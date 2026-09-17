"""Tests for Ticket 17: The posted card carries a buyer picker.

Acceptance criteria:
- build_request_blocks("posted", …) renders a users_select with action_id req_assign_select
  in the same actions block as Approve, and build_request_blocks("approved", …) does not.
- A test asserts the handler recovers the request payload from the sibling Approve button's
  value in body["message"]["blocks"] — with no new state file.
- Selecting a buyer re-renders the card with the assignee line set and performs no Excel write
  — assert append_row was not called.
- Picking a non-buyer leaves the request unassigned, posts the add-buyer refusal, and a subsequent
  Approve still writes the row.
- Picking a buyer with no requesters entry gets the existing /roster-set-name refusal and leaves
  the request unassigned.
- A picked buyer and a mentioned buyer together: the mention wins, and the reply names which input was used.
- A test asserts both the picker path and the mention path call lifecycle.handle_assign — one implementation, not two.
- Picking nobody and approving writes the rows and posts the unassigned card, exactly as ticket 08 established.
- AGENTS.md §9 trap 7 says "assigned", and the trap itself is still there.
- ruff check ., python scripts/check_tests_first.py and pytest -q all pass.
"""
import json
import os
from unittest.mock import MagicMock

import pytest

from src import app, blocks, lifecycle, log_writer, queue_worker, roster


@pytest.fixture(autouse=True)
def clean_roster(tmp_path, monkeypatch):
    """Ensure a fresh isolated roster for each test."""
    roster_file = str(tmp_path / "roster.json")
    monkeypatch.setattr(roster, "ROSTER_PATH", roster_file)
    roster._DATA = None
    data = {
        "admins": ["U_ADMIN"],
        "approvers": ["U_CHARLIE"],
        "buyers": ["U_DYLAN", "U_SMEET"],
        "requesters": {
            "U_ADMIN": "Isaac",
            "U_CHARLIE": "Charlie H.",
            "U_DYLAN": "Dylan",
            "U_SMEET": "Smeet",
            "U_REQ": "Alex",
        },
        "vendors": [],
    }
    with open(roster_file, "w", encoding="utf-8") as f:
        json.dump(data, f)
    return roster_file


def _sample_request():
    return {
        "item_description": "Oscilloscope Probe",
        "total_price": 120.00,
        "vendor": "DigiKey",
        "vendor_contact_name": "Sales",
        "vendor_contact_email": "sales@digikey.com",
        "payment_method": "Workday",
        "category": "Research/Lab Supplies (3105)",
        "category_error": None,
        "project_id": "PG000025831",
        "fund": "133",
        "delivery_room": "ERB 212",
        "purpose": "Sensor testing",
        "date_of_purchase": "09/16/26",
        "requester": "Isaac",
        "user_id": "U_ADMIN",
        "thread_ts": "1000.2000",
        "name_of_system": "",
        "asset_id": "",
        "link": "",
    }


def _make_picker_body(selected_user: str, req_data: dict, user_id: str = "U_CHARLIE"):
    btn_val = json.dumps({
        "state": "posted",
        "requester": req_data.get("requester", "Isaac"),
        "thread_ts": req_data.get("thread_ts", "1000.2000"),
        "request": req_data,
        "history": [],
    })
    return {
        "user": {"id": user_id},
        "channel": {"id": "C_PURCHASING"},
        "message": {
            "ts": "1000.2000",
            "blocks": [
                {
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": "🛒 *New Purchase Request*"},
                },
                {
                    "type": "actions",
                    "elements": [
                        {
                            "type": "button",
                            "action_id": "req_approve",
                            "value": btn_val,
                        },
                        {
                            "type": "button",
                            "action_id": "req_decline",
                            "value": btn_val,
                        },
                        {
                            "type": "users_select",
                            "action_id": "req_assign_select",
                            "placeholder": {"type": "plain_text", "text": "Assign a buyer (optional)"},
                        },
                    ],
                },
            ],
        },
        "container": {"message_ts": "1000.2000", "thread_ts": "1000.2000"},
        "actions": [
            {
                "action_id": "req_assign_select",
                "selected_user": selected_user,
            }
        ],
    }


