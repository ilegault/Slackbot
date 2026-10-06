"""Tests for Ticket 74: The DM card carries the buyer picker too.

Covers:
- The DM card has the picker only while approved.
- A pick in the DM moves the request.
- Permission and refusal match the thread card.
- A missing thread card refuses privately and alerts.
"""
import json
from unittest.mock import MagicMock

import pytest

from src import app, blocks, config, queue_worker, roster


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
        "row": req_data.get("row", 15),
        "request": req_data,
        "history": history or [],
    })
    return {
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
                        "text": {"type": "plain_text", "text": "Mark Processed"},
                        "action_id": "req_processed",
                        "value": btn_val,
                    }
                ],
            },
        ],
    }


def _make_dm_picker_body(
    selected_user: str,
    user_id: str,
    thread_channel: str = "C123",
    thread_ts: str = "1000.0",
    card_ts: str = "1000.1",
):
    action_id = getattr(config, "ACTION_DM_REQ_ASSIGN_SELECT", "dm_req_assign_select")
    pointer = {
        "thread_channel": thread_channel,
        "thread_ts": thread_ts,
        "card_ts": card_ts,
    }
    block_id_val = json.dumps(pointer)
    return {
        "user": {"id": user_id},
        "channel": {"id": "D_BUYER"},
        "message": {
            "ts": "2000.1",
            "blocks": [
                {
                    "type": "actions",
                    "block_id": block_id_val,
                    "elements": [
                        {
                            "type": "users_select",
                            "action_id": action_id,
                        }
                    ],
                }
            ],
        },
        "container": {"message_ts": "2000.1"},
        "actions": [
            {
                "action_id": action_id,
                "block_id": block_id_val,
                "selected_user": selected_user,
            }
        ],
    }


# ---------------------------------------------------------------------------
# Criterion 1: The DM card has the picker only while approved
# ---------------------------------------------------------------------------

def test_dm_card_has_picker_only_while_approved(clean_roster):
    """build_dm_card_blocks("approved", …) has a static_select with
    action_id == "dm_req_assign_select" and initial_option equal to the assignee,
    and its actions block's block_id parses as JSON with thread_ts and card_ts;
    for processed there is none.
    """
    req_assigned = {
        "item_description": "Widget",
        "vendor": "Acme",
        "total_price": 50.0,
        "assignee_id": "U_BUYER",
    }
    blks_appr = blocks.build_dm_card_blocks(
        state="approved",
        request=req_assigned,
        thread_channel="C123",
        thread_ts="1000.0",
        card_ts="1000.1",
    )
    # Check actions block
    actions_blocks = [b for b in blks_appr if b.get("type") == "actions"]
    assert len(actions_blocks) == 1, "Approved DM card must have an actions block"
    actions_blk = actions_blocks[0]

    # block_id parses as JSON containing thread_ts and card_ts
    assert "block_id" in actions_blk, "actions block must carry block_id with pointer JSON"
    block_id_data = json.loads(actions_blk["block_id"])
    assert block_id_data.get("thread_channel") == "C123"
    assert block_id_data.get("thread_ts") == "1000.0"
    assert block_id_data.get("card_ts") == "1000.1"

    # Must contain picker element
    expected_action_id = getattr(config, "ACTION_DM_REQ_ASSIGN_SELECT", "dm_req_assign_select")
    selects = [e for e in actions_blk.get("elements", []) if e.get("action_id") == expected_action_id]
    assert len(selects) == 1, "Approved DM card actions block must contain buyer picker"
    picker = selects[0]
    assert picker.get("type") == "static_select"
    assert picker.get("initial_option", {}).get("value") == "U_BUYER"
    assert picker.get("placeholder", {}).get("text") == "Assign a buyer"

    # For unassigned request, no initial_option
    req_unassigned = {
        "item_description": "Widget",
        "vendor": "Acme",
        "total_price": 50.0,
    }
    blks_unassigned = blocks.build_dm_card_blocks(
        state="approved",
        request=req_unassigned,
        thread_channel="C123",
        thread_ts="1000.0",
        card_ts="1000.1",
    )
    unassigned_actions = [b for b in blks_unassigned if b.get("type") == "actions"][0]
    unassigned_picker = [e for e in unassigned_actions.get("elements", []) if e.get("action_id") == expected_action_id][0]
    assert unassigned_picker.get("type") == "static_select"
    assert "initial_option" not in unassigned_picker
    assert unassigned_picker.get("placeholder", {}).get("text") == "Assign a buyer"

    # For processed: no buyer picker
    blks_proc = blocks.build_dm_card_blocks(
        state="processed",
        request=req_assigned,
        thread_channel="C123",
        thread_ts="1000.0",
        card_ts="1000.1",
    )
    for b in blks_proc:
        for el in b.get("elements", []):
            assert el.get("action_id") != expected_action_id, "processed state must not have a buyer picker"


