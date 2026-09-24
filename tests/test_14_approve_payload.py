"""Tests for Ticket 14: The Approve button uses the payload it was handed.

Acceptance criteria:
- handle_epif_processing accepts posted_payload and resolves sources in the order in requirement 2:
  direct_file -> a PDF found in the thread -> posted_payload -> the Slack metadata lookup -> "couldn't find" reply
- Approving a card posted by /new-purchase logs the item shown on that card,
  asserted by the row values reaching log_writer.build_row — not by asserting which lookup function ran
- A thread containing a message whose text mimics the old '🛒 *New Purchase Request' summary
  but carries no metadata produces no request and no row
- The string 'sales@vendor.com' appears nowhere in src/
- find_modal_request_in_thread appears nowhere in src/; the metadata branch survives as
  find_request_metadata_in_thread and a test covers it
- The keyword path (@Purchasing approved in a modal-posted card's thread, no button payload)
  still resolves through metadata and still writes the row
- find_row_in_thread returns no row for a thread containing 'Fund 133' and a price,
  and does return the row for the bot's own 'Logged to row 18' line
- ruff check ., python scripts/check_tests_first.py and pytest -q all pass
"""
import datetime
import json
import os
from unittest.mock import MagicMock

import pytest

from src import app, epif_parser, lifecycle, log_writer, queue_worker, roster, slack_io


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


def test_source_scan_no_sales_at_vendor_com_in_src():
    """AC: The string 'sales@vendor.com' appears nowhere in src/."""
    src_dir = os.path.join(os.path.dirname(__file__), "..", "src")
    found_files = []
    for root, _, files in os.walk(src_dir):
        for fname in files:
            if fname.endswith(".py"):
                fpath = os.path.join(root, fname)
                with open(fpath, "r", encoding="utf-8") as f:
                    if "sales@vendor.com" in f.read():
                        found_files.append(fname)
    assert not found_files, f"'sales@vendor.com' found in src files: {found_files}"


def test_source_scan_find_modal_request_in_thread_removed():
    """AC: find_modal_request_in_thread appears nowhere in src/; find_request_metadata_in_thread exists."""
    src_dir = os.path.join(os.path.dirname(__file__), "..", "src")
    found_files = []
    for root, _, files in os.walk(src_dir):
        for fname in files:
            if fname.endswith(".py"):
                fpath = os.path.join(root, fname)
                with open(fpath, "r", encoding="utf-8") as f:
                    if "find_modal_request_in_thread" in f.read():
                        found_files.append(fname)
    assert not found_files, f"'find_modal_request_in_thread' found in src files: {found_files}"
    assert hasattr(slack_io, "find_request_metadata_in_thread"), (
        "slack_io must define find_request_metadata_in_thread"
    )


def test_find_row_in_thread_narrowed():
    """AC: find_row_in_thread returns no row for thread containing 'Fund 133' and a price,

    and returns row for the bot's own 'Logged to row 18' line.
    """
    client = MagicMock()

    # Case 1: Human prose mentioning Fund 133 and price, and even old-style Row #12
    client.conversations_replies.return_value = {
        "messages": [
            {"text": "Hey check this order out, cost is $133.50 for Fund 133."},
            {"text": "Can we also check Row #12 or item 50?"},
        ]
    }
    row = slack_io.find_row_in_thread(client, "C1", "100.0")
    assert row is None, f"Expected None for human prose, got {row}"

    # Case 2: Bot's own 'Logged to row 18' line
    client.conversations_replies.return_value = {
        "messages": [
            {"text": "Hey check this order out, cost is $133.50 for Fund 133."},
            {"text": "Logged to row 18: Optics Mount — $150.00 from Thorlabs (Supplies)."},
        ]
    }
    row = slack_io.find_row_in_thread(client, "C1", "100.0")
    assert row == 18, f"Expected 18, got {row}"


def test_find_request_metadata_in_thread():
    """AC: find_request_metadata_in_thread parses Slack metadata correctly."""
    client = MagicMock()
    client.conversations_replies.return_value = {
        "messages": [
            {
                "text": "Card without metadata",
            },
            {
                "text": "Some message",
                "metadata": {
                    "event_type": "purchase_request",
                    "event_payload": {
                        "parsed": {
                            "item_description": "Laser Diode",
                            "total_price": 250.0,
                            "vendor": "Thorlabs",
                            "date_of_purchase": "2026-09-17",
                            "category": "Research/Lab Supplies (3105)",
                            "project_id": "123456",
                            "fund": "133",
                        },
                        "requester": "Alex",
                        "user_id": "U_REQ",
                        "is_pending_name": False,
                    },
                },
            },
        ]
    }
    parsed, requester, user_id, is_pending = slack_io.find_request_metadata_in_thread(client, "C1", "100.0")
    assert parsed is not None
    assert parsed["item_description"] == "Laser Diode"
    assert parsed["date_of_purchase"] == datetime.date(2026, 9, 17)
    assert requester == "Alex"
    assert user_id == "U_REQ"
    assert is_pending is False