# 1. build_request_blocks renders users_select on posted and NOT on approved
def test_build_request_blocks_posted_renders_users_select_and_approved_does_not():
    """AC: build_request_blocks('posted') renders users_select with action_id req_assign_select

    in the same actions block as Approve, and build_request_blocks('approved') does not.
    """
    sample_req = _sample_request()

    posted_blks = blocks.build_request_blocks("posted", sample_req)
    action_blocks = [b for b in posted_blks if b.get("type") == "actions"]
    assert len(action_blocks) == 1, "Posted state must have exactly 1 action block"

    elems = action_blocks[0].get("elements", [])
    approve_btns = [e for e in elems if e.get("action_id") == "req_approve"]
    picker_elems = [e for e in elems if e.get("action_id") == "req_assign_select"]

    assert len(approve_btns) == 1, "Must contain req_approve button"
    assert len(picker_elems) == 1, "Must contain req_assign_select picker in same actions block"
    assert picker_elems[0].get("type") == "users_select"
    assert picker_elems[0].get("placeholder", {}).get("text") == "Assign a buyer (optional)"

    # Approved state does NOT carry the picker
    approved_blks = blocks.build_request_blocks("approved", sample_req)
    approved_action_blocks = [b for b in approved_blks if b.get("type") == "actions"]
    assert len(approved_action_blocks) == 1
    approved_elems = approved_action_blocks[0].get("elements", [])
    approved_pickers = [e for e in approved_elems if e.get("action_id") == "req_assign_select"]
    assert len(approved_pickers) == 0, "Approved state must NOT carry the buyer picker"


def test_users_select_initial_user_when_assignee_present():
    """Initial user is set on users_select and Buyer line appears in summary."""
    sample_req = {**_sample_request(), "assignee_id": "U_DYLAN", "assignee": "Dylan"}
    posted_blks = blocks.build_request_blocks("posted", sample_req)

    summary_sec = posted_blks[0]["text"]["text"]
    assert "• *Buyer:* <@U_DYLAN> (Dylan)" in summary_sec

    action_blocks = [b for b in posted_blks if b.get("type") == "actions"]
    picker = [e for e in action_blocks[0]["elements"] if e.get("action_id") == "req_assign_select"][0]
    assert picker.get("initial_user") == "U_DYLAN"


# 2. Handler recovers request payload from sibling Approve button's value (no state file)
def test_handler_recovers_payload_from_sibling_approve_button_no_state_file(monkeypatch):
    """AC: handler recovers the request payload from the sibling Approve button's value

    in body['message']['blocks'] with no new state file.
    """
    req_data = _sample_request()
    body = _make_picker_body("U_DYLAN", req_data)

    ack = MagicMock()
    respond = MagicMock()
    client = MagicMock()

    captured_assign = {}

    def mock_handle_assign(**kwargs):
        captured_assign.update(kwargs)
        return True

    monkeypatch.setattr(lifecycle, "handle_assign", mock_handle_assign)

    app.handle_req_assign_select_action(ack, body, respond, client)

    ack.assert_called_once()
    assert captured_assign.get("target_user_id") == "U_DYLAN"
    assert captured_assign.get("req_data") == req_data
    assert captured_assign.get("current_state") == "posted"

    # Assert no requests.json or other state file was touched
    assert not os.path.exists("requests.json")


# 3. Selecting a buyer re-renders card with assignee line set and performs NO Excel write
def test_selecting_buyer_rerenders_card_with_assignee_line_and_no_excel_write(monkeypatch):
    """AC: selecting a buyer re-renders the card with the assignee line set and performs

    NO Excel write — assert append_row was not called.
    """
    req_data = _sample_request()
    body = _make_picker_body("U_DYLAN", req_data)

    ack = MagicMock()
    respond = MagicMock()
    client = MagicMock()
    client.conversations_replies.return_value = {"messages": []}

    mock_append = MagicMock()
    monkeypatch.setattr(log_writer, "append_row", mock_append)

    app.handle_req_assign_select_action(ack, body, respond, client)

    ack.assert_called_once()
    mock_append.assert_not_called()
    client.chat_update.assert_called_once()

    update_kwargs = client.chat_update.call_args[1]
    assert update_kwargs["ts"] == "1000.2000"
    updated_blocks = update_kwargs["blocks"]

    # Verify Buyer line is present in summary
    summary_text = updated_blocks[0]["text"]["text"]
    assert "• *Buyer:* <@U_DYLAN> (Dylan)" in summary_text

    # Verify sibling Approve button value carries updated assignee
    action_block = [b for b in updated_blocks if b.get("type") == "actions"][0]
    approve_btn = [e for e in action_block["elements"] if e.get("action_id") == "req_approve"][0]
    val_data = json.loads(approve_btn["value"])
    assert val_data["request"]["assignee_id"] == "U_DYLAN"
    assert val_data["request"]["assignee"] == "Dylan"

    # Verify picker maintains initial_user
    picker = [e for e in action_block["elements"] if e.get("action_id") == "req_assign_select"][0]
    assert picker.get("initial_user") == "U_DYLAN"


