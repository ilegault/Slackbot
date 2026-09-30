"""Tests for Ticket 68: A click on the DM card advances the request.

Covers:
- Bolt registration: handle_dm_stage_action registered for 3 DM actions.
- slack_io.get_card_by_ts reads button value, not metadata, and picks the exact card.
- Assignee's DM click advances the request for processed, confirmed, and delivered stages.
- Permission enforcement: different buyer, unassigned request, and unregistered user refused privately;
  admin and approver succeed.
- Stale click refused with 'already <stage>'; vanished card refused and alerted to admin channel.
"""
import json
from unittest.mock import MagicMock

import pytest

from src import app, config, log_writer, queue_worker, roster, slack_io, text_rules


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


def _make_thread_card_message(ts: str, state: str, req_data: dict, history: list | None = None, meta_state: str | None = None):
    btn_val = json.dumps({
        "state": state,
        "row": req_data.get("row", 15),
        "request": req_data,
        "history": history or [],
    })
    msg = {
        "ts": ts,
        "blocks": [
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"Card for {req_data.get('item_description')}"},
            },
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "Next Stage"},
                        "action_id": "some_stage_action",
                        "value": btn_val,
                    }
                ],
            },
        ],
    }
    if meta_state:
        msg["metadata"] = {
            "event_type": "purchase_request",
            "event_payload": {"state": meta_state, "item_description": req_data.get("item_description")},
        }
    return msg