# ---------------------------------------------------------------------------
# Criterion 2: A pick in the DM moves the request
# ---------------------------------------------------------------------------

def test_pick_in_dm_moves_request(clean_roster, sync_queue, monkeypatch):
    """The assignee (buyer A) selects buyer B on the DM card:
    - the thread card (channel = thread channel, ts = card_ts) is chat_updated with "assignee_id": "U_B"
    - buyer A's DM card is retired (no actions block, contains Reassigned to)
    - a new DM card is posted to U_B.
    """
    req_data = {
        "item_description": "Widget",
        "vendor": "Acme",
        "total_price": 50.0,
        "row": 15,
        "assignee_id": "U_BUYER",
        "assignee": "Dylan",
        "user_id": "U_REQ",
        "requester": "Alex",
        "dm_channel": "D_BUYER",
        "dm_ts": "2000.1",
        "parsed": {
            "item_description": "Widget",
            "vendor": "Acme",
            "total_price": 50.0,
            "category": "Supplies",
        },
    }
    thread_msg = _make_thread_card_message(ts="1000.1", state="approved", req_data=req_data)

    client = MagicMock()
    client.conversations_replies.return_value = {"messages": [thread_msg]}
    # Fake client.chat_postMessage to return ts
    client.chat_postMessage.return_value = {"ok": True, "ts": "3000.1", "channel": "D_OTHER_BUYER"}

    body = _make_dm_picker_body(
        selected_user="U_OTHER_BUYER",
        user_id="U_BUYER",
        thread_channel="C123",
        thread_ts="1000.0",
        card_ts="1000.1",
    )
    ack = MagicMock()
    respond = MagicMock()

    handler = getattr(app, "handle_dm_assign_select_action", None)
    assert handler is not None, "app must define handle_dm_assign_select_action"

    handler(ack=ack, body=body, respond=respond, client=client)

    ack.assert_called_once()
    assert respond.call_count == 0, "Authorized buyer should not be refused"

    # Thread card chat_update
    thread_updates = [
        c for c in client.chat_update.call_args_list
        if c.kwargs.get("channel") == "C123" and c.kwargs.get("ts") == "1000.1"
    ]
    assert len(thread_updates) >= 1, "Thread card must be updated with chat_update"
    last_thread_update = thread_updates[-1].kwargs
    update_meta = last_thread_update.get("metadata", {}).get("event_payload", {})
    # Button value or metadata carries assignee_id == "U_OTHER_BUYER"
    button_assignee = None
    for b in last_thread_update.get("blocks", []):
        for e in b.get("elements", []):
            if e.get("type") == "button":
                val = json.loads(e.get("value") or "{}")
                if "request" in val:
                    button_assignee = val["request"].get("assignee_id")
    assert button_assignee == "U_OTHER_BUYER" or update_meta.get("assignee_id") == "U_OTHER_BUYER"

    # Buyer A's DM card retired
    dm_retire_updates = [
        c for c in client.chat_update.call_args_list
        if c.kwargs.get("channel") == "D_BUYER" and c.kwargs.get("ts") == "2000.1"
    ]
    assert len(dm_retire_updates) == 1, "Buyer A's DM card must be retired with chat_update"
    retired_blocks = dm_retire_updates[0].kwargs.get("blocks", [])
    assert not any(b.get("type") == "actions" for b in retired_blocks), "Retired DM card must have no actions block"
    sec_text = "\n".join(b.get("text", {}).get("text", "") for b in retired_blocks if b.get("type") == "section")
    assert "Reassigned to" in sec_text

    # A new DM card is posted to U_OTHER_BUYER
    dm_posts_to_new_buyer = [
        c for c in client.chat_postMessage.call_args_list
        if c.kwargs.get("channel") == "U_OTHER_BUYER"
    ]
    assert len(dm_posts_to_new_buyer) >= 1, "New DM card must be posted to U_OTHER_BUYER"