# 4. Picking a non-buyer leaves request unassigned, posts refusal, subsequent Approve writes row
def test_picking_non_buyer_refusal_and_subsequent_approve_writes_row(monkeypatch):
    """AC: picking a non-buyer leaves request unassigned, posts the add-buyer refusal,

    and a subsequent Approve still writes the row.
    """
    req_data = _sample_request()
    body = _make_picker_body("U_NON_BUYER", req_data)

    ack = MagicMock()
    respond = MagicMock()
    client = MagicMock()
    client.conversations_replies.return_value = {"messages": []}

    app.handle_req_assign_select_action(ack, body, respond, client)

    # Refusal posted to thread
    thread_msgs = [c[1]["text"] for c in client.chat_postMessage.call_args_list]
    assert any("isn't on the buyers list" in msg and "@Purchasing add-buyer <@U_NON_BUYER>" in msg for msg in thread_msgs)
    client.chat_update.assert_not_called()

    # Subsequent click of Approve button
    approve_body = {
        "user": {"id": "U_CHARLIE"},
        "channel": {"id": "C_PURCHASING"},
        "message": {"ts": "1000.2000"},
        "container": {"thread_ts": "1000.2000"},
        "actions": [
            {
                "action_id": "req_approve",
                "value": json.dumps({
                    "state": "posted",
                    "requester": "Isaac",
                    "thread_ts": "1000.2000",
                    "request": req_data,  # Still unassigned!
                    "history": [],
                }),
            }
        ],
    }

    def sync_submit(action_fn, *args, success_callback=None, **kwargs):
        res = action_fn()
        if success_callback:
            success_callback(res)

    monkeypatch.setattr(queue_worker, "submit_write_task", sync_submit)
    mock_append = MagicMock(return_value=15)
    monkeypatch.setattr(log_writer, "append_row", mock_append)
    monkeypatch.setattr(log_writer, "save_epif", lambda *a, **k: None)

    app.handle_req_approve_action(ack, approve_body, respond, client)

    # Assert row was written and card was updated to unassigned approved state
    mock_append.assert_called_once()
    client.chat_update.assert_called_once()
    approved_blocks = client.chat_update.call_args[1]["blocks"]
    assert "• *Buyer:* ⚠️ _Unassigned_" in approved_blocks[0]["text"]["text"]