def test_mimicked_summary_prose_without_metadata_produces_no_request_and_no_row(monkeypatch):
    """AC: A thread containing a message whose text mimics the old '🛒 *New Purchase Request'

    summary but carries no metadata produces no request and no row.
    """
    client = MagicMock()
    say = MagicMock()

    mimic_text = (
        "🛒 *New Purchase Request from Alex:*\n"
        "• *Item:* Titanium Screws\n"
        "• *Total:* $99.99\n"
        "• *Vendor:* McMaster-Carr (P-card)\n"
        "• *Category:* Research/Lab Supplies (3105)\n"
        "• *Project ID / Fund:* PRJ123 (Fund 133)\n"
        "• *Delivery Room:* ERB 123\n"
        "• *Purpose:* Lab assembly"
    )
    # No PDF, no metadata on messages
    client.conversations_replies.return_value = {
        "messages": [
            {"text": mimic_text, "ts": "100.0"},
        ]
    }

    submitted_tasks = []
    monkeypatch.setattr(
        queue_worker,
        "submit_write_task",
        lambda *a, **kw: submitted_tasks.append(kw),
    )

    lifecycle.handle_epif_processing(
        client=client,
        say=say,
        channel="C1",
        thread_ts="100.0",
        approver="U_CHARLIE",
        event_ts="100.1",
        posted_payload=None,
    )

    # No task submitted
    assert len(submitted_tasks) == 0, "Expected no write task to be submitted!"
    # Says couldn't find
    say.assert_called_once()
    assert "treating this as a *Workday order*" in say.call_args[1]["text"]


def test_approving_card_posted_by_new_purchase_logs_item_on_card(monkeypatch):
    """AC: Approving a card posted by /new-purchase logs the item shown on that card,

    asserted by the row values reaching log_writer.build_row — not by asserting which lookup function ran.
    """
    client = MagicMock()
    say = MagicMock()

    captured_build_row_args = []
    orig_build_row = log_writer.build_row

    def tracking_build_row(parsed, requester):
        captured_build_row_args.append((parsed, requester))
        return orig_build_row(parsed, requester)

    monkeypatch.setattr(log_writer, "build_row", tracking_build_row)
    monkeypatch.setattr(log_writer, "append_row", lambda row, path=None: 25)
    monkeypatch.setattr(slack_io, "find_card_in_thread", lambda *a, **kw: ({}, "100.0", [], "posted"))

    # Drains synchronously
    def sync_submit(action_fn, channel, thread_ts, user_id, task_type, description, success_callback, failure_callback, client=None):
        res = action_fn()
        success_callback(res)

    monkeypatch.setattr(queue_worker, "submit_write_task", sync_submit)

    posted_payload = {
        "parsed": {
            "item_description": "Precision Optical Rail 500mm",
            "total_price": 349.50,
            "vendor": "Thorlabs",
            "category": "Research/Lab Supplies (3105)",
            "category_error": None,
            "project_id": "PG000025831",
            "fund": "133",
            "delivery_room": "ERB 212",
            "purpose": "Beam steering setup",
            "payment_method": "Workday",
            "date_of_purchase": "2026-09-17",
            "link": "https://thorlabs.com/item123",
            "vendor_contact_email": "orders@thorlabs.com",
            "vendor_contact_name": "Thorlabs Rep",
            "name_of_system": "",
            "asset_id": "",
        },
        "requester": "Alex",
        "user_id": "U_REQ",
        "is_pending_name": False,
    }

    # Simulate handle_req_approve_action passing posted_payload
    lifecycle.handle_epif_processing(
        client=client,
        say=say,
        channel="C1",
        thread_ts="100.0",
        approver="U_CHARLIE",
        event_ts="100.1",
        posted_payload=posted_payload,
    )

    assert len(captured_build_row_args) == 1, "build_row should have been called once"
    logged_parsed, logged_requester = captured_build_row_args[0]

    assert logged_requester == "Alex"
    assert logged_parsed["item_description"] == "Precision Optical Rail 500mm"
    assert logged_parsed["total_price"] == 349.50
    assert logged_parsed["vendor"] == "Thorlabs"
    assert logged_parsed["project_id"] == "PG000025831"
    assert logged_parsed["fund"] == "133"
    assert logged_parsed["delivery_room"] == "ERB 212"
    assert logged_parsed["purpose"] == "Beam steering setup"
    assert logged_parsed["date_of_purchase"] == datetime.date(2026, 9, 17)


