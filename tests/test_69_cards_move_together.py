"""Tests for Ticket 69: Both cards move together — every stage, cancel, reassignment and a stale click.

Covers:
- Retired states (cancelled, reassigned with note, delivered) have no buttons in build_dm_card_blocks.
- A thread click moves the DM card, and the keyword does too.
- A run from the DM keeps both cards level (processed -> confirmed -> delivered).
- Cancel and reassignment retire cards.
- A stale click refreshes the DM card; a failed refresh never blocks approval or updates and alerts admins.
"""
import json
from unittest.mock import MagicMock

import pytest

from src import app, blocks, config, lifecycle, log_writer, queue_worker, roster, slack_io


@pytest.fixture
def clean_roster(tmp_path, monkeypatch):
    roster_file = str(tmp_path / "roster.json")
    monkeypatch.setattr(roster, "ROSTER_PATH", roster_file)
    roster._DATA = None
    data = {
        "admins": ["U_ADMIN"],
        "approvers": ["U_CHARLIE"],
        "buyers": ["U_BUYER", "U_OTHER_BUYER"],
        "requesters": {
            "U_ADMIN": "Isaac",
            "U_CHARLIE": "Charlie H.",
            "U_BUYER": "Dylan",
            "U_OTHER_BUYER": "Bob",
            "U_REQ": "Alex",
        },
        "vendors": [],
    }
    with open(roster_file, "w", encoding="utf-8") as f:
        json.dump(data, f)
    yield


@pytest.fixture
def sync_queue(monkeypatch):
    def fake_submit(action_fn, *args, **kwargs):
        result = action_fn()
        if "success_callback" in kwargs and kwargs["success_callback"]:
            kwargs["success_callback"](result)
        return result

    monkeypatch.setattr(queue_worker, "submit_write_task", fake_submit)


def _make_thread_card_message(ts: str, state: str, req_data: dict, history: list | None = None):
    btn_val = json.dumps({
        "state": state,
        "row": req_data.get("row", 17),
        "request": req_data,
        "history": history or [],
    })
    return {
        "ts": ts,
        "text": f"🛒 Purchase Request ({state.capitalize()})",
        "blocks": [
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"Card for {req_data.get('item_description', 'Item')}"},
            },
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "Next Stage"},
                        "action_id": f"req_{state}",
                        "value": btn_val,
                    }
                ],
            },
        ],
        "metadata": {
            "event_type": "purchase_request",
            "event_payload": req_data,
        },
    }


def _make_dm_click_body(action_id: str, user_id: str, thread_channel: str = "C123", thread_ts: str = "1000.0", card_ts: str = "1000.1"):
    return {
        "user": {"id": user_id},
        "channel": {"id": "D_BUYER"},
        "message": {"ts": "2000.1"},
        "container": {"message_ts": "2000.1"},
        "actions": [
            {
                "action_id": action_id,
                "value": json.dumps({
                    "thread_channel": thread_channel,
                    "thread_ts": thread_ts,
                    "card_ts": card_ts,
                }),
            }
        ],
    }


def test_retired_states_have_no_buttons():
    """AC 1: build_dm_card_blocks for cancelled, reassigned (with a note), and delivered

    returns no actions block, and section/context text contains Cancelled, the note,
    and Delivered respectively.
    """
    req = {"item_description": "Widgets", "vendor": "Acme", "total_price": 50.0}

    # 1. Cancelled
    blocks_cancelled = blocks.build_dm_card_blocks(
        state="cancelled",
        request=req,
        thread_channel="C123",
        thread_ts="1000.0",
        card_ts="1000.1",
    )
    assert not any(b.get("type") == "actions" for b in blocks_cancelled)
    text_cancelled = "\n".join(b.get("text", {}).get("text", "") for b in blocks_cancelled)
    assert "Cancelled" in text_cancelled

    # 2. Reassigned with note
    blocks_reassigned = blocks.build_dm_card_blocks(
        state="reassigned",
        request=req,
        thread_channel="C123",
        thread_ts="1000.0",
        card_ts="1000.1",
        note="Reassigned to Bob",
    )
    assert not any(b.get("type") == "actions" for b in blocks_reassigned)
    text_reassigned = "\n".join(b.get("text", {}).get("text", "") for b in blocks_reassigned)
    assert "Reassigned to Bob" in text_reassigned

    # 3. Delivered
    blocks_delivered = blocks.build_dm_card_blocks(
        state="delivered",
        request=req,
        thread_channel="C123",
        thread_ts="1000.0",
        card_ts="1000.1",
    )
    assert not any(b.get("type") == "actions" for b in blocks_delivered)
    text_delivered = "\n".join(b.get("text", {}).get("text", "") for b in blocks_delivered)
    assert "Delivered" in text_delivered


