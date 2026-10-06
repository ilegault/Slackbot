"""Tests for Ticket 72: Any buyer can move an approved request from the thread card.

Covers ADR 0011 decisions 1–2: any buyer, approver or admin may set or change the
assignee before Processed; the approved thread card carries the buyer picker.
"""
import json
from unittest.mock import MagicMock

import pytest

from src import app, blocks, config, queue_worker, roster, slack_io


@pytest.fixture
def clean_roster(tmp_path, monkeypatch):
    roster_file = str(tmp_path / "roster.json")
    monkeypatch.setattr(roster, "ROSTER_PATH", roster_file)
    roster._DATA = None
    data = {
        "admins": ["U_ADMIN"],
        "approvers": ["U_CHARLIE"],
        "buyers": ["U_BUYER_A", "U_BUYER_B", "U_BUYER_C"],
        "requesters": {
            "U_ADMIN": "Isaac",
            "U_CHARLIE": "Charlie H.",
            "U_BUYER_A": "Alice",
            "U_BUYER_B": "Bob",
            "U_BUYER_C": "Carol",
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
        "text": f"Purchase Request ({state.capitalize()})",
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


def _make_picker_body(user_id: str, selected_user: str, req_data: dict, history: list):
    """Build the body for a req_assign_select action click on an approved card."""
    btn_val = json.dumps({
        "state": "approved",
        "request": req_data,
        "history": history,
    })
    return {
        "user": {"id": user_id},
        "channel": {"id": "C123"},
        "message": {
            "ts": "1000.1",
            "blocks": [
                {"type": "section", "text": {"type": "mrkdwn", "text": "Card"}},
                {
                    "type": "actions",
                    "elements": [
                        {
                            "type": "button",
                            "action_id": "req_processed",
                            "value": btn_val,
                        },
                        {
                            "type": "button",
                            "action_id": "req_cancel",
                            "value": btn_val,
                        },
                        {
                            "type": "users_select",
                            "action_id": config.ACTION_REQ_ASSIGN_SELECT,
                        },
                    ],
                },
            ],
        },
        "container": {"thread_ts": "1000.0"},
        "actions": [
            {
                "action_id": config.ACTION_REQ_ASSIGN_SELECT,
                "selected_user": selected_user,
            }
        ],
    }


def test_approved_card_has_picker(clean_roster):
    """AC 1: build_request_blocks('approved') has a static_select picker with the right
    action_id and initial_option; unassigned approved card has no initial_option and
    placeholder 'Assign a buyer'; processed/confirmed/delivered have no picker.
    """
    req_with_buyer = {
        "item_description": "Laser diode",
        "vendor": "Thorlabs",
        "total_price": 120.0,
        "assignee_id": "U_BUYER_A",
        "assignee": "Alice",
    }

    # Approved with assignee — picker present, action_id matches, initial_option set
    blks = blocks.build_request_blocks("approved", req_with_buyer)
    all_elements = [e for b in blks if b.get("type") == "actions" for e in b.get("elements", [])]
    pickers = [e for e in all_elements if e.get("action_id") == config.ACTION_REQ_ASSIGN_SELECT]
    assert len(pickers) == 1
    assert pickers[0]["type"] == "static_select"
    assert pickers[0].get("initial_option", {}).get("value") == "U_BUYER_A"

    # Approved without assignee — picker present, no initial_option, correct placeholder
    req_no_buyer = {"item_description": "Laser diode", "vendor": "Thorlabs", "total_price": 120.0}
    blks2 = blocks.build_request_blocks("approved", req_no_buyer)
    all_elements2 = [e for b in blks2 if b.get("type") == "actions" for e in b.get("elements", [])]
    pickers2 = [e for e in all_elements2 if e.get("action_id") == config.ACTION_REQ_ASSIGN_SELECT]
    assert len(pickers2) == 1
    assert pickers2[0]["type"] == "static_select"
    assert "initial_option" not in pickers2[0]
    assert pickers2[0]["placeholder"]["text"] == "Assign a buyer"

    # No picker in processed, confirmed, delivered
    for state in ("processed", "confirmed", "delivered"):
        blks_s = blocks.build_request_blocks(state, req_with_buyer)
        all_el = [e for b in blks_s if b.get("type") == "actions" for e in b.get("elements", [])]
        assert not any(e.get("action_id") == config.ACTION_REQ_ASSIGN_SELECT for e in all_el), (
            f"Unexpected picker in state={state}"
        )


def test_another_buyer_moves_assigned_request(clean_roster, monkeypatch):
    """AC 2: Buyer B selects Buyer C on an approved card assigned to Buyer A.

    The thread card chat_update carries assignee_id=U_BUYER_C in a button value;
    chat_postMessage goes to U_BUYER_C (new DM card); history contains 'Reassigned to'.
    Buyer B selecting Buyer B (not the current assignee) also succeeds.
    """
    monkeypatch.setattr(slack_io, "find_row_in_thread", lambda *a, **kw: None)

    req_data = {
        "item_description": "Laser diode",
        "vendor": "Thorlabs",
        "total_price": 120.0,
        "assignee_id": "U_BUYER_A",
        "assignee": "Alice",
        "dm_channel": "D_BUYER_A",
        "dm_ts": "5.5",
        "row": 17,
    }
    history = ["Assigned to Alice on 01/01/26 10:00"]
    body = _make_picker_body("U_BUYER_B", "U_BUYER_C", req_data, history)

    client = MagicMock()
    client.chat_postMessage.return_value = {"channel": "D_BUYER_C", "ts": "99.1", "ok": True}
    respond = MagicMock()

    app.handle_req_assign_select_action(ack=lambda: None, body=body, respond=respond, client=client)

    # Thread card updated with assignee_id == U_BUYER_C in a button value
    thread_updates = [c[1] for c in client.chat_update.call_args_list if c[1].get("channel") == "C123"]
    assert len(thread_updates) >= 1
    found_assignee = False
    for c in client.chat_update.call_args_list:
        for blk in c[1].get("blocks", []):
            for el in blk.get("elements", []):
                if el.get("type") == "button" and el.get("value"):
                    val = json.loads(el["value"])
                    if val.get("request", {}).get("assignee_id") == "U_BUYER_C":
                        found_assignee = True
    assert found_assignee, "Updated thread card does not carry assignee_id=U_BUYER_C in any button value"

    # New DM card posted to U_BUYER_C
    dm_posts = [
        c[1] for c in client.chat_postMessage.call_args_list
        if c[1].get("channel") == "U_BUYER_C" and c[1].get("blocks")
    ]
    assert len(dm_posts) >= 1

    # History contains "Reassigned to" — stored in button values in the card blocks
    history_lines = []
    for c in client.chat_update.call_args_list:
        for blk in c[1].get("blocks", []):
            for el in blk.get("elements", []):
                if el.get("type") == "button" and el.get("value"):
                    try:
                        val = json.loads(el["value"])
                        history_lines.extend(val.get("history", []))
                    except (json.JSONDecodeError, TypeError):
                        pass
    assert any("Reassigned to" in h for h in history_lines), (
        f"No 'Reassigned to' in any button value history: {history_lines}"
    )

    # Also: buyer B selecting buyer B (not A — different buyer) also succeeds
    client.reset_mock()
    body2 = _make_picker_body("U_BUYER_B", "U_BUYER_B", dict(req_data), list(history))
    app.handle_req_assign_select_action(ack=lambda: None, body=body2, respond=respond, client=client)
    thread_updates2 = [c[1] for c in client.chat_update.call_args_list if c[1].get("channel") == "C123"]
    assert len(thread_updates2) >= 1


def test_non_buyer_refused_privately(clean_roster):
    """AC 3: Requester (not buyer/approver/admin) using picker is refused via respond (ephemeral).

    No chat_update and no chat_postMessage are made.
    """
    req_data = {
        "item_description": "Laser diode",
        "vendor": "Thorlabs",
        "total_price": 120.0,
        "assignee_id": "U_BUYER_A",
        "assignee": "Alice",
        "row": 17,
    }
    history = ["Assigned to Alice on 01/01/26 10:00"]
    body = _make_picker_body("U_REQ", "U_BUYER_B", req_data, history)

    client = MagicMock()
    respond = MagicMock()

    app.handle_req_assign_select_action(ack=lambda: None, body=body, respond=respond, client=client)

    respond.assert_called_once()
    call_text = respond.call_args[1].get("text", "")
    assert "Only buyers, approvers or admins" in call_text

    client.chat_update.assert_not_called()
    client.chat_postMessage.assert_not_called()


def test_picking_current_buyer_does_nothing(clean_roster):
    """AC 4: Selecting the current assignee is a no-op — zero chat_update, zero chat_postMessage."""
    req_data = {
        "item_description": "Laser diode",
        "vendor": "Thorlabs",
        "total_price": 120.0,
        "assignee_id": "U_BUYER_A",
        "assignee": "Alice",
        "row": 17,
    }
    history = ["Assigned to Alice on 01/01/26 10:00"]
    # Buyer A picks Buyer A (the current assignee)
    body = _make_picker_body("U_BUYER_A", "U_BUYER_A", req_data, history)

    client = MagicMock()
    respond = MagicMock()

    app.handle_req_assign_select_action(ack=lambda: None, body=body, respond=respond, client=client)

    client.chat_update.assert_not_called()
    client.chat_postMessage.assert_not_called()


def test_typed_keyword_follows_same_rule(clean_roster, monkeypatch):
    """AC 5: '@Purchasing assign @C' sent by buyer B on a thread assigned to buyer A updates
    the thread card to assignee C.

    Replaces test_buyer_reassign_already_assigned_request_denied, which asserted the old
    ADR 0004 rule that a non-assignee buyer was refused.
    """
    monkeypatch.setattr(slack_io, "find_row_in_thread", lambda *a, **kw: None)

    req_data = {
        "item_description": "Laser diode",
        "vendor": "Thorlabs",
        "total_price": 120.0,
        "assignee_id": "U_BUYER_A",
        "assignee": "Alice",
        "row": 17,
    }
    history = ["Assigned to Alice on 01/01/26 10:00"]
    thread_card_msg = _make_thread_card_message("1000.1", "approved", req_data, history)

    client = MagicMock()
    client.conversations_replies.return_value = {
        "ok": True,
        "messages": [
            {"ts": "1000.0", "text": "Parent"},
            thread_card_msg,
        ],
    }
    client.chat_postMessage.return_value = {"channel": "D_BUYER_C", "ts": "99.1", "ok": True}
    say = MagicMock()

    app.dispatch_command(
        client=client,
        say=say,
        channel="C123",
        thread_ts="1000.0",
        user="U_BUYER_B",
        event_ts="1000.3",
        text="assign <@U_BUYER_C>",
        respond=None,
        bot_user_id="U_BOT",
    )

    # Thread card updated to assignee C
    found_assignee = False
    for c in client.chat_update.call_args_list:
        for blk in c[1].get("blocks", []):
            for el in blk.get("elements", []):
                if el.get("type") == "button" and el.get("value"):
                    val = json.loads(el["value"])
                    if val.get("request", {}).get("assignee_id") == "U_BUYER_C":
                        found_assignee = True
    assert found_assignee, (
        "Keyword 'assign @U_BUYER_C' by buyer B did not update thread card to U_BUYER_C. "
        f"chat_update calls: {[c[1] for c in client.chat_update.call_args_list]}"
    )
