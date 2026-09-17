"""Tests for Ticket 13: The card follows the write, not the click.

Acceptance criteria:
- handle_processed, handle_confirmation and handle_delivery each accept card_ts, req_data and history, and render the card inside on_success
- A handle_processed call that cannot identify a row posts its reply and calls chat_update not at all — assert on the absence
- A handle_processed whose queued write fails: the thread gets the error and the card still reads approved — asserted on the rendered blocks, not a flag
- A successful handle_processed: the card reads processed and history gained exactly one line
- The same three criteria hold for handle_confirmation and handle_delivery
- An approval whose EPIF fails validation writes no row and leaves the card on its previous state — asserted on the blocks
- A test with the workbook locked asserts the card stays on the previous stage and the thread carries the delayed-write message
- chat_update appears nowhere in src/app.py (source scan)
- handle_cancel is unchanged and its existing tests still pass untouched
"""
import json
import os
import time
from unittest.mock import MagicMock

import pytest

from src import blocks, config, lifecycle, queue_worker, roster


@pytest.fixture(autouse=True)
def clean_roster(tmp_path, monkeypatch):
    """Ensure a fresh isolated roster for each test."""
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
        "vendors": [],
    }
    with open(roster_file, "w", encoding="utf-8") as f:
        json.dump(data, f)
    return roster_file


def test_source_scan_no_chat_update_in_app_py():
    """Requirement 5: chat_update appears nowhere in src/app.py."""
    app_py_path = os.path.join(os.path.dirname(__file__), "..", "src", "app.py")
    with open(app_py_path, "r", encoding="utf-8") as f:
        content = f.read()

    assert "chat_update" not in content, (
        "Found 'chat_update' in src/app.py! Every chat_update must leave src/app.py."
    )


def test_handle_processed_no_row_no_chat_update():
    """Requirement 3: handle_processed with no row identified posts reply and never calls chat_update."""
    client = MagicMock()
    say = MagicMock()

    lifecycle.handle_processed(
        client=client,
        say=say,
        channel="C1",
        thread_ts="",
        user_id="U_UNKNOWN",
        event_ts="100.1",
        text="no row here",
        card_ts="100.0",
        req_data={"state": "approved"},
        history=[],
    )

    say.assert_called_once()
    assert "couldn't figure out which order" in say.call_args[1]["text"]
    client.chat_update.assert_not_called()


def test_handle_processed_queued_write_fails_card_stays_approved(monkeypatch):
    """Requirement 1 & Criteria: When write fails, error is posted to thread and card is NOT updated."""
    client = MagicMock()
    say = MagicMock()

    # Fail the write in queue_worker
    def fail_submit(action_fn, channel, thread_ts, user_id, task_type, description, success_callback, failure_callback, client=None):
        failure_callback(Exception("Simulated disk error"))

    monkeypatch.setattr(lifecycle.queue_worker, "submit_write_task", fail_submit)

    initial_history = ["Approved by Charlie H. on 09/16/26 10:00"]
    req_data = {
        "item_description": "Laser Mount",
        "total_price": 150.0,
        "vendor": "Thorlabs",
        "category": "Research/Lab Supplies (3105)",
        "assignee_id": "U_BUYER",
        "assignee": "Dylan",
    }

    lifecycle.handle_processed(
        client=client,
        say=say,
        channel="C_PURCHASE",
        thread_ts="100.00",
        user_id="U_BUYER",
        event_ts="100.10",
        text="Row 42",
        card_ts="100.00",
        req_data=req_data,
        history=initial_history,
    )

    # Thread gets error
    say.assert_called_once()
    assert "Error updating Order Log" in say.call_args[1]["text"]
    # Card was NOT updated
    client.chat_update.assert_not_called()


