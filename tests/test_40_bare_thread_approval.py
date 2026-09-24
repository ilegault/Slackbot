import json
from unittest.mock import MagicMock

from src import admin, app, bom, lifecycle, log_writer, slack_io, validators


def _make_button_body(action_id, user_id="U123", state="posted", req=None):
    if req is None:
        req = {"item_description": "Test item"}
    val_data = {
        "state": state,
        "request": req,
        "history": [],
    }
    return {
        "user": {"id": user_id},
        "channel": {"id": "C_PURCHASING"},
        "message": {"ts": "1000.2000"},
        "container": {"message_ts": "1000.2000", "thread_ts": "1000.2000"},
        "actions": [
            {
                "action_id": action_id,
                "value": json.dumps(val_data)
            }
        ],
        "view": {"private_metadata": json.dumps({"channel_id": "C_PURCHASING", "thread_ts": "1000.2000", "card_ts": "1000.2000", "assignee_id": "U_ASSIGNEE"})}
    }


def test_bare_thread_approval_posts_reply_and_card(monkeypatch):
    """Approval on a thread with no PDF or card creates a waiting_for_details card and writes no row."""
    client = MagicMock()
    say = MagicMock()

    # Mock finding nothing in the thread
    monkeypatch.setattr(slack_io, "find_epif_in_thread", MagicMock(return_value=(None, None)))
    monkeypatch.setattr(slack_io, "find_card_in_thread", MagicMock(return_value=(None, None, [], None)))
    monkeypatch.setattr(slack_io, "find_request_metadata_in_thread", MagicMock(return_value=(None, None, None, False)))

    # Mock getting thread parent author
    monkeypatch.setattr(slack_io, "get_thread_parent_author", MagicMock(return_value="U_REQUESTER"))
    monkeypatch.setattr(slack_io, "resolve_requester", MagicMock(return_value="Katarina"))

    lifecycle.handle_epif_processing(
        client=client,
        say=say,
        channel="C123",
        thread_ts="T123",
        approver="Charlie",
        event_ts="E123",
    )

    # Assert exactly one thread reply with specific wording
    say.assert_called_once()
    reply_text = say.call_args[1]["text"]
    assert "✅ Approved by Charlie. No EPIF in this thread" in reply_text
    assert "treating this as a *Workday order*" in reply_text
    assert "<@U_REQUESTER>" in reply_text
    assert "fill in the details" in reply_text

    # Assert one card posted
    client.chat_postMessage.assert_called_once()
    card_kwargs = client.chat_postMessage.call_args[1]
    assert card_kwargs["channel"] == "C123"
    assert card_kwargs["thread_ts"] == "T123"
    assert "Approved — waiting for details" in card_kwargs["text"]

    # Assert waiting_for_details state is saved in the block
    blocks_str = json.dumps(card_kwargs["blocks"])
    assert "waiting_for_details" in blocks_str
    assert "req_fill_details" in blocks_str
    assert "req_needs_epif" in blocks_str
    assert "req_cancel" in blocks_str

def test_fill_in_details_writes_row_and_updates_card(monkeypatch):
    """Submitting the Workday details modal writes the row, updates card to approved, and DMs assignee."""
    client = MagicMock()
    ack = MagicMock()

    # Mock validation pass
    monkeypatch.setattr(validators, "validate", MagicMock(return_value=[]))

    # Mock parsing pasted items to empty
    monkeypatch.setattr(bom, "parse_line_items", MagicMock(return_value=([], 0.0, None)))
    monkeypatch.setattr(bom, "check_total", MagicMock(return_value=None))

    # Mock finalize_purchase_request to just assert it's called
    monkeypatch.setattr(lifecycle, "finalize_purchase_request", MagicMock())

    # Mock card payload fetch to return waiting_for_details
    card_payload = {
        "state": "waiting_for_details",
        "assignee_id": "U_ASSIGNEE",
        "assignee": "Assignee",
        "approver": "Charlie",
        "requester": "Katarina"
    }
    monkeypatch.setattr(slack_io, "get_card_payload", MagicMock(return_value=card_payload))
    monkeypatch.setattr(slack_io, "resolve_requester", MagicMock(return_value="Katarina"))

    body = {"user": {"id": "U_REQUESTER"}}
    view = {
        "private_metadata": json.dumps({
            "channel_id": "C123",
            "thread_ts": "T123",
            "card_ts": "C_TS"
        }),
        "state": {
            "values": {
                "block_vendor": {"vendor": {"selected_option": {"value": "Grainger"}}},
                "block_item_description": {"item_description": {"value": "Widget"}},
                "block_total_price": {"total_price": {"value": "10.00"}},
                "block_date_of_purchase": {"date_of_purchase": {"selected_date": "2026-09-24"}},
                "block_category": {"category": {"selected_option": {"value": "Lab Consumable"}}}
            }
        }
    }

    app.handle_workday_details_submit(ack, body, client, view)

    ack.assert_called_once_with()

    lifecycle.finalize_purchase_request.assert_called_once()
    kwargs = lifecycle.finalize_purchase_request.call_args[1]
    assert kwargs["parsed"]["route"] == "workday"
    assert kwargs["parsed"]["vendor"] == "Grainger"
    assert kwargs["parsed"]["item_description"] == "Widget"
    assert kwargs["requester"] == "Katarina"
    assert kwargs["assignee_id"] == "U_ASSIGNEE"
    assert kwargs["approver"] == "Charlie"

def test_cancel_on_waiting_for_details(monkeypatch):
    """Cancel on waiting_for_details card turns it terminal with no workbook write."""
    client = MagicMock()
    ack = MagicMock()
    respond = MagicMock()

    # Mock admin/approver check
    monkeypatch.setattr(admin, "is_approved_reviewer", MagicMock(return_value=True))

    monkeypatch.setattr(log_writer, "blank_row", MagicMock())

    body = _make_button_body("req_cancel", state="waiting_for_details", req={"requester": "Katarina"})

    app.handle_req_cancel_action(ack, body, respond, client)

    ack.assert_called_once()

    # Assert card is updated to terminal state with no buttons
    client.chat_update.assert_called_once()
    kwargs = client.chat_update.call_args[1]
    blocks_str = json.dumps(kwargs["blocks"])
    assert "Cancelled by <@U123>" in blocks_str
    assert "actions" not in blocks_str  # No buttons

    # Assert thread reply
    client.chat_postMessage.assert_called_once()
    assert "🚫 Purchase request cancelled" in client.chat_postMessage.call_args[1]["text"]

    # Assert no write to workbook
    log_writer.blank_row.assert_not_called()

def test_this_needs_an_epif_replies_privately_and_writes_nothing(monkeypatch):
    """Clicking 'This needs an EPIF' responds with a private message (stub for ticket 41)."""
    client = MagicMock()
    ack = MagicMock()
    respond = MagicMock()

    # Mock admin/approver check
    monkeypatch.setattr(admin, "is_admin_user", MagicMock(return_value=True))

    body = _make_button_body("req_needs_epif", state="waiting_for_details", req={"requester": "Katarina"})

    # Needs a trigger id
    body["trigger_id"] = "TRIG123"

    app.handle_req_needs_epif(ack, body, respond, client)

    ack.assert_called_once()
    client.chat_postMessage.assert_called_once()
    assert "ticket 41" in client.chat_postMessage.call_args[1]["text"]
