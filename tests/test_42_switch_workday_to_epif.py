import json
import os
from unittest.mock import MagicMock
import pytest

from src import app, blocks, config, log_writer
from tests.test_29_approval_archives_bom import temp_workbook, sync_queue  # reuse fixtures


@pytest.fixture
def mock_client():
    return MagicMock()


@pytest.fixture
def base_request():
    return {
        "row": 15,
        "requester": "Test User",
        "user_id": "U111",
        "route": "workday",
        "source": "modal",
        "parsed": {
            "vendor": "Test Vendor",
            "payment_method": "Workday",
            "item_description": "Test Item",
            "total_price": 50.0,
            "category": "Test",
            "purpose": "Test",
        }
    }


def test_build_request_blocks_shows_switch_button(base_request):
    # Success condition
    blks = blocks.build_request_blocks("approved", base_request)

    switch_found = False
    for block in blks:
        if block.get("type") == "actions":
            for element in block.get("elements", []):
                if element.get("action_id") == "req_switch_epif":
                    switch_found = True
                    break
    assert switch_found, "Button should be present for approved workday requests with no date_processed"

    # Fails condition 1: Not approved
    blks = blocks.build_request_blocks("posted", base_request)
    switch_found = any(elem.get("action_id") == "req_switch_epif" for block in blks if block.get("type") == "actions" for elem in block.get("elements", []))
    assert not switch_found, "Button must be absent if state is not approved"

    # Fails condition 2: route is not workday
    epif_req = dict(base_request)
    epif_req["route"] = "epif"
    blks = blocks.build_request_blocks("approved", epif_req)
    switch_found = any(elem.get("action_id") == "req_switch_epif" for block in blks if block.get("type") == "actions" for elem in block.get("elements", []))
    assert not switch_found, "Button must be absent if route is epif"

    # Fails condition 3: date_processed is present
    proc_req = dict(base_request)
    proc_req["date_processed"] = "2026-09-22"
    blks = blocks.build_request_blocks("approved", proc_req)
    switch_found = any(elem.get("action_id") == "req_switch_epif" for block in blks if block.get("type") == "actions" for elem in block.get("elements", []))
    assert not switch_found, "Button must be absent if date_processed is set"


def test_permission_switch_to_epif(mock_client, base_request, monkeypatch):
    monkeypatch.setattr("src.admin.is_admin_user", lambda uid: uid == "U_ADMIN")
    monkeypatch.setattr("src.roster.is_buyer", lambda uid: uid == "U_BUYER")
    monkeypatch.setattr("src.slack_io.resolve_requester", lambda c, u: "Test User" if u == "U111" else None)

    respond = MagicMock()

    def simulate_click(user_id, assignee_id=None):
        req = dict(base_request)
        if assignee_id:
            req["assignee_id"] = assignee_id

        body = {
            "user": {"id": user_id},
            "channel": {"id": "C1"},
            "message": {"ts": "123.45"},
            "trigger_id": "trig_1",
            "actions": [{"value": json.dumps({"request": req, "requester": "Test User"})}]
        }
        mock_client.reset_mock()
        respond.reset_mock()
        app.handle_req_switch_epif(MagicMock(), body, respond, mock_client)
        return respond.called, mock_client.views_open.called

    # Allowed: requester
    denied, opened = simulate_click("U111")
    assert not denied and opened

    # Allowed: assignee
    denied, opened = simulate_click("U_ASSIGNEE", assignee_id="U_ASSIGNEE")
    assert not denied and opened

    # Allowed: unassigned buyer
    denied, opened = simulate_click("U_BUYER")
    assert not denied and opened

    # Allowed: admin
    denied, opened = simulate_click("U_ADMIN")
    assert not denied and opened

    # Denied: random user
    denied, opened = simulate_click("U_RANDOM")
    assert denied and not opened

    # Denied: buyer trying to click on assigned request to someone else
    denied, opened = simulate_click("U_BUYER", assignee_id="U_ASSIGNEE")
    assert denied and not opened