def test_handle_processed_success_card_advances_and_history_gains_one_line(monkeypatch):
    """Requirement 1 & 2: Successful handle_processed renders card to 'processed' and adds 1 history line."""
    client = MagicMock()
    say = MagicMock()

    def success_submit(action_fn, channel, thread_ts, user_id, task_type, description, success_callback, failure_callback, client=None):
        res = action_fn()
        success_callback(res)

    monkeypatch.setattr(lifecycle.queue_worker, "submit_write_task", success_submit)
    monkeypatch.setattr(lifecycle.log_writer, "update_row", lambda row, vals, workbook_path=None: row)
    monkeypatch.setattr(lifecycle.log_writer, "get_row_info", lambda row: {"row": row, "item_description": "Laser Mount"})

    initial_history = ["Approved by Charlie H. on 09/16/26 10:00"]
    req_data = {
        "item_description": "Laser Mount",
        "total_price": 150.0,
        "vendor": "Thorlabs",
        "category": "Research/Lab Supplies (3105)",
        "assignee_id": "U_BUYER",
        "assignee": "Dylan",
    }

    lifecycle.handle_processed(
        client=client,
        say=say,
        channel="C_PURCHASE",
        thread_ts="100.00",
        user_id="U_BUYER",
        event_ts="100.10",
        text="Row 42",
        card_ts="100.00",
        req_data=req_data,
        history=list(initial_history),
    )

    client.chat_update.assert_called_once()
    update_call = client.chat_update.call_args[1]
    assert update_call["channel"] == "C_PURCHASE"
    assert update_call["ts"] == "100.00"
    assert update_call["text"] == "🛒 Purchase Request (Processed)"

    # Verify blocks: next button is req_confirmed
    actions_block = next(b for b in update_call["blocks"] if b.get("type") == "actions")
    assert actions_block["elements"][0]["action_id"] == "req_confirmed"

    # Verify history gained EXACTLY ONE line
    context_block = next(b for b in update_call["blocks"] if b.get("type") == "context")
    context_text = context_block["elements"][0]["text"]
    lines = [line for line in context_text.split("\n") if line.strip()]
    bullet_lines = [line for line in lines if line.startswith("•")]
    assert len(bullet_lines) == len(initial_history) + 1
    assert "Approved by Charlie H." in bullet_lines[0]
    assert "Processed by Dylan on" in bullet_lines[1]


def test_handle_confirmation_no_row_no_chat_update():
    """handle_confirmation with no row identified posts reply and never calls chat_update."""
    client = MagicMock()
    say = MagicMock()

    lifecycle.handle_confirmation(
        client=client,
        say=say,
        channel="C1",
        thread_ts="",
        user_id="U_UNKNOWN",
        event_ts="100.1",
        text="no row here",
        card_ts="100.0",
        req_data={"state": "processed"},
        history=[],
    )

    say.assert_called_once()
    assert "couldn't figure out which order" in say.call_args[1]["text"]
    client.chat_update.assert_not_called()


def test_handle_confirmation_queued_write_fails_card_stays_processed(monkeypatch):
    """When confirmation write fails, error is posted and card is NOT updated."""
    client = MagicMock()
    say = MagicMock()

    def fail_submit(action_fn, channel, thread_ts, user_id, task_type, description, success_callback, failure_callback, client=None):
        failure_callback(Exception("Write failed"))

    monkeypatch.setattr(lifecycle.queue_worker, "submit_write_task", fail_submit)

    initial_history = [
        "Approved by Charlie H. on 09/16/26 10:00",
        "Processed by Dylan on 09/16/26 11:00",
    ]
    req_data = {"item_description": "Laser Mount", "assignee_id": "U_BUYER", "assignee": "Dylan"}

    lifecycle.handle_confirmation(
        client=client,
        say=say,
        channel="C_PURCHASE",
        thread_ts="100.00",
        user_id="U_BUYER",
        event_ts="100.20",
        text="Row 42",
        card_ts="100.00",
        req_data=req_data,
        history=initial_history,
    )

    say.assert_called_once()
    assert "Error updating Order Log" in say.call_args[1]["text"]
    client.chat_update.assert_not_called()


def test_handle_confirmation_success_card_advances_and_history_gains_one_line(monkeypatch):
    """Successful handle_confirmation renders card to 'confirmed' and adds 1 history line."""
    client = MagicMock()
    say = MagicMock()

    def success_submit(action_fn, channel, thread_ts, user_id, task_type, description, success_callback, failure_callback, client=None):
        res = action_fn()
        success_callback(res)

    monkeypatch.setattr(lifecycle.queue_worker, "submit_write_task", success_submit)
    monkeypatch.setattr(lifecycle.log_writer, "update_row", lambda row, vals, workbook_path=None: row)
    monkeypatch.setattr(lifecycle.log_writer, "get_row_info", lambda row: {"row": row, "item_description": "Laser Mount"})

    initial_history = [
        "Approved by Charlie H. on 09/16/26 10:00",
        "Processed by Dylan on 09/16/26 11:00",
    ]
    req_data = {"item_description": "Laser Mount", "assignee_id": "U_BUYER", "assignee": "Dylan"}

    lifecycle.handle_confirmation(
        client=client,
        say=say,
        channel="C_PURCHASE",
        thread_ts="100.00",
        user_id="U_BUYER",
        event_ts="100.20",
        text="Row 42",
        card_ts="100.00",
        req_data=req_data,
        history=list(initial_history),
    )

    client.chat_update.assert_called_once()
    update_call = client.chat_update.call_args[1]
    assert update_call["channel"] == "C_PURCHASE"
    assert update_call["ts"] == "100.00"
    assert update_call["text"] == "🛒 Purchase Request (Confirmed)"

    # Verify blocks: next button is req_delivered
    actions_block = next(b for b in update_call["blocks"] if b.get("type") == "actions")
    assert actions_block["elements"][0]["action_id"] == "req_delivered"

    # Verify history gained EXACTLY ONE line
    context_block = next(b for b in update_call["blocks"] if b.get("type") == "context")
    context_text = context_block["elements"][0]["text"]
    lines = [line for line in context_text.split("\n") if line.strip()]
    bullet_lines = [line for line in lines if line.startswith("•")]
    assert len(bullet_lines) == len(initial_history) + 1
    assert "Approved by Charlie H." in bullet_lines[0]
    assert "Processed by Dylan on" in bullet_lines[1]
    assert "Confirmed by Dylan on" in bullet_lines[2]