def test_keyword_path_approves_via_metadata_lookup(monkeypatch):
    """AC: The keyword path (@Purchasing approved in a modal-posted card's thread, no button payload)

    still resolves through metadata and still writes the row.
    """
    client = MagicMock()
    say = MagicMock()

    # Thread messages carry metadata
    client.conversations_replies.return_value = {
        "messages": [
            {
                "text": "Card posted by modal",
                "metadata": {
                    "event_type": "purchase_request",
                    "event_payload": {
                        "parsed": {
                            "item_description": "Spectrometer Grating",
                            "total_price": 890.00,
                            "vendor": "Edmund Optics",
                            "category": "Research/Lab Supplies (3105)",
                            "category_error": None,
                            "project_id": "PG000025831",
                            "fund": "133",
                            "delivery_room": "ERB 212",
                            "purpose": "Monochromator upgrade",
                            "payment_method": "P-card",
                            "date_of_purchase": "2026-09-17",
                            "link": "",
                            "vendor_contact_email": "orders@edmundoptics.com",
                            "vendor_contact_name": "EO Rep",
                            "name_of_system": "",
                            "asset_id": "",
                        },
                        "requester": "Isaac",
                        "user_id": "U_ADMIN",
                        "is_pending_name": False,
                    },
                },
            }
        ]
    }

    captured_build_row_args = []
    orig_build_row = log_writer.build_row

    def tracking_build_row(parsed, requester):
        captured_build_row_args.append((parsed, requester))
        return orig_build_row(parsed, requester)

    monkeypatch.setattr(log_writer, "build_row", tracking_build_row)
    monkeypatch.setattr(log_writer, "append_row", lambda row, path=None: 26)
    monkeypatch.setattr(slack_io, "find_card_in_thread", lambda *a, **kw: ({}, "100.0", [], "posted"))

    def sync_submit(action_fn, channel, thread_ts, user_id, task_type, description, success_callback, failure_callback, client=None):
        res = action_fn()
        success_callback(res)

    monkeypatch.setattr(queue_worker, "submit_write_task", sync_submit)

    # Keyword path: posted_payload is None
    lifecycle.handle_epif_processing(
        client=client,
        say=say,
        channel="C1",
        thread_ts="100.0",
        approver="U_CHARLIE",
        event_ts="100.1",
        posted_payload=None,
    )

    assert len(captured_build_row_args) == 1, "build_row should have been called once via metadata resolution"
    logged_parsed, logged_requester = captured_build_row_args[0]
    assert logged_requester == "Isaac"
    assert logged_parsed["item_description"] == "Spectrometer Grating"
    assert logged_parsed["total_price"] == 890.00
    assert logged_parsed["vendor"] == "Edmund Optics"