def _make_dm_click_body(action_id: str, user_id: str, thread_channel: str = "C123", thread_ts: str = "1000.0", card_ts: str = "1000.1"):
    return {
        "user": {"id": user_id},
        "channel": {"id": "D_BUYER"},
        "message": {"ts": "2000.1"},
        "container": {"message_ts": "2000.1"},  # NO container.thread_ts on DM click
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


# ---------------------------------------------------------------------------
# Acceptance Criterion 1: Registered once per stage
# ---------------------------------------------------------------------------

def test_dm_stage_action_registered_once_per_stage():
    """In tests/test_68_dm_click.py,
    sum(1 for l in app.app._listeners if l.ack_function is app.handle_dm_stage_action) == 3
    """
    assert hasattr(app, "handle_dm_stage_action"), "app must define handle_dm_stage_action"
    count = sum(1 for listener in app.app._listeners if getattr(listener, "ack_function", None) is app.handle_dm_stage_action)
    assert count == 3, f"Expected 3 registrations for handle_dm_stage_action, found {count}"


# ---------------------------------------------------------------------------
# Acceptance Criterion 2: get_card_by_ts reads button value, not metadata, exact card
# ---------------------------------------------------------------------------

def test_get_card_by_ts_reads_button_value_and_picks_exact_card():
    """A fake thread with two cards, one whose metadata says 'posted' but whose button value
    says 'approved': asking for that card's ts returns state 'approved' and its own history;
    the other card's ts returns the other card; an unknown ts returns None.
    """
    assert hasattr(slack_io, "get_card_by_ts"), "slack_io must define get_card_by_ts"

    msg1 = _make_thread_card_message(
        ts="100.1",
        state="approved",
        req_data={"item_description": "Widget A", "vendor": "Vendor A"},
        history=["Approved by Charlie"],
        meta_state="posted",
    )
    msg2 = _make_thread_card_message(
        ts="100.2",
        state="processed",
        req_data={"item_description": "Widget B", "vendor": "Vendor B"},
        history=["Processed by Dylan"],
        meta_state="posted",
    )

    client = MagicMock()
    client.conversations_replies.return_value = {"messages": [msg1, msg2]}

    card1 = slack_io.get_card_by_ts(client, channel="C123", thread_ts="100.0", card_ts="100.1")
    assert card1 is not None
    req1, hist1, state1 = card1
    assert state1 == "approved"
    assert hist1 == ["Approved by Charlie"]
    assert req1.get("item_description") == "Widget A"

    card2 = slack_io.get_card_by_ts(client, channel="C123", thread_ts="100.0", card_ts="100.2")
    assert card2 is not None
    req2, hist2, state2 = card2
    assert state2 == "processed"
    assert hist2 == ["Processed by Dylan"]
    assert req2.get("item_description") == "Widget B"

    card_unknown = slack_io.get_card_by_ts(client, channel="C123", thread_ts="100.0", card_ts="999.9")
    assert card_unknown is None


# ---------------------------------------------------------------------------
# Acceptance Criterion 3: Assignee click advances request for each stage
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "stage_name,action_id,thread_state,expected_col",
    [
        ("processed", config.ACTION_DM_REQ_PROCESSED, "approved", config.COLUMN_DATE_PROCESSED),
        ("confirmed", config.ACTION_DM_REQ_CONFIRMED, "processed", config.COLUMN_DATE_CONFIRMED),
        ("delivered", config.ACTION_DM_REQ_DELIVERED, "confirmed", config.COLUMN_DATE_DELIVERY),
    ],
)
def test_assignee_click_advances_request(
    clean_roster, sync_queue, monkeypatch, stage_name, action_id, thread_state, expected_col
):
    """The assignee's click advances the request, for each stage.
    update_row called once with expected column dict,
    chat_update called with channel=='C123', thread card ts, next stage's button,
    chat_postMessage(channel='C123', thread_ts=...) confirms in thread.
    """
    row_updates = []
    monkeypatch.setattr(log_writer, "update_row", lambda row, fields: row_updates.append((row, fields)))

    req_data = {
        "item_description": "Widget",
        "row": 15,
        "assignee_id": "U_BUYER",
        "assignee": "Dylan",
        "user_id": "U_REQ",
        "requester": "Alex",
        "total_price": 50.0,
        "vendor": "Acme",
        "dm_channel": "D_BUYER",
        "dm_ts": "2000.1",
    }
    history = [f"Stage {thread_state} by Someone"]
    thread_msg = _make_thread_card_message(ts="1000.1", state=thread_state, req_data=req_data, history=history)
    logged_msg = {"text": "Logged to row 15", "ts": "1000.0"}

    client = MagicMock()
    client.conversations_replies.return_value = {"messages": [logged_msg, thread_msg]}

    body = _make_dm_click_body(action_id=action_id, user_id="U_BUYER", thread_channel="C123", thread_ts="1000.0", card_ts="1000.1")
    ack = MagicMock()
    respond = MagicMock()

    app.handle_dm_stage_action(ack=ack, body=body, respond=respond, client=client)

    ack.assert_called_once()
    assert respond.call_count == 0, "Authorized assignee click should not be refused"

    # Assert update_row was called once with dict containing expected_col
    assert len(row_updates) == 1
    row_num, fields = row_updates[0]
    assert row_num == 15
    assert expected_col in fields

    # Assert chat_update called with channel == "C123" and card_ts == "1000.1"
    update_calls = [c for c in client.chat_update.call_args_list if c.kwargs.get("channel") == "C123" and c.kwargs.get("ts") == "1000.1"]
    assert len(update_calls) == 1
    updated_blocks = update_calls[0].kwargs.get("blocks", [])

    # Check button on updated thread card
    action_blocks = [b for b in updated_blocks if b.get("type") == "actions"]
    if stage_name == "delivered":
        # None after delivered
        assert len(action_blocks) == 0
    elif stage_name == "processed":
        # Next button is Mark Confirmed
        assert len(action_blocks) == 1
        btn = action_blocks[0]["elements"][0]
        assert btn["action_id"] == "req_confirmed"
    elif stage_name == "confirmed":
        # Next button is Mark Delivered
        assert len(action_blocks) == 1
        btn = action_blocks[0]["elements"][0]
        assert btn["action_id"] == "req_delivered"

    # Assert chat_postMessage(channel="C123", thread_ts=...) confirms it in the thread
    thread_posts = [
        c for c in client.chat_postMessage.call_args_list
        if c.kwargs.get("channel") == "C123" and c.kwargs.get("thread_ts") == "1000.0"
    ]
    assert len(thread_posts) >= 1