def test_thread_click_and_keyword_moves_dm_card(clean_roster, sync_queue, monkeypatch):
    """AC 2: A thread click moves the DM card, and the keyword does too.

    A request with dm_channel="D_BUYER", dm_ts="9.9":
    - Assignee's Mark Processed click produces chat_update(channel="D_BUYER", ts="9.9") with 'Mark Confirmed'
    - Keyword 'processed' via real app.dispatch_command produces the same
    - A request without the two keys produces exactly one chat_update (thread card) and none with ts=="9.9".
    """
    updated_rows = []
    monkeypatch.setattr(log_writer, "update_row", lambda row, vals: updated_rows.append((row, vals)))
    monkeypatch.setattr(log_writer, "get_row_info", lambda row: {"item_description": "Widgets"})

    # 1. Thread button click with DM references
    client = MagicMock()
    req_with_dm = {
        "item_description": "Widgets",
        "vendor": "Acme",
        "total_price": 50.0,
        "assignee_id": "U_BUYER",
        "dm_channel": "D_BUYER",
        "dm_ts": "9.9",
        "row": 17,
    }
    say = MagicMock()

    lifecycle.handle_processed(
        client=client,
        say=say,
        channel="C123",
        thread_ts="1000.0",
        user_id="U_BUYER",
        event_ts="1000.2",
        text="",
        card_ts="1000.1",
        req_data=req_with_dm,
        history=[],
    )

    # Check chat_update calls on client
    # Expect 1 update for thread card ("C123", ts="1000.1") and 1 for DM card ("D_BUYER", ts="9.9")
    dm_updates = [c for c in client.chat_update.call_args_list if c[1].get("channel") == "D_BUYER" and c[1].get("ts") == "9.9"]
    assert len(dm_updates) == 1
    dm_call_kwargs = dm_updates[0][1]
    dm_btn_texts = []
    for b in dm_call_kwargs.get("blocks", []):
        if b.get("type") == "actions":
            for elem in b.get("elements", []):
                dm_btn_texts.append(elem.get("text", {}).get("text", ""))
    assert any("Mark Confirmed" in t for t in dm_btn_texts)

    # 2. Keyword 'processed' via real app.dispatch_command
    client.reset_mock()
    thread_card_msg = _make_thread_card_message("1000.1", "approved", req_with_dm)
    client.conversations_replies.return_value = {
        "ok": True,
        "messages": [
            {"ts": "1000.0", "text": "Parent message"},
            thread_card_msg,
            {"ts": "1000.05", "text": "Logged to row 17 in Purchasing-Log.xlsx"},
        ],
    }
    say = MagicMock()

    app.dispatch_command(
        client=client,
        say=say,
        channel="C123",
        thread_ts="1000.0",
        user="U_BUYER",
        event_ts="1000.3",
        text="processed",
        respond=None,
    )

    dm_updates = [c for c in client.chat_update.call_args_list if c[1].get("channel") == "D_BUYER" and c[1].get("ts") == "9.9"]
    assert len(dm_updates) == 1
    dm_call_kwargs = dm_updates[0][1]
    dm_btn_texts = [elem.get("text", {}).get("text", "") for b in dm_call_kwargs.get("blocks", []) if b.get("type") == "actions" for elem in b.get("elements", [])]
    assert any("Mark Confirmed" in t for t in dm_btn_texts)

    # 3. Request WITHOUT DM references
    client.reset_mock()
    req_no_dm = {
        "item_description": "Widgets",
        "vendor": "Acme",
        "total_price": 50.0,
        "assignee_id": "U_BUYER",
        "row": 17,
    }
    lifecycle.handle_processed(
        client=client,
        say=say,
        channel="C123",
        thread_ts="1000.0",
        user_id="U_BUYER",
        event_ts="1000.4",
        text="",
        card_ts="1000.1",
        req_data=req_no_dm,
        history=[],
    )
    assert client.chat_update.call_count == 1
    assert client.chat_update.call_args[1].get("channel") == "C123"
    assert not any(c[1].get("ts") == "9.9" for c in client.chat_update.call_args_list)


