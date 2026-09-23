"""Tests for Ticket 29: Approval archives the BOM and the log points at it.

Acceptance criteria:
- [ ] Approving a three-item request writes one row, saves NNNN_<Vendor>_BOM.xlsx into the configured BOMs folder, and the saved file's header names that row
- [ ] The row's Notes cell reads BOM: <filename> (N items) — asserted by reading the workbook
- [ ] The archived spreadsheet is uploaded into the thread
- [ ] Approving a one-item request writes the row and produces no file, no Notes text and no upload
- [ ] A spreadsheet save that raises leaves the row blank, no file behind, and the card not advanced — asserted on the workbook and on the absence of a card update
- [ ] An approval whose items no longer total the request amount writes no row, creates no file, DMs the requester and posts in the thread
- [ ] Approving a request with no items behaves exactly as it does today
- [ ] The approved card's payload carries the archived file name
- [ ] Every workbook write in this ticket goes through the existing write queue
- [ ] ruff check ., python scripts/check_tests_first.py and pytest -q all pass
"""
import json
import os
import zipfile
from datetime import date
from unittest.mock import MagicMock

import openpyxl
import pytest

from src import config, lifecycle, log_writer, queue_worker, roster

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SAMPLES = os.path.join(PROJECT_ROOT, "samples")
SAMPLE_WORKBOOK = os.path.join(SAMPLES, "Purchasing-Log.xlsx")


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