def test_handle_delivery_no_row_no_chat_update():
    """handle_delivery with no row identified posts reply and never calls chat_update."""
    client = MagicMock()
    say = MagicMock()

    lifecycle.handle_delivery(
        client=client,
        say=say,
        channel="C1",
        thread_ts="",
        user_id="U_UNKNOWN",
        event_ts="100.1",
        text="no row here",
        card_ts="100.0",
        req_data={"state": "confirmed"},
        history=[],
    )

    say.assert_called_once()
    assert "couldn't figure out which order" in say.call_args[1]["text"]
    client.chat_update.assert_not_called()


def test_handle_delivery_queued_write_fails_card_stays_confirmed(monkeypatch):
    """When delivery write fails, error is posted and card is NOT updated."""
    client = MagicMock()
    say = MagicMock()

    def fail_submit(action_fn, channel, thread_ts, user_id, task_type, description, success_callback, failure_callback, client=None):
        failure_callback(Exception("Write failed"))

    monkeypatch.setattr(lifecycle.queue_worker, "submit_write_task", fail_submit)

    initial_history = [
        "Approved by Charlie H. on 09/16/26 10:00",
        "Processed by Dylan on 09/16/26 11:00",
        "Confirmed by Dylan on 09/16/26 12:00",
    ]
    req_data = {"item_description": "Laser Mount", "assignee_id": "U_BUYER", "assignee": "Dylan"}

    lifecycle.handle_delivery(
        client=client,
        say=say,
        channel="C_PURCHASE",
        thread_ts="100.00",
        user_id="U_BUYER",
        event_ts="100.30",
        text="Row 42",
        card_ts="100.00",
        req_data=req_data,
        history=initial_history,
    )

    say.assert_called_once()
    assert "Error updating Order Log" in say.call_args[1]["text"]
    client.chat_update.assert_not_called()


def test_handle_delivery_success_card_advances_and_history_gains_one_line(monkeypatch):
    """Successful handle_delivery renders card to 'delivered' and adds 1 history line."""
    client = MagicMock()
    say = MagicMock()

    def success_submit(action_fn, channel, thread_ts, user_id, task_type, description, success_callback, failure_callback, client=None):
        res = action_fn()
        success_callback(res)

    monkeypatch.setattr(lifecycle.queue_worker, "submit_write_task", success_submit)
    monkeypatch.setattr(lifecycle.log_writer, "update_row", lambda row, vals, workbook_path=None: row)
    monkeypatch.setattr(lifecycle.log_writer, "get_row_info", lambda row: {"row": row, "item_description": "Laser Mount"})

    initial_history = [
        "Approved by Charlie H. on 09/16/26 10:00",
        "Processed by Dylan on 09/16/26 11:00",
        "Confirmed by Dylan on 09/16/26 12:00",
    ]
    req_data = {"item_description": "Laser Mount", "assignee_id": "U_BUYER", "assignee": "Dylan"}

    lifecycle.handle_delivery(
        client=client,
        say=say,
        channel="C_PURCHASE",
        thread_ts="100.00",
        user_id="U_BUYER",
        event_ts="100.30",
        text="Row 42",
        card_ts="100.00",
        req_data=req_data,
        history=list(initial_history),
    )

    client.chat_update.assert_called_once()
    update_call = client.chat_update.call_args[1]
    assert update_call["channel"] == "C_PURCHASE"
    assert update_call["ts"] == "100.00"
    assert update_call["text"] == "🛒 Purchase Request (Delivered)"

    # Verify blocks: no action buttons on delivered
    assert not any(b.get("type") == "actions" for b in update_call["blocks"])

    # Verify history gained EXACTLY ONE line
    context_block = next(b for b in update_call["blocks"] if b.get("type") == "context")
    context_text = context_block["elements"][0]["text"]
    lines = [line for line in context_text.split("\n") if line.strip()]
    bullet_lines = [line for line in lines if line.startswith("•")]
    assert len(bullet_lines) == len(initial_history) + 1
    assert "Delivered to Dylan on" in bullet_lines[3]