def test_run_from_dm_keeps_both_cards_level(clean_roster, sync_queue, monkeypatch):
    """AC 3: Click dm_req_processed, then dm_req_confirmed, then dm_req_delivered

    through app.handle_dm_stage_action, feeding each chat_update back into the fake thread:
    - after each click both cards show the same next button
    - after delivered neither has an actions block.
    """
    updated_rows = []
    monkeypatch.setattr(log_writer, "update_row", lambda row, vals: updated_rows.append((row, vals)))
    monkeypatch.setattr(log_writer, "get_row_info", lambda row: {"item_description": "Widgets"})

    thread_card_msg = _make_thread_card_message(
        ts="1000.1",
        state="approved",
        req_data={
            "item_description": "Widgets",
            "vendor": "Acme",
            "total_price": 50.0,
            "assignee_id": "U_BUYER",
            "dm_channel": "D_BUYER",
            "dm_ts": "9.9",
            "row": 17,
        },
    )

    client = MagicMock()

    def fake_replies(channel, ts=None, **kwargs):
        return {"ok": True, "messages": [{"ts": "1000.0", "text": "Parent"}, thread_card_msg]}

    client.conversations_replies.side_effect = fake_replies

    def record_chat_update(**kwargs):
        if kwargs.get("channel") == "C123" and kwargs.get("ts") == "1000.1":
            thread_card_msg["blocks"] = kwargs.get("blocks", [])
            thread_card_msg["text"] = kwargs.get("text", "")
            if "metadata" in kwargs:
                thread_card_msg["metadata"] = kwargs["metadata"]
        return {"ok": True}

    client.chat_update.side_effect = record_chat_update

    # --- Step 1: Click dm_req_processed ---
    ack = MagicMock()
    respond = MagicMock()
    body_proc = _make_dm_click_body(config.ACTION_DM_REQ_PROCESSED, "U_BUYER")
    app.handle_dm_stage_action(ack, body_proc, respond, client)
    respond.assert_not_called()

    # Find the DM card update from this step
    dm_calls = [c[1] for c in client.chat_update.call_args_list if c[1].get("channel") == "D_BUYER" and c[1].get("ts") == "9.9"]
    assert len(dm_calls) >= 1
    dm_last_proc = dm_calls[-1]
    # Check next button on both cards: "Mark Confirmed"
    thread_btn_names = [e.get("text", {}).get("text", "") for b in thread_card_msg["blocks"] if b.get("type") == "actions" for e in b.get("elements", [])]
    dm_btn_names = [e.get("text", {}).get("text", "") for b in dm_last_proc["blocks"] if b.get("type") == "actions" for e in b.get("elements", [])]
    assert any("Mark Confirmed" in t for t in thread_btn_names)
    assert any("Mark Confirmed" in t for t in dm_btn_names)

    # --- Step 2: Click dm_req_confirmed ---
    client.chat_update.reset_mock()
    body_conf = _make_dm_click_body(config.ACTION_DM_REQ_CONFIRMED, "U_BUYER")
    app.handle_dm_stage_action(ack, body_conf, respond, client)
    respond.assert_not_called()

    dm_calls = [c[1] for c in client.chat_update.call_args_list if c[1].get("channel") == "D_BUYER" and c[1].get("ts") == "9.9"]
    assert len(dm_calls) >= 1
    dm_last_conf = dm_calls[-1]
    thread_btn_names = [e.get("text", {}).get("text", "") for b in thread_card_msg["blocks"] if b.get("type") == "actions" for e in b.get("elements", [])]
    dm_btn_names = [e.get("text", {}).get("text", "") for b in dm_last_conf["blocks"] if b.get("type") == "actions" for e in b.get("elements", [])]
    assert any("Mark Delivered" in t for t in thread_btn_names)
    assert any("Mark Delivered" in t for t in dm_btn_names)

    # --- Step 3: Click dm_req_delivered ---
    client.chat_update.reset_mock()
    body_deliv = _make_dm_click_body(config.ACTION_DM_REQ_DELIVERED, "U_BUYER")
    app.handle_dm_stage_action(ack, body_deliv, respond, client)
    respond.assert_not_called()

    dm_calls = [c[1] for c in client.chat_update.call_args_list if c[1].get("channel") == "D_BUYER" and c[1].get("ts") == "9.9"]
    assert len(dm_calls) >= 1
    dm_last_deliv = dm_calls[-1]
    assert not any(b.get("type") == "actions" for b in thread_card_msg["blocks"])
    assert not any(b.get("type") == "actions" for b in dm_last_deliv["blocks"])