# ---------------------------------------------------------------------------
# Acceptance Criterion 4: Everyone else is refused privately and nothing written
# ---------------------------------------------------------------------------

def test_different_buyer_refused_privately(clean_roster, monkeypatch):
    row_updates = []
    monkeypatch.setattr(log_writer, "update_row", lambda row, fields: row_updates.append((row, fields)))

    req_data = {
        "item_description": "Widget",
        "row": 15,
        "assignee_id": "U_BUYER",
        "assignee": "Dylan",
        "user_id": "U_REQ",
        "requester": "Alex",
    }
    thread_msg = _make_thread_card_message(ts="1000.1", state="approved", req_data=req_data)

    client = MagicMock()
    client.conversations_replies.return_value = {"messages": [thread_msg]}

    body = _make_dm_click_body(action_id=config.ACTION_DM_REQ_PROCESSED, user_id="U_OTHER_BUYER")
    ack = MagicMock()
    respond = MagicMock()

    app.handle_dm_stage_action(ack=ack, body=body, respond=respond, client=client)

    ack.assert_called_once()
    assert len(row_updates) == 0
    assert client.chat_update.call_count == 0
    respond.assert_called_once_with(
        text=text_rules.format_stage_denial("U_BUYER"),
        response_type="ephemeral",
        replace_original=False,
    )


def test_unassigned_request_refused_privately(clean_roster, monkeypatch):
    row_updates = []
    monkeypatch.setattr(log_writer, "update_row", lambda row, fields: row_updates.append((row, fields)))

    req_data = {
        "item_description": "Widget",
        "row": 15,
        "assignee_id": None,
        "user_id": "U_REQ",
        "requester": "Alex",
    }
    thread_msg = _make_thread_card_message(ts="1000.1", state="approved", req_data=req_data)

    client = MagicMock()
    client.conversations_replies.return_value = {"messages": [thread_msg]}

    body = _make_dm_click_body(action_id=config.ACTION_DM_REQ_PROCESSED, user_id="U_BUYER")
    ack = MagicMock()
    respond = MagicMock()

    app.handle_dm_stage_action(ack=ack, body=body, respond=respond, client=client)

    ack.assert_called_once()
    assert len(row_updates) == 0
    assert client.chat_update.call_count == 0
    respond.assert_called_once_with(
        text=text_rules.format_stage_unassigned(),
        response_type="ephemeral",
        replace_original=False,
    )


def test_unregistered_user_refused_privately(clean_roster, monkeypatch):
    row_updates = []
    monkeypatch.setattr(log_writer, "update_row", lambda row, fields: row_updates.append((row, fields)))

    req_data = {
        "item_description": "Widget",
        "row": 15,
        "assignee_id": "U_GHOST",
        "user_id": "U_REQ",
        "requester": "Alex",
    }
    thread_msg = _make_thread_card_message(ts="1000.1", state="approved", req_data=req_data)

    client = MagicMock()
    client.conversations_replies.return_value = {"messages": [thread_msg]}
    client.users_info.return_value = {"ok": False}

    body = _make_dm_click_body(action_id=config.ACTION_DM_REQ_PROCESSED, user_id="U_GHOST")
    ack = MagicMock()
    respond = MagicMock()

    app.handle_dm_stage_action(ack=ack, body=body, respond=respond, client=client)

    ack.assert_called_once()
    assert len(row_updates) == 0
    assert client.chat_update.call_count == 0
    respond.assert_called_once_with(
        text="🔒 You must be registered in the lab roster to update requests. Use `/roster-set-name` first.",
        response_type="ephemeral",
        replace_original=False,
    )