def create_test_workbook(dest_path: str) -> str:
    """Build a valid Purchasing-Log.xlsx fixture with rows 12-16 filled and 17+ empty."""
    cols = [chr(c) for c in range(ord("A"), ord("Z") + 1)]
    rows_xml = ['<row r="11"><c r="B11" t="inlineStr"><is><t>Requester Name</t></is></c></row>']
    for r in range(12, 17):
        c_xml = "".join(
            f'<c r="{col}{r}" s="46" t="inlineStr"><is><t>filled</t></is></c>'
            if col in ("A", "B", "Z")
            else f'<c r="{col}{r}" s="46"/>'
            for col in cols
        )
        rows_xml.append(f'<row r="{r}">{c_xml}</row>')
    for r in range(17, 35):
        c_xml = "".join(f'<c r="{col}{r}" s="46"/>' for col in cols)
        rows_xml.append(f'<row r="{r}">{c_xml}</row>')

    sheet1_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:x14="http://schemas.microsoft.com/office/spreadsheetml/2009/9/main">\n'
        '<sheetData>' + "".join(rows_xml) + '</sheetData>\n'
        '</worksheet>'
    )
    with zipfile.ZipFile(dest_path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(config.SHEET_XML, sheet1_xml)
    return dest_path


@pytest.fixture
def temp_workbook(tmp_path, monkeypatch):
    """Create a temp copy of Purchasing-Log.xlsx and set config.WORKBOOK_PATH."""
    copy_path = str(tmp_path / "Purchasing-Log.xlsx")
    create_test_workbook(copy_path)
    monkeypatch.setattr(config, "WORKBOOK_PATH", copy_path)
    return copy_path


@pytest.fixture
def temp_boms_dir(tmp_path, monkeypatch):
    """Create a temp BOMs directory and set config.BOMS_DIR."""
    boms_path = str(tmp_path / "BOMs")
    os.makedirs(boms_path, exist_ok=True)
    monkeypatch.setattr(config, "BOMS_DIR", boms_path)
    return boms_path


@pytest.fixture
def sync_queue(monkeypatch):
    """Execute queue write tasks synchronously."""
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


def _valid_request(total_price=150.0):
    return {
        "item_description": "Shaft Couplings",
        "purpose": "Motor test stand alignment",
        "total_price": total_price,
        "vendor": "Ruland",
        "vendor_contact_name": "Sales",
        "vendor_contact_email": "sales@ruland.com",
        "date_of_purchase": date(2026, 9, 22),
        "project_id": "PG000025831",
        "fund": "133",
        "category": "Research/Lab Supplies (3105)",
        "delivery_room": "ERB 212",
        "payment_method": "Workday",
        "link": "https://ruland.com",
        "name_of_system": "",
        "asset_id": "",
    }


def _three_items():
    return [
        {"qty": 2, "name": "Coupling A", "part_number": "CP-1", "unit_price": 25.0, "link": "https://ruland.com/1", "description": "5mm"},
        {"qty": 2, "name": "Coupling B", "part_number": "CP-2", "unit_price": 35.0, "link": "https://ruland.com/2", "description": "8mm"},
        {"qty": 1, "name": "Coupling C", "part_number": "CP-3", "unit_price": 30.0, "link": "https://ruland.com/3", "description": "10mm"},
    ]


def test_approval_three_items_archives_bom_writes_notes_and_uploads(temp_workbook, temp_boms_dir, sync_queue):
    """AC 1, 2, 3, 8: 3-item request writes 1 row, archives NNNN_<Vendor>_BOM.xlsx, writes Notes, uploads file, carries bom_file."""
    client = MagicMock()
    say = MagicMock()
    parsed = _valid_request(total_price=150.0)
    items = _three_items()

    card_payload = {
        "parsed": parsed,
        "requester": "Alex",
        "user_id": "U_REQ",
        "items": items,
        "shipping": 0.0,
        "thread_ts": "100.00",
    }
    client.conversations_replies.return_value = {
        "messages": [
            {
                "ts": "100.00",
                "metadata": {
                    "event_type": "purchase_request",
                    "event_payload": card_payload,
                },
                "blocks": [],
            }
        ]
    }

    lifecycle.finalize_purchase_request(
        client=client,
        say=say,
        channel="C_PURCHASING",
        thread_ts="100.00",
        event_ts="100.10",
        parsed=parsed,
        requester="Alex",
        notify_target="U_REQ",
        card_ts="100.00",
        items=items,
        shipping=0.0,
        approver="U_CHARLIE",
    )

    # 1. Row written in workbook
    with zipfile.ZipFile(temp_workbook) as zf:
        sheet_xml = zf.read(config.SHEET_XML).decode("utf-8")
    row_num = log_writer.find_first_empty_row(sheet_xml) - 1
    assert row_num == 17

    # 2. BOM file exists in BOMS_DIR with row NNNN
    expected_fname = f"{row_num:04d}_Ruland_BOM.xlsx"
    saved_bom_path = os.path.join(temp_boms_dir, expected_fname)
    assert os.path.exists(saved_bom_path), f"Expected {saved_bom_path} to exist"

    # Saved file's header names that row
    wb = openpyxl.load_workbook(saved_bom_path)
    ws = wb.active
    assert ws["E4"].value == f"Purchasing Log row {row_num:04d}"
    assert ws["B3"].value == "Ruland"
    assert ws["B4"].value == "Alex"

    # 3. Notes column reads BOM: <filename> (N items)
    notes_val = log_writer.get_cell_value(sheet_xml, f"{config.COLUMN_NOTES}{row_num}")
    assert notes_val == f"BOM: {expected_fname} (3 items)"

    # 4. Archived spreadsheet uploaded to thread
    upload_call = client.files_upload_v2 if hasattr(client, "files_upload_v2") else client.files_upload
    upload_call.assert_called_once()
    up_kwargs = upload_call.call_args[1]
    assert up_kwargs["filename"] == expected_fname
    assert up_kwargs["thread_ts"] == "100.00"

    # 5. Approved card's payload carries archived file name
    client.chat_update.assert_called_once()
    update_kwargs = client.chat_update.call_args[1]
    # Check button value
    actions_block = next(b for b in update_kwargs["blocks"] if b.get("type") == "actions")
    btn_val = json.loads(actions_block["elements"][0]["value"])
    assert btn_val["request"]["bom_file"] == expected_fname
    # Check metadata
    if "metadata" in update_kwargs:
        assert update_kwargs["metadata"]["event_payload"]["bom_file"] == expected_fname


def test_approval_one_item_request_no_file_no_notes_no_upload(temp_workbook, temp_boms_dir, sync_queue):
    """AC 4: Approving a one-item request writes the row and produces no file, no Notes text and no upload."""
    client = MagicMock()
    say = MagicMock()
    parsed = _valid_request(total_price=50.0)
    items = [
        {"qty": 2, "name": "Coupling A", "part_number": "CP-1", "unit_price": 25.0, "link": "", "description": ""},
    ]

    lifecycle.finalize_purchase_request(
        client=client,
        say=say,
        channel="C_PURCHASING",
        thread_ts="100.00",
        event_ts="100.10",
        parsed=parsed,
        requester="Alex",
        notify_target="U_REQ",
        card_ts="100.00",
        items=items,
        shipping=0.0,
        approver="U_CHARLIE",
    )

    # Row is written
    with zipfile.ZipFile(temp_workbook) as zf:
        sheet_xml = zf.read(config.SHEET_XML).decode("utf-8")
    row_num = log_writer.find_first_empty_row(sheet_xml) - 1
    assert row_num == 17

    # No file produced in BOMs dir
    assert len(os.listdir(temp_boms_dir)) == 0

    # No Notes text
    notes_val = log_writer.get_cell_value(sheet_xml, f"{config.COLUMN_NOTES}{row_num}")
    assert notes_val is None or notes_val == ""

    # No upload
    upload_call = client.files_upload_v2 if hasattr(client, "files_upload_v2") else client.files_upload
    upload_call.assert_not_called()


def test_approval_no_items_behaves_as_today(temp_workbook, temp_boms_dir, sync_queue):
    """AC 7: Approving a request with no items behaves exactly as it does today."""
    client = MagicMock()
    say = MagicMock()
    parsed = _valid_request(total_price=150.0)

    lifecycle.finalize_purchase_request(
        client=client,
        say=say,
        channel="C_PURCHASING",
        thread_ts="100.00",
        event_ts="100.10",
        parsed=parsed,
        requester="Alex",
        notify_target="U_REQ",
        card_ts="100.00",
        items=None,
        shipping=0.0,
        approver="U_CHARLIE",
    )

    with zipfile.ZipFile(temp_workbook) as zf:
        sheet_xml = zf.read(config.SHEET_XML).decode("utf-8")
    row_num = log_writer.find_first_empty_row(sheet_xml) - 1
    assert row_num == 17

    assert len(os.listdir(temp_boms_dir)) == 0
    notes_val = log_writer.get_cell_value(sheet_xml, f"{config.COLUMN_NOTES}{row_num}")
    assert notes_val is None or notes_val == ""
    upload_call = client.files_upload_v2 if hasattr(client, "files_upload_v2") else client.files_upload
    upload_call.assert_not_called()


def test_save_bom_raises_leaves_row_blank_no_file_card_not_advanced(temp_workbook, temp_boms_dir, sync_queue, monkeypatch):
    """AC 5: A spreadsheet save that raises leaves the row blank, no file behind, and the card not advanced."""
    client = MagicMock()
    say = MagicMock()
    parsed = _valid_request(total_price=150.0)
    items = _three_items()

    def fail_save_bom(*args, **kwargs):
        raise OSError("Disk write failed simulated")

    monkeypatch.setattr(log_writer, "save_bom", fail_save_bom)

    lifecycle.finalize_purchase_request(
        client=client,
        say=say,
        channel="C_PURCHASING",
        thread_ts="100.00",
        event_ts="100.10",
        parsed=parsed,
        requester="Alex",
        notify_target="U_REQ",
        card_ts="100.00",
        items=items,
        shipping=0.0,
        approver="U_CHARLIE",
    )

    # 1. Assert row in workbook was blanked back (first empty row remains 17)
    with zipfile.ZipFile(temp_workbook) as zf:
        sheet_xml = zf.read(config.SHEET_XML).decode("utf-8")
    assert log_writer.find_first_empty_row(sheet_xml) == 17
    # Cell B17 should be empty
    assert log_writer.get_cell_value(sheet_xml, "B17") is None

    # 2. No file behind in BOMs directory
    assert len(os.listdir(temp_boms_dir)) == 0

    # 3. Card not advanced
    client.chat_update.assert_not_called()
    # Error reported to thread
    say.assert_called()
    assert "Error" in say.call_args[1]["text"] or "saving" in say.call_args[1]["text"]


def test_approval_items_mismatch_refused_no_row_no_file(temp_workbook, temp_boms_dir, sync_queue):
    """AC 6: An approval whose items no longer total request amount writes no row, creates no file, DMs requester, posts in thread."""
    client = MagicMock()
    say = MagicMock()
    # Total price is 100, but items total 150
    parsed = _valid_request(total_price=100.0)
    items = _three_items()

    lifecycle.finalize_purchase_request(
        client=client,
        say=say,
        channel="C_PURCHASING",
        thread_ts="100.00",
        event_ts="100.10",
        parsed=parsed,
        requester="Alex",
        notify_target="U_REQ",
        card_ts="100.00",
        items=items,
        shipping=0.0,
        approver="U_CHARLIE",
    )

    # 1. No row written
    with zipfile.ZipFile(temp_workbook) as zf:
        sheet_xml = zf.read(config.SHEET_XML).decode("utf-8")
    assert log_writer.find_first_empty_row(sheet_xml) == 17

    # 2. No file created
    assert len(os.listdir(temp_boms_dir)) == 0

    # 3. DMs the requester
    client.chat_postMessage.assert_any_call(
        channel="U_REQ",
        text=pytest.approx(
            client.chat_postMessage.call_args_list[0][1]["text"]
        ) if False else client.chat_postMessage.call_args[1]["text"],
    )
    dm_calls = [call for call in client.chat_postMessage.call_args_list if call[1].get("channel") == "U_REQ"]
    assert len(dm_calls) >= 1
    assert "Line items total ($150.00) does not match request total ($100.00)" in dm_calls[0][1]["text"]

    # 4. Posts in the thread
    say.assert_called_once()
    assert "Not logged" in say.call_args[1]["text"]

    # 5. Card not updated
    client.chat_update.assert_not_called()


def test_all_workbook_writes_in_ticket_go_through_queue(temp_workbook, temp_boms_dir, monkeypatch):
    """AC 9: Every workbook write in this ticket goes through the existing write queue."""
    client = MagicMock()
    say = MagicMock()
    parsed = _valid_request(total_price=150.0)
    items = _three_items()

    queue_submitted = []

    def mock_submit(action_fn, channel="", thread_ts="", user_id="", task_type="append",
                    description="", success_callback=None, failure_callback=None, client=None):
        queue_submitted.append({
            "task_type": task_type,
            "description": description,
            "action_fn": action_fn,
        })
        res = action_fn()
        if success_callback:
            success_callback(res)

    monkeypatch.setattr(queue_worker, "submit_write_task", mock_submit)

    lifecycle.finalize_purchase_request(
        client=client,
        say=say,
        channel="C_PURCHASING",
        thread_ts="100.00",
        event_ts="100.10",
        parsed=parsed,
        requester="Alex",
        notify_target="U_REQ",
        card_ts="100.00",
        items=items,
        shipping=0.0,
        approver="U_CHARLIE",
    )

    assert len(queue_submitted) == 1
    assert queue_submitted[0]["task_type"] == "append"


def test_handle_epif_processing_button_path_gets_items_from_card(temp_workbook, temp_boms_dir, sync_queue):
    """Button path gets items and shipping from card metadata via get_card_payload."""
    client = MagicMock()
    say = MagicMock()
    parsed = _valid_request(total_price=150.0)
    items = _three_items()

    card_payload = {
        "parsed": parsed,
        "requester": "Alex",
        "user_id": "U_REQ",
        "items": items,
        "shipping": 0.0,
        "thread_ts": "100.00",
        "state": "posted",
    }
    client.conversations_replies.return_value = {
        "messages": [
            {
                "ts": "100.00",
                "metadata": {
                    "event_type": "purchase_request",
                    "event_payload": card_payload,
                },
                "blocks": [],
            }
        ]
    }

    lifecycle.handle_epif_processing(
        client=client,
        say=say,
        channel="C_PURCHASING",
        thread_ts="100.00",
        approver="U_CHARLIE",
        event_ts="100.10",
        posted_payload=card_payload,
        card_ts="100.00",
    )

    # 1. BOM file exists in BOMS_DIR
    saved_files = os.listdir(temp_boms_dir)
    assert len(saved_files) == 1
    assert saved_files[0] == "0017_Ruland_BOM.xlsx"

    # 2. Notes column in workbook
    with zipfile.ZipFile(temp_workbook) as zf:
        sheet_xml = zf.read(config.SHEET_XML).decode("utf-8")
    notes_val = log_writer.get_cell_value(sheet_xml, f"{config.COLUMN_NOTES}17")
    assert notes_val == "BOM: 0017_Ruland_BOM.xlsx (3 items)"


def test_keyword_approval_modal_path_archives_bom(temp_workbook, temp_boms_dir, sync_queue):
    """Keyword path (@Purchasing approved) on modal request extracts items and archives BOM."""
    client = MagicMock()
    say = MagicMock()
    parsed = _valid_request(total_price=150.0)
    items = _three_items()

    card_payload = {
        "parsed": parsed,
        "requester": "Alex",
        "user_id": "U_REQ",
        "items": items,
        "shipping": 0.0,
        "thread_ts": "100.00",
        "state": "posted",
    }
    client.conversations_replies.return_value = {
        "messages": [
            {
                "ts": "100.00",
                "metadata": {
                    "event_type": "purchase_request",
                    "event_payload": card_payload,
                },
                "blocks": [],
            }
        ]
    }

    # Keyword path: no direct_file, no posted_payload, no card_ts
    lifecycle.handle_epif_processing(
        client=client,
        say=say,
        channel="C_PURCHASING",
        thread_ts="100.00",
        approver="U_CHARLIE",
        event_ts="100.20",
    )

    saved_files = os.listdir(temp_boms_dir)
    assert len(saved_files) == 1
    assert saved_files[0] == "0017_Ruland_BOM.xlsx"

    with zipfile.ZipFile(temp_workbook) as zf:
        sheet_xml = zf.read(config.SHEET_XML).decode("utf-8")
    notes_val = log_writer.get_cell_value(sheet_xml, f"{config.COLUMN_NOTES}17")
    assert notes_val == "BOM: 0017_Ruland_BOM.xlsx (3 items)"