def test_switch_refused_if_already_processed_in_queue(temp_workbook, mock_client, monkeypatch):
    # Setup row 15 in the temp workbook
    log_writer.update_row(15, {"A": "15", "B": "Vendor", "C": "Item"}, workbook_path=temp_workbook)

    # We will simulate marking it processed just before the task runs
    def mock_submit_write_task(action_fn, *args, **kwargs):
        # Oh wait, someone processed it!
        log_writer.update_row(15, {config.COLUMN_DATE_PROCESSED: "2026-09-22"}, workbook_path=temp_workbook)
        try:
            action_fn()
        except RuntimeError as err:
            kwargs["failure_callback"](err)

    monkeypatch.setattr("src.queue_worker.submit_write_task", mock_submit_write_task)

    view = {
        "private_metadata": json.dumps({"channel_id": "C1", "thread_ts": "T1", "card_ts": "123.4", "vendor_choice": "Vendor"}),
        "state": {"values": {
            "block_item_description": {"item_description": {"value": "New Item"}},
            "block_purpose": {"purpose": {"value": "New Purpose"}},
            "block_total_price": {"total_price": {"value": "50.00"}},
            "block_date_of_purchase": {"date_of_purchase": {"selected_date": "2026-09-22"}},
            "block_delivery_room": {"delivery_room": {"value": "Room A"}},
            "block_project_id": {"project_id": {"value": "PRJ1"}},
            "block_fund": {"fund": {"value": "133"}},
            "block_category": {"category": {"selected_option": {"value": "Supplies"}}},
        }}
    }

    monkeypatch.setattr("src.slack_io.get_card_payload", lambda *a, **k: {"state": "approved", "request": {"row": 15}})

    app.handle_switch_epif_submit(MagicMock(), {"user": {"id": "U1"}}, mock_client, view)

    # Assert thread reply happened
    mock_client.chat_postMessage.assert_called()
    call_args = mock_client.chat_postMessage.call_args[1]
    assert "Failed to switch" in call_args["text"]
    assert "already been processed" in call_args["text"]


def test_switch_success_flow(temp_workbook, sync_queue, mock_client, tmp_path, monkeypatch):
    epifs_dir = tmp_path / "EPIFs"
    monkeypatch.setattr("src.config.EPIFS_DIR", str(epifs_dir))
    monkeypatch.setattr("src.config.WORKBOOK_PATH", temp_workbook)
    # The fixture template
    template_path = os.path.join(os.path.dirname(__file__), "fixtures", "EPIF_TEMPLATE_HIRST.pdf")
    monkeypatch.setattr("src.config.EPIF_TEMPLATE_PATH", template_path)
    monkeypatch.setattr("src.config.BOMS_DIR", str(tmp_path / "BOMs"))

    log_writer.update_row(15, {"A": "15", config.COLUMN_REQUESTER: "Original Requester", "C": "Old Item", config.COLUMN_DATE_OF_REQUEST: "2026-09-20"}, workbook_path=temp_workbook)

    view = {
        "private_metadata": json.dumps({"channel_id": "C1", "thread_ts": "T1", "card_ts": "123.4", "vendor_choice": "Vendor"}),
        "state": {"values": {
            "block_item_description": {"item_description": {"value": "New Item"}},
            "block_purpose": {"purpose": {"value": "New Purpose"}},
            "block_total_price": {"total_price": {"value": "50.00"}},
            "block_date_of_purchase": {"date_of_purchase": {"selected_date": "2026-09-22"}},
            "block_delivery_room": {"delivery_room": {"value": "Room A"}},
            "block_project_id": {"project_id": {"value": "PRJ1"}},
            "block_fund": {"fund": {"value": "133"}},
            "block_category": {"category": {"selected_option": {"value": "Supplies"}}},
        }}
    }

    req_data = {"row": 15, "assignee_id": "U_ASSIGNEE"}
    monkeypatch.setattr("src.slack_io.get_card_payload", lambda *a, **k: {"state": "approved", "request": req_data, "requester": "Original Requester"})
    monkeypatch.setattr("src.slack_io.resolve_requester", lambda *a, **k: "Original Requester")

    app.handle_switch_epif_submit(MagicMock(), {"user": {"id": "U1"}}, mock_client, view)

    sync_queue()  # Wait for queued task

    # Check row was updated (row number unchanged, requester unchanged)
    row_info = log_writer.get_row_info(15, workbook_path=temp_workbook)
    assert row_info["requester"] == "Original Requester"
    assert row_info["item_description"] == "New Item"
    # Note: How Buying is E, we would check that, but log_writer.get_row_info doesn't currently pull it unless explicitly asked.

    # Check EPIF generated
    epif_files = os.listdir(epifs_dir)
    assert len(epif_files) == 1
    assert "EPIF" in epif_files[0]

    # Check thread message
    mock_client.chat_postMessage.assert_called()
    thread_msg = next(call[1]["text"] for call in mock_client.chat_postMessage.call_args_list if "Switched to EPIF" in call[1]["text"])
    assert "🔁 Switched to EPIF by Original Requester." in thread_msg

    # Check chat_update (route becomes epif)
    mock_client.chat_update.assert_called()
    update_blocks = mock_client.chat_update.call_args[1]["blocks"]

    # parse the button value to see route
    btn_val = None
    for b in update_blocks:
        if b["type"] == "actions":
            btn_val = json.loads(b["elements"][0]["value"])
            break
    assert btn_val["request"]["route"] == "epif"
    assert btn_val["request"]["source"] == "epif"

    # Check assignee DM
    mock_client.files_upload_v2.assert_called()
    assert "Place this in Workday:" not in str(mock_client.chat_postMessage.call_args_list)