def test_cancel_and_reassignment_retire_cards(clean_roster, sync_queue, monkeypatch):
    """AC 4: Cancel and reassignment retire cards.

    - handle_cancel on approved request with DM references: DM card updated to cancelled (no actions, contains Cancelled)
    - handle_cancel without DM references: no DM card update
    - handle_assign moving to second buyer: first DM card updated to reassigned, second DM card posted, thread card holds second DM references.
    """
    monkeypatch.setattr(log_writer, "blank_row", lambda row: None)
    monkeypatch.setattr(log_writer, "get_row_info", lambda row: {"item_description": "Widgets"})
    monkeypatch.setattr(slack_io, "find_all_rows_in_thread", lambda client, channel, thread_ts: [17])

    client = MagicMock()
    say = MagicMock()

    # 1. Cancel with DM references
    req_with_dm = {
        "item_description": "Widgets",
        "vendor": "Acme",
        "total_price": 50.0,
        "assignee_id": "U_BUYER",
        "dm_channel": "D_BUYER",
        "dm_ts": "9.9",
        "row": 17,
    }
    lifecycle.handle_cancel(
        client=client,
        say=say,
        channel="C123",
        thread_ts="1000.0",
        msg_ts="1000.1",
        user_id="U_CHARLIE",
        req_data=req_with_dm,
        state="approved",
        history=[],
    )
    dm_updates = [c[1] for c in client.chat_update.call_args_list if c[1].get("channel") == "D_BUYER" and c[1].get("ts") == "9.9"]
    assert len(dm_updates) == 1
    assert not any(b.get("type") == "actions" for b in dm_updates[0].get("blocks", []))
    text_cancelled = "\n".join(b.get("text", {}).get("text", "") for b in dm_updates[0].get("blocks", []))
    assert "Cancelled" in text_cancelled

    # 2. Cancel without DM references
    client.reset_mock()
    req_no_dm = {
        "item_description": "Widgets",
        "vendor": "Acme",
        "total_price": 50.0,
        "assignee_id": "U_BUYER",
        "row": 17,
    }
    lifecycle.handle_cancel(
        client=client,
        say=say,
        channel="C123",
        thread_ts="1000.0",
        msg_ts="1000.1",
        user_id="U_CHARLIE",
        req_data=req_no_dm,
        state="approved",
        history=[],
    )
    assert not any(c[1].get("channel") == "D_BUYER" for c in client.chat_update.call_args_list)

    # 3. Reassignment from U_BUYER to U_OTHER_BUYER
    client.reset_mock()
    client.conversations_open.return_value = {"channel": {"id": "D_OTHER_BUYER"}}
    client.chat_postMessage.return_value = {"channel": "D_OTHER_BUYER", "ts": "99.99"}

    reassign_req = dict(req_with_dm)
    lifecycle.handle_assign(
        client=client,
        say=say,
        channel="C123",
        thread_ts="1000.0",
        user_id="U_CHARLIE",
        event_ts="1000.5",
        target_user_id="U_OTHER_BUYER",
        req_data=reassign_req,
        msg_ts="1000.1",
        history=[],
        current_state="approved",
    )

    # Old buyer's DM card (D_BUYER, 9.9) retired to reassigned
    old_dm_updates = [c[1] for c in client.chat_update.call_args_list if c[1].get("channel") == "D_BUYER" and c[1].get("ts") == "9.9"]
    assert len(old_dm_updates) == 1
    assert not any(b.get("type") == "actions" for b in old_dm_updates[0].get("blocks", []))
    text_reassigned = "\n".join(b.get("text", {}).get("text", "") for b in old_dm_updates[0].get("blocks", []))
    assert "Reassigned to Bob" in text_reassigned

    # New buyer received DM card
    new_dm_posts = [c[1] for c in client.chat_postMessage.call_args_list if c[1].get("channel") == "U_OTHER_BUYER" and c[1].get("blocks")]
    assert len(new_dm_posts) >= 1

    # Thread card's last chat_update holds second card's references
    thread_updates = [c[1] for c in client.chat_update.call_args_list if c[1].get("channel") == "C123" and c[1].get("ts") == "1000.1"]
    assert len(thread_updates) >= 1
    last_thread_update = thread_updates[-1]
    meta_payload = last_thread_update.get("metadata", {}).get("event_payload", {})
    assert meta_payload.get("dm_channel") == "D_OTHER_BUYER"
    assert meta_payload.get("dm_ts") == "99.99"