def test_approval_validation_failure_leaves_card_unchanged(monkeypatch):
    """Approval whose EPIF fails validation writes no row and leaves card unchanged."""
    client = MagicMock()
    say = MagicMock()
    append_mock = MagicMock()
    monkeypatch.setattr(lifecycle.log_writer, "append_row", append_mock)

    # Card is already posted in thread
    card_blocks = blocks.build_request_blocks("posted", {"item_description": "Bad Item"}, history=[])
    thread_messages = [{
        "ts": "100.05",
        "thread_ts": "100.00",
        "blocks": card_blocks,
    }]
    client.conversations_replies.return_value = {"ok": True, "messages": thread_messages}

    # Invalid parsed request (missing purpose, total_price is None, etc.)
    invalid_parsed = {
        "item_description": "Bad Item",
        "purpose": "",
        "total_price": None,
        "vendor": "",
        "vendor_contact_email": "",
        "date_of_purchase": None,
        "payment_method": "",
        "category": "",
        "category_error": None,
        "project_id": "",
        "fund": "",
        "delivery_room": "",
    }

    lifecycle.finalize_purchase_request(
        client=client,
        say=say,
        channel="C_PURCHASE",
        thread_ts="100.00",
        event_ts="100.10",
        parsed=invalid_parsed,
        requester="Alex",
        notify_target="U_REQ",
    )

    # Row is NOT appended
    append_mock.assert_not_called()
    # Card is NOT updated
    client.chat_update.assert_not_called()
    # Rejection reported
    say.assert_called_once()
    assert "Not logged -" in say.call_args[1]["text"]


def test_workbook_locked_card_stays_previous_stage_delayed_message_posted(tmp_path, monkeypatch):
    """Requirement 7: When workbook is locked, card stays on previous stage and thread gets delayed message."""
    mock_client = MagicMock()
    worker = queue_worker.LockQueueWorker(client=mock_client)
    monkeypatch.setattr(lifecycle.queue_worker, "get_queue_worker", lambda client=None: worker)

    # Set up workbook and lock file
    wb_file = str(tmp_path / "Purchasing-Log.xlsx")
    with open(wb_file, "w") as f:
        f.write("mock workbook")
    lock_file = str(tmp_path / "~$Purchasing-Log.xlsx")
    with open(lock_file, "w") as f:
        f.write("lock")

    monkeypatch.setattr(config, "WORKBOOK_PATH", wb_file)
    monkeypatch.setattr(config, "EXCEL_QUEUE_POLL_INTERVAL", 0.05)

    def fake_update_row(row, vals, workbook_path=None):
        if os.path.exists(lock_file):
            raise lifecycle.log_writer.WorkbookLockedError(f"Locked: {lock_file}")
        return row

    monkeypatch.setattr(lifecycle.log_writer, "update_row", fake_update_row)
    monkeypatch.setattr(lifecycle.log_writer, "get_row_info", lambda row: {"row": row, "item_description": "Locked Item"})

    say = MagicMock()
    initial_history = ["Approved by Charlie H. on 09/16/26 10:00"]
    req_data = {
        "item_description": "Locked Item",
        "total_price": 100.0,
        "vendor": "Thorlabs",
        "category": "Research/Lab Supplies (3105)",
        "assignee_id": "U_BUYER",
        "assignee": "Dylan",
    }

    try:
        worker.start()

        # Submit processed update
        lifecycle.handle_processed(
            client=mock_client,
            say=say,
            channel="C_PURCHASE",
            thread_ts="100.00",
            user_id="U_BUYER",
            event_ts="100.10",
            text="Row 42",
            card_ts="100.00",
            req_data=req_data,
            history=list(initial_history),
        )

        # Allow worker to attempt write and hit lock
        time.sleep(0.2)

        # Worker notified thread of lock
        mock_client.chat_postMessage.assert_called()
        call_texts = [call[1]["text"] for call in mock_client.chat_postMessage.call_args_list]
        assert any("currently open in Excel" in t for t in call_texts)

        # Card has NOT advanced (chat_update not called while locked)
        mock_client.chat_update.assert_not_called()

        # Now remove lock
        os.remove(lock_file)

        # Wait for worker retry (minimum poll interval is 0.5s)
        for _ in range(20):
            if mock_client.chat_update.called:
                break
            time.sleep(0.1)

        # After lock cleared, write completes and card updates!
        mock_client.chat_update.assert_called_once()
        assert mock_client.chat_update.call_args[1]["text"] == "🛒 Purchase Request (Processed)"

    finally:
        worker.stop()