def test_handle_epif_processing_resolution_order(monkeypatch):
    """AC: Requirement 2 resolution order:

    direct_file -> PDF in thread -> posted_payload -> Slack metadata -> "couldn't find"
    """
    client = MagicMock()
    say = MagicMock()

    # Step A: direct_file beats everything
    # When direct_file is provided, it must not use posted_payload or metadata
    direct_file_obj = {"name": "EPIF_direct.pdf"}
    downloaded_files = []

    def mock_download(file_obj):
        downloaded_files.append(file_obj.get("name"))
        return b"%PDF-1.4 sample content"

    monkeypatch.setattr(slack_io, "download", mock_download)
    monkeypatch.setattr(
        epif_parser,
        "parse_epif",
        lambda pdf_bytes: {
            "item_description": "Direct File Item",
            "total_price": 100.0,
            "vendor": "V1",
            "category": "Research/Lab Supplies (3105)",
            "category_error": None,
            "project_id": "PG000025831",
            "fund": "133",
            "delivery_room": "ERB 212",
            "purpose": "Test",
            "date_of_purchase": datetime.date(2026, 9, 17),
            "payment_method": "P-card",
            "vendor_contact_email": "orders@v1.com",
        },
    )

    captured_build_rows = []
    monkeypatch.setattr(log_writer, "build_row", lambda p, r: captured_build_rows.append(p["item_description"]))
    monkeypatch.setattr(log_writer, "append_row", lambda row, path=None: 1)
    monkeypatch.setattr(log_writer, "save_epif", lambda b, f: f"EPIFs/{f}")
    monkeypatch.setattr(slack_io, "find_card_in_thread", lambda *a, **kw: ({}, "100.0", [], "posted"))
    monkeypatch.setattr(
        queue_worker,
        "submit_write_task",
        lambda action_fn, channel, thread_ts, user_id, task_type, description, success_callback, failure_callback, client=None: success_callback(action_fn()),
    )

    dummy_payload = {
        "parsed": {
            "item_description": "Payload Item",
            "total_price": 50.0,
            "vendor": "V2",
            "category": "Research/Lab Supplies (3105)",
            "category_error": None,
            "project_id": "PG000025831",
            "fund": "133",
            "purpose": "Test payload",
            "delivery_room": "ERB 212",
            "date_of_purchase": "2026-09-17",
            "payment_method": "P-card",
            "vendor_contact_email": "orders@v2.com",
        },
        "requester": "Alex",
    }

    # 1. direct_file provided along with posted_payload
    lifecycle.handle_epif_processing(
        client=client,
        say=say,
        channel="C1",
        thread_ts="100.0",
        approver="U_CHARLIE",
        event_ts="100.1",
        direct_file=direct_file_obj,
        direct_poster="U_REQ",
        posted_payload=dummy_payload,
    )
    assert captured_build_rows[-1] == "Direct File Item"
    assert downloaded_files[-1] == "EPIF_direct.pdf"

    # 2. PDF in thread beats posted_payload
    monkeypatch.setattr(slack_io, "find_epif_in_thread", lambda cl, ch, ts: ({"name": "EPIF_thread.pdf"}, "U_REQ"))
    lifecycle.handle_epif_processing(
        client=client,
        say=say,
        channel="C1",
        thread_ts="100.0",
        approver="U_CHARLIE",
        event_ts="100.1",
        posted_payload=dummy_payload,
    )
    assert captured_build_rows[-1] == "Direct File Item"  # parse_epif mock returns "Direct File Item"
    assert downloaded_files[-1] == "EPIF_thread.pdf"

    # 3. posted_payload beats metadata lookup
    monkeypatch.setattr(slack_io, "find_epif_in_thread", lambda cl, ch, ts: (None, None))
    meta_called = []

    def mock_meta_lookup(cl, ch, ts):
        meta_called.append(True)
        return (
            {
                "item_description": "Metadata Item",
                "total_price": 20.0,
                "vendor": "V3",
                "category": "Research/Lab Supplies (3105)",
                "category_error": None,
                "project_id": "PG000025831",
                "fund": "133",
                "purpose": "Test meta",
                "delivery_room": "ERB 212",
                "date_of_purchase": datetime.date(2026, 9, 17),
                "payment_method": "P-card",
                "vendor_contact_email": "orders@v3.com",
            },
            "Alex",
            "U_REQ",
            False,
        )

    monkeypatch.setattr(slack_io, "find_request_metadata_in_thread", mock_meta_lookup)

    lifecycle.handle_epif_processing(
        client=client,
        say=say,
        channel="C1",
        thread_ts="100.0",
        approver="U_CHARLIE",
        event_ts="100.1",
        posted_payload=dummy_payload,
    )
    assert captured_build_rows[-1] == "Payload Item"
    assert len(meta_called) == 0, "Metadata lookup must not be called when posted_payload is present"


def test_handle_req_approve_action_passes_posted_payload(monkeypatch):
    """AC: handle_req_approve_action reads request from button value and passes as posted_payload."""
    passed_args = {}

    def mock_epif_processing(**kwargs):
        passed_args.update(kwargs)

    monkeypatch.setattr(lifecycle, "handle_epif_processing", mock_epif_processing)

    req_data = {
        "parsed": {
            "item_description": "Optics Board",
            "total_price": 500.0,
            "vendor": "Thorlabs",
        },
        "requester": "Dylan",
        "user_id": "U_BUYER",
    }
    btn_val = json.dumps({
        "state": "posted",
        "requester": "Dylan",
        "thread_ts": "100.5",
        "request": req_data,
        "history": [],
    })

    body = {
        "user": {"id": "U_CHARLIE"},
        "channel": {"id": "C_PURCHASE"},
        "message": {"ts": "100.5"},
        "container": {"thread_ts": "100.5"},
        "actions": [{"value": btn_val}],
    }
    respond = MagicMock()
    client = MagicMock()
    ack = MagicMock()

    app.handle_req_approve_action(ack, body, respond, client)

    ack.assert_called_once()
    assert passed_args.get("approver") == "U_CHARLIE"
    assert passed_args.get("posted_payload") == req_data