def test_stale_click_refreshes_and_failed_refresh_never_blocks(clean_roster, sync_queue, monkeypatch):
    """AC 5: A stale click refreshes; a failed refresh never blocks.

    - A dm_req_processed click when the thread is already 'processed':
      refused with 'already', and the DM card is updated to the 'processed' state's blocks.
    - With chat_update raising only for the DM card, a normal Mark Processed click still
      calls update_row once and updates the thread card, and exactly one message goes to
      the alert channel containing 'update the buyer's DM card'.
    """
    updated_rows = []
    monkeypatch.setattr(log_writer, "update_row", lambda row, vals: updated_rows.append((row, vals)))
    monkeypatch.setattr(log_writer, "get_row_info", lambda row: {"item_description": "Widgets"})
    monkeypatch.setattr(config, "ADMIN_ALERT_CHANNEL", "C_ADMIN")

    # 1. Stale click
    thread_card_msg = _make_thread_card_message(
        ts="1000.1",
        state="processed",  # already processed
        req_data={
            "item_description": "Widgets",
            "vendor": "Acme",
            "total_price": 50.0,
            "assignee_id": "U_BUYER",
            "dm_channel": "D_BUYER",
            "dm_ts": "9.9",
            "row": 17,
        },
    )
    client = MagicMock()
    client.conversations_replies.return_value = {"ok": True, "messages": [{"ts": "1000.0", "text": "Parent"}, thread_card_msg]}

    ack = MagicMock()
    respond = MagicMock()
    body_stale = _make_dm_click_body(config.ACTION_DM_REQ_PROCESSED, "U_BUYER")

    app.handle_dm_stage_action(ack, body_stale, respond, client)
    respond.assert_called_once()
    called_text = respond.call_args[1].get("text") if respond.call_args[1] else respond.call_args[0][0]
    assert "already" in called_text

    # DM card refreshed to 'processed' blocks (contains 'Mark Confirmed')
    dm_calls = [c[1] for c in client.chat_update.call_args_list if c[1].get("channel") == "D_BUYER" and c[1].get("ts") == "9.9"]
    assert len(dm_calls) == 1
    dm_btn_names = [e.get("text", {}).get("text", "") for b in dm_calls[0].get("blocks", []) if b.get("type") == "actions" for e in b.get("elements", [])]
    assert any("Mark Confirmed" in t for t in dm_btn_names)

    # 2. Failed DM card update never blocks thread card update or row write, and alerts admin
    client.reset_mock()
    say = MagicMock()

    def chat_update_side_effect(**kwargs):
        if kwargs.get("channel") == "D_BUYER":
            raise RuntimeError("Slack API DM update failure")
        return {"ok": True}

    client.chat_update.side_effect = chat_update_side_effect

    req_with_dm = {
        "item_description": "Widgets",
        "vendor": "Acme",
        "total_price": 50.0,
        "assignee_id": "U_BUYER",
        "dm_channel": "D_BUYER",
        "dm_ts": "9.9",
        "row": 17,
    }
    lifecycle.handle_processed(
        client=client,
        say=say,
        channel="C123",
        thread_ts="1000.0",
        user_id="U_BUYER",
        event_ts="1000.2",
        text="",
        card_ts="1000.1",
        req_data=req_with_dm,
        history=[],
    )

    # update_row was called once
    assert len(updated_rows) == 1
    # thread card was updated
    thread_updates = [c[1] for c in client.chat_update.call_args_list if c[1].get("channel") == "C123"]
    assert len(thread_updates) == 1
    # alert posted to admin channel containing "update the buyer's DM card"
    admin_alerts = [c[1] for c in client.chat_postMessage.call_args_list if c[1].get("channel") == "C_ADMIN"]
    assert len(admin_alerts) == 1
    assert "update the buyer's DM card" in admin_alerts[0].get("text", "")