# 5. Picking a buyer with no requesters entry gets /roster-set-name refusal and leaves unassigned
def test_picking_buyer_no_requesters_entry_refusal():
    """AC: picking a buyer with no requesters entry gets existing /roster-set-name refusal

    and leaves the request unassigned.
    """
    # U_GHOST is a buyer but not in requesters
    with open(roster.ROSTER_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    data["buyers"].append("U_GHOST")
    with open(roster.ROSTER_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f)
    roster._DATA = None

    req_data = _sample_request()
    body = _make_picker_body("U_GHOST", req_data)

    ack = MagicMock()
    respond = MagicMock()
    client = MagicMock()
    client.conversations_replies.return_value = {"messages": []}

    app.handle_req_assign_select_action(ack, body, respond, client)

    thread_msgs = [c[1]["text"] for c in client.chat_postMessage.call_args_list]
    assert any("must be registered in the lab roster" in msg and "/roster-set-name" in msg for msg in thread_msgs)
    client.chat_update.assert_not_called()
    assert req_data.get("assignee_id") is None


# 6. Picked buyer and mentioned buyer together: mention wins and reply names input used
def test_picked_buyer_and_mentioned_buyer_mention_wins_and_reply_names_input(monkeypatch):
    """AC: a picked buyer and a mentioned buyer together: the mention wins,

    and the reply names which input was used.
    """
    client = MagicMock()
    say = MagicMock()

    # Card in thread has picked buyer U_SMEET
    card_req = {
        **_sample_request(),
        "assignee_id": "U_SMEET",
        "assignee": "Smeet",
    }
    client.conversations_replies.return_value = {
        "messages": [
            {
                "ts": "1000.2000",
                "metadata": {
                    "event_type": "purchase_request",
                    "event_payload": card_req,
                },
                "blocks": [
                    {
                        "type": "actions",
                        "elements": [
                            {
                                "action_id": "req_approve",
                                "value": json.dumps({
                                    "state": "posted",
                                    "request": card_req,
                                    "history": [],
                                }),
                            }
                        ],
                    }
                ],
            }
        ]
    }

    captured_epif = {}

    def mock_epif_processing(*args, **kwargs):
        captured_epif.update(kwargs)

    monkeypatch.setattr(lifecycle, "handle_epif_processing", mock_epif_processing)

    # Charlie mentions U_DYLAN in approval command
    app.dispatch_command(
        client=client,
        say=say,
        channel="C_PURCHASING",
        thread_ts="1000.2000",
        user="U_CHARLIE",
        event_ts="1000.2001",
        text="<@U_BOT> approved <@U_DYLAN>",
        bot_user_id="U_BOT",
    )

    # Mention U_DYLAN won over picked U_SMEET!
    assert captured_epif.get("assignee_id") == "U_DYLAN"
    assert captured_epif.get("assignee_name") == "Dylan"
    assert captured_epif.get("input_note") is not None
    assert "mention" in captured_epif["input_note"].lower()


# 7. Both picker path and mention path call lifecycle.handle_assign
def test_both_picker_and_mention_paths_call_handle_assign(monkeypatch):
    """AC: both the picker path and the mention path call lifecycle.handle_assign — one implementation, not two."""
    picker_assign_called = []
    mention_assign_called = []

    def mock_handle_assign(**kwargs):
        if kwargs.get("current_state") == "posted":
            picker_assign_called.append(kwargs)
        else:
            mention_assign_called.append(kwargs)
        return True

    monkeypatch.setattr(lifecycle, "handle_assign", mock_handle_assign)

    # 1. Picker path
    ack = MagicMock()
    respond = MagicMock()
    client = MagicMock()
    body = _make_picker_body("U_DYLAN", _sample_request())
    app.handle_req_assign_select_action(ack, body, respond, client)
    assert len(picker_assign_called) == 1

    # 2. Mention path (@Purchasing assign <@U_DYLAN>)
    say = MagicMock()
    app.dispatch_command(
        client=client,
        say=say,
        channel="C_PURCHASING",
        thread_ts="1000.2000",
        user="U_CHARLIE",
        event_ts="1000.2001",
        text="<@U_BOT> assign <@U_DYLAN>",
        bot_user_id="U_BOT",
    )
    assert len(mention_assign_called) == 1
    assert mention_assign_called[0]["target_user_id"] == "U_DYLAN"


# 8. Picking nobody and approving writes rows and posts unassigned card
def test_picking_nobody_and_approving_writes_unassigned_card(monkeypatch):
    """AC: picking nobody and approving writes rows and posts unassigned card, exactly as ticket 08 established."""
    req_data = _sample_request()
    assert "assignee_id" not in req_data

    ack = MagicMock()
    respond = MagicMock()
    client = MagicMock()

    body = {
        "user": {"id": "U_CHARLIE"},
        "channel": {"id": "C_PURCHASING"},
        "message": {"ts": "1000.2000"},
        "container": {"thread_ts": "1000.2000"},
        "actions": [
            {
                "action_id": "req_approve",
                "value": json.dumps({
                    "state": "posted",
                    "requester": "Isaac",
                    "thread_ts": "1000.2000",
                    "request": req_data,
                    "history": [],
                }),
            }
        ],
    }

    def sync_submit(action_fn, *args, success_callback=None, **kwargs):
        res = action_fn()
        if success_callback:
            success_callback(res)

    monkeypatch.setattr(queue_worker, "submit_write_task", sync_submit)
    mock_append = MagicMock(return_value=15)
    monkeypatch.setattr(log_writer, "append_row", mock_append)
    monkeypatch.setattr(log_writer, "save_epif", lambda *a, **k: None)

    app.handle_req_approve_action(ack, body, respond, client)

    mock_append.assert_called_once()
    client.chat_update.assert_called_once()
    approved_blocks = client.chat_update.call_args[1]["blocks"]
    assert "• *Buyer:* ⚠️ _Unassigned_" in approved_blocks[0]["text"]["text"]


# 9. AGENTS.md §9 trap 7 says "assigned", and the trap itself is still there
def test_agents_md_trap_7_says_assigned():
    """AC: AGENTS.md §9 trap 7 says 'assigned', and the trap itself is still there."""
    agents_md_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "AGENTS.md")
    with open(agents_md_path, "r", encoding="utf-8") as f:
        content = f.read()

    assert "Claimed by Dylan" not in content
    assert "Assigned to Dylan" in content
    assert "A buyer needs two roster entries" in content