def test_approver_and_admin_not_refused(clean_roster, sync_queue, monkeypatch):
    row_updates = []
    monkeypatch.setattr(log_writer, "update_row", lambda row, fields: row_updates.append((row, fields)))

    req_data = {
        "item_description": "Widget",
        "row": 15,
        "assignee_id": "U_BUYER",
        "assignee": "Dylan",
        "user_id": "U_REQ",
        "requester": "Alex",
    }
    thread_msg = _make_thread_card_message(ts="1000.1", state="approved", req_data=req_data)
    logged_msg = {"text": "Logged to row 15", "ts": "1000.0"}

    client = MagicMock()
    client.conversations_replies.return_value = {"messages": [logged_msg, thread_msg]}

    # Test Charlie (approver)
    body = _make_dm_click_body(action_id=config.ACTION_DM_REQ_PROCESSED, user_id="U_CHARLIE")
    ack = MagicMock()
    respond = MagicMock()
    app.handle_dm_stage_action(ack=ack, body=body, respond=respond, client=client)
    assert respond.call_count == 0
    assert len(row_updates) == 1

    # Test Isaac (admin)
    row_updates.clear()
    body = _make_dm_click_body(action_id=config.ACTION_DM_REQ_PROCESSED, user_id="U_ADMIN")
    ack = MagicMock()
    respond = MagicMock()
    app.handle_dm_stage_action(ack=ack, body=body, respond=respond, client=client)
    assert respond.call_count == 0
    assert len(row_updates) == 1


# ---------------------------------------------------------------------------
# Acceptance Criterion 5: Stale click and vanished card
# ---------------------------------------------------------------------------

def test_stale_click_refused_privately(clean_roster, monkeypatch):
    """With thread card already in state 'processed', a dm_req_processed click:
    respond text contains 'already', update_row not called.
    """
    row_updates = []
    monkeypatch.setattr(log_writer, "update_row", lambda row, fields: row_updates.append((row, fields)))

    req_data = {
        "item_description": "Widget",
        "row": 15,
        "assignee_id": "U_BUYER",
        "assignee": "Dylan",
        "user_id": "U_REQ",
        "requester": "Alex",
    }
    thread_msg = _make_thread_card_message(ts="1000.1", state="processed", req_data=req_data)

    client = MagicMock()
    client.conversations_replies.return_value = {"messages": [thread_msg]}

    body = _make_dm_click_body(action_id=config.ACTION_DM_REQ_PROCESSED, user_id="U_BUYER")
    ack = MagicMock()
    respond = MagicMock()

    app.handle_dm_stage_action(ack=ack, body=body, respond=respond, client=client)

    ack.assert_called_once()
    assert len(row_updates) == 0
    assert client.chat_update.call_count == 0
    assert respond.call_count == 1
    refusal_text = respond.call_args[1].get("text", "")
    assert "already" in refusal_text
    assert "*processed*" in refusal_text


def test_vanished_card_refused_privately_and_alerted(clean_roster, monkeypatch):
    """With card missing from the thread: refused with 'can't find' text,
    update_row not called, and one message to the alert channel containing 'find the card for a DM click'.
    """
    row_updates = []
    monkeypatch.setattr(log_writer, "update_row", lambda row, fields: row_updates.append((row, fields)))
    monkeypatch.setattr(config, "ADMIN_ALERT_CHANNEL", "C_ALERTS")

    client = MagicMock()
    # conversations_replies returns empty list (card not found)
    client.conversations_replies.return_value = {"messages": []}

    body = _make_dm_click_body(action_id=config.ACTION_DM_REQ_PROCESSED, user_id="U_BUYER")
    ack = MagicMock()
    respond = MagicMock()

    app.handle_dm_stage_action(ack=ack, body=body, respond=respond, client=client)

    ack.assert_called_once()
    assert len(row_updates) == 0
    assert client.chat_update.call_count == 0

    assert respond.call_count == 1
    refusal_text = respond.call_args[1].get("text", "")
    assert "can't find the request card in the thread any more" in refusal_text

    alert_calls = [
        c for c in client.chat_postMessage.call_args_list
        if c.kwargs.get("channel") == "C_ALERTS"
    ]
    assert len(alert_calls) == 1
    alert_text = alert_calls[0].kwargs.get("text", "")
    assert "find the card for a DM click" in alert_text