# ---------------------------------------------------------------------------
# Criterion 3: Permission and refusal match the thread card
# ---------------------------------------------------------------------------

def test_dm_card_picker_permission_and_refusal_match_thread_card(clean_roster, monkeypatch):
    """A requester who is not a buyer, approver or admin:
    respond is called with 'Only buyers, approvers or admins', no chat_update.
    """
    req_data = {
        "item_description": "Widget",
        "vendor": "Acme",
        "total_price": 50.0,
        "row": 15,
        "assignee_id": "U_BUYER",
        "assignee": "Dylan",
        "user_id": "U_REQ",
        "requester": "Alex",
    }
    thread_msg = _make_thread_card_message(ts="1000.1", state="approved", req_data=req_data)

    client = MagicMock()
    client.conversations_replies.return_value = {"messages": [thread_msg]}

    body = _make_dm_picker_body(
        selected_user="U_OTHER_BUYER",
        user_id="U_REQ",  # Alex: requester only, not buyer/approver/admin
        thread_channel="C123",
        thread_ts="1000.0",
        card_ts="1000.1",
    )
    ack = MagicMock()
    respond = MagicMock()

    handler = getattr(app, "handle_dm_assign_select_action", None)
    assert handler is not None, "app must define handle_dm_assign_select_action"

    handler(ack=ack, body=body, respond=respond, client=client)

    ack.assert_called_once()
    assert client.chat_update.call_count == 0, "No chat_update allowed on permission refusal"
    assert respond.call_count == 1, "Refusal must be sent via respond"
    refusal_text = respond.call_args[1].get("text", "")
    assert "Only buyers, approvers or admins" in refusal_text


# ---------------------------------------------------------------------------
# Criterion 4: A missing thread card refuses privately and alerts
# ---------------------------------------------------------------------------

def test_missing_thread_card_refuses_privately_and_alerts(clean_roster, monkeypatch):
    """conversations_replies returns no card:
    respond contains 'can't find the request card',
    one message goes to the admin alert channel,
    no chat_update.
    """
    monkeypatch.setattr(config, "ADMIN_ALERT_CHANNEL", "C_ALERTS")

    client = MagicMock()
    client.conversations_replies.return_value = {"messages": []}

    body = _make_dm_picker_body(
        selected_user="U_OTHER_BUYER",
        user_id="U_BUYER",
        thread_channel="C123",
        thread_ts="1000.0",
        card_ts="1000.1",
    )
    ack = MagicMock()
    respond = MagicMock()

    handler = getattr(app, "handle_dm_assign_select_action", None)
    assert handler is not None, "app must define handle_dm_assign_select_action"

    handler(ack=ack, body=body, respond=respond, client=client)

    ack.assert_called_once()
    assert client.chat_update.call_count == 0, "No chat_update when card is missing"
    assert respond.call_count == 1, "User must receive private refusal"
    refusal_text = respond.call_args[1].get("text", "")
    assert "can't find the request card" in refusal_text

    alert_calls = [
        c for c in client.chat_postMessage.call_args_list
        if c.kwargs.get("channel") == "C_ALERTS"
    ]
    assert len(alert_calls) == 1, "Admin alert channel must receive alert"
    assert "find the card for a DM click" in alert_calls[0].kwargs.get("text", "")


# ---------------------------------------------------------------------------
# Criterion 5: Handler is registered on Bolt app
# ---------------------------------------------------------------------------

def test_dm_assign_select_action_registered():
    """Verify that handle_dm_assign_select_action is registered for ACTION_DM_REQ_ASSIGN_SELECT."""
    assert hasattr(app, "handle_dm_assign_select_action"), "app must define handle_dm_assign_select_action"
    count = sum(
        1 for listener in app.app._listeners
        if getattr(listener, "ack_function", None) is app.handle_dm_assign_select_action
    )
    assert count >= 1, "handle_dm_assign_select_action must be registered on Bolt app"
