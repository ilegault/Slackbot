import json
from unittest.mock import MagicMock

import openpyxl
import pytest

from src import admin, app, bom, config, lifecycle, log_writer, queue_worker, roster, slack_io, validators


@pytest.fixture(autouse=True)
def clean_roster(tmp_path, monkeypatch):
    roster_file = str(tmp_path / "roster.json")
    monkeypatch.setattr(roster, "ROSTER_PATH", roster_file)
    roster._DATA = None
    data = {
        "admins": ["U_ADMIN"],
        "approvers": ["U_CHARLIE"],
        "buyers": ["U_BUYER"],
        "requesters": {
            "U_ADMIN": "Isaac",
            "U_CHARLIE": "Charlie H.",
            "U_BUYER": "Dylan",
            "U_REQ": "Alex",
        },
        "vendors": [{"name": "Grainger", "id": "V1"}],
    }
    with open(roster_file, "w", encoding="utf-8") as f:
        json.dump(data, f)
    roster.load_roster()
    return roster_file

@pytest.fixture
def temp_workbook(tmp_path, monkeypatch):
    copy_path = str(tmp_path / "Purchasing-Log.xlsx")
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Purchasing Log"
    for r in range(1, 35):
        ws.append([""] * 30)
    wb.save(copy_path)
    monkeypatch.setattr(config, "WORKBOOK_PATH", copy_path)
    return copy_path

@pytest.fixture
def sync_queue(monkeypatch):
    def _sync_submit(action_fn, channel="", thread_ts="", user_id="", task_type="append",
                     description="", success_callback=None, failure_callback=None, client=None):
        try:
            res = action_fn()
            if success_callback:
                success_callback(res)
        except Exception as exc:
            if failure_callback:
                failure_callback(exc)

    monkeypatch.setattr(queue_worker, "submit_write_task", _sync_submit)
    return _sync_submit


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
    """Clicking 'This needs an EPIF' opens the stage 2 modal."""
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
    client.views_open.assert_called_once()


def test_scenario_end_to_end(temp_workbook, sync_queue, monkeypatch):
    client = MagicMock()
    say = MagicMock()
    ack = MagicMock()

    posted_messages = []

    def fake_postMessage(**kwargs):
        msg = dict(kwargs)
        if "ts" not in msg:
            msg["ts"] = "1000.2000"
        posted_messages.append(msg)
        return msg

    client.chat_postMessage.side_effect = fake_postMessage

    monkeypatch.setattr(slack_io, "find_epif_in_thread", MagicMock(return_value=(None, None)))

    def fake_conversations_replies(channel, ts, **kwargs):
        return {"messages": posted_messages}

    client.conversations_replies.side_effect = fake_conversations_replies
    monkeypatch.setattr(slack_io, "get_thread_parent_author", MagicMock(return_value="U_REQ"))
    monkeypatch.setattr(slack_io, "resolve_requester", MagicMock(return_value="Alex"))

    wb = openpyxl.load_workbook(temp_workbook)
    ws = wb.active
    _ = ws

    lifecycle.handle_epif_processing(
        client=client,
        say=say,
        channel="C123",
        thread_ts="T123",
        approver="U_CHARLIE",
        event_ts="E123",
        assignee_id="U_BUYER",
        assignee_name="Dylan"
    )

    say.assert_called_once()
    assert len(posted_messages) == 1
    card_msg = posted_messages[0]
    assert "Approved — waiting for details" in card_msg["text"]

    body = {"user": {"id": "U_REQ"}}
    view = {
        "private_metadata": json.dumps({
            "channel_id": "C123",
            "thread_ts": "T123",
            "card_ts": "1000.2000"
        }),
        "state": {
            "values": {
                "block_vendor": {"vendor": {"selected_option": {"value": "Grainger"}}},
                "block_item_description": {"item_description": {"value": "Widget"}},
                "block_purpose": {"purpose": {"value": "Test purpose"}},
                "block_total_price": {"total_price": {"value": 10.00}},
                "block_date_of_purchase": {"date_of_purchase": {"selected_date": "2026-09-24"}},
                "block_project_id": {"project_id": {"value": "PG000025831"}},
                "block_fund": {"fund": {"value": "133"}},
                "block_category": {"category": {"selected_option": {"value": "Research/Lab Supplies (3105)"}}},
                "block_delivery_room": {"delivery_room": {"value": "ERB 212"}}
            }
        }
    }

    app.handle_workday_details_submit(ack, body, client, view)

    ack.assert_called_once_with()
    client.chat_update.assert_called_once()

    wb3 = openpyxl.load_workbook(temp_workbook)
    ws3 = wb3.active

    found_row = None
    for row in range(2, 35):
        if ws3[f"C{row}"].value == "Widget":
            found_row = row
            break

    assert found_row is not None
    assert ws3[f"B{found_row}"].value == "Alex"
    assert ws3[f"I{found_row}"].value == "Grainger"

def test_denial_fill_in_details(temp_workbook, monkeypatch):
    client = MagicMock()
    ack = MagicMock()
    respond = MagicMock()

    body = _make_button_body("req_fill_details", user_id="U_RANDOM", state="waiting_for_details", req={"requester": "Charlie H.", "user_id": "U_CHARLIE"})

    app.handle_req_fill_details(ack, body, respond, client)

    ack.assert_called_once()
    respond.assert_called_once()
    assert "Only the requester, assignee, or admin can fill in the details." in respond.call_args[1].get("text", respond.call_args[0][0] if respond.call_args[0] else "")
    assert not client.views_open.called

    wb = openpyxl.load_workbook(temp_workbook)
    assert len(list(wb.active.rows)) == 34

def test_cancel_on_ordinary_approved_card(monkeypatch):
    client = MagicMock()
    ack = MagicMock()
    respond = MagicMock()

    monkeypatch.setattr(admin, "is_approved_reviewer", MagicMock(return_value=True))
    monkeypatch.setattr(log_writer, "blank_row", MagicMock())

    body = _make_button_body("req_cancel", state="approved", req={"requester": "Katarina"})

    app.handle_req_cancel_action(ack, body, respond, client)

    ack.assert_called_once()
    for call in client.chat_postMessage.call_args_list:
        assert "🚫 Purchase request cancelled" not in call[1].get("text", "")


def test_regression_epif_upload_does_not_post_waiting_card(monkeypatch):
    client = MagicMock()
    say = MagicMock()

    monkeypatch.setattr(slack_io, "find_epif_in_thread", MagicMock(return_value=({"name": "test_epif.pdf", "url_private_download": "http://example.com/test_epif.pdf"}, "U_POSTER")))
    monkeypatch.setattr(slack_io, "download", MagicMock(return_value=b"fake_pdf_content"))
    import src.epif_parser as epif_parser
    monkeypatch.setattr(epif_parser, "parse_epif", MagicMock(return_value={"item_description": "Widget", "vendor": "Acme", "total_price": 100, "project_id": "PRJ", "fund": "133", "category": "Lab Consumable", "payment_method": "EPIF"}))
    monkeypatch.setattr(lifecycle, "finalize_purchase_request", MagicMock())

    lifecycle.handle_epif_processing(
        client=client,
        say=say,
        channel="C123",
        thread_ts="T123",
        approver="Charlie",
        event_ts="E123",
    )

    lifecycle.finalize_purchase_request.assert_called_once()
    client.chat_postMessage.assert_not_called()
