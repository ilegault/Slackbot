"""Tests for Ticket 57: A missing storage location during approval is reported and leaves no row.

Acceptance criteria:
- [ ] EPIF folder missing at approval. In tests/test_57_approval_storage_problems.py,
  on a temp copy of a real workbook fixture, drive an approval of a PDF-born request with
  EPIFS_DIR pointing at a missing folder (copy the setup of an existing approval test in
  tests/test_45_epif_approval_archives.py). Assert: one thread reply containing
  EPIFS_DIR and the path; the row that was appended is blank afterward (read the temp
  workbook); the EPIFs folder still does not exist.
- [ ] BOM folder missing at approval. A request with two or more line items and
  BOMS_DIR missing: thread reply names BOMS_DIR; row blank afterward; no BOM file
  anywhere under the temp tree.
- [ ] Workbook not set. WORKBOOK_PATH empty: the reply names PURCHASING_LOG_PATH
  and nothing is written to any temp folder.
- [ ] A non-storage error keeps its old text: force log_writer.append_row to raise
  ValueError("boom"); the reply still starts Error saving/logging purchase request.
- [ ] Only the Slack client and the file download are faked; the workbook write is real,
  on the temp copy.
"""
import json
import os
import zipfile
from datetime import date
from unittest.mock import MagicMock

import pytest

from src import config, lifecycle, log_writer, queue_worker, roster, text_rules


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


@pytest.fixture
def temp_workbook(tmp_path, monkeypatch):
    """Create a temp copy of Purchasing-Log.xlsx and set config.WORKBOOK_PATH."""
    copy_path = str(tmp_path / "Purchasing-Log.xlsx")
    create_test_workbook(copy_path)
    monkeypatch.setattr(config, "WORKBOOK_PATH", copy_path)
    return copy_path


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


def _valid_request(total_price=150.0, route="epif"):
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
        "route": route,
    }


def test_epif_folder_missing_at_approval(temp_workbook, tmp_path, sync_queue, monkeypatch):
    """EPIF folder missing at approval: reports EPIFS_DIR, row is blanked, folder not created."""
    missing_epifs_dir = str(tmp_path / "missing_epifs")
    monkeypatch.setattr(config, "EPIFS_DIR", missing_epifs_dir)

    client = MagicMock()
    say = MagicMock()
    parsed = _valid_request(total_price=150.0, route="epif")

    lifecycle.finalize_purchase_request(
        client=client,
        say=say,
        channel="C_PURCHASING",
        thread_ts="100.00",
        event_ts="101.00",
        parsed=parsed,
        requester="Alex",
        notify_target="U_REQ",
        pdf_bytes=b"%PDF-1.4 dummy epif content",
        file_name="epif_order.pdf",
    )

    # 1. Exactly one thread reply matching storage_problem_message
    assert say.call_count == 1
    reply_text = say.call_args[1]["text"]
    expected_msg = text_rules.storage_problem_message("EPIFS_DIR", missing_epifs_dir, "does not exist")
    assert reply_text == expected_msg
    assert not reply_text.startswith("Error saving/logging purchase request")
    assert say.call_args[1]["thread_ts"] == "100.00"

    # 2. The row that was appended (17) is blank afterward
    with zipfile.ZipFile(temp_workbook) as zf:
        sheet_xml = zf.read(config.SHEET_XML).decode("utf-8")
    assert log_writer.get_cell_value(sheet_xml, "I17") is None

    # 3. EPIFs folder still does not exist
    assert not os.path.exists(missing_epifs_dir)


def test_bom_folder_missing_at_approval(temp_workbook, tmp_path, sync_queue, monkeypatch):
    """BOM folder missing at approval: reports BOMS_DIR, row is blanked, no BOM in temp tree."""
    # Ensure EPIFS_DIR exists so it doesn't fail on EPIF
    epifs_dir = str(tmp_path / "epifs")
    os.makedirs(epifs_dir, exist_ok=True)
    monkeypatch.setattr(config, "EPIFS_DIR", epifs_dir)

    missing_boms_dir = str(tmp_path / "missing_boms")
    monkeypatch.setattr(config, "BOMS_DIR", missing_boms_dir)

    client = MagicMock()
    say = MagicMock()
    parsed = _valid_request(total_price=200.0, route="workday")

    items = [
        {"item": "Coupling A", "part_number": "C-1", "qty": 1, "unit_price": 100.0},
        {"item": "Coupling B", "part_number": "C-2", "qty": 1, "unit_price": 100.0},
    ]

    lifecycle.finalize_purchase_request(
        client=client,
        say=say,
        channel="C_PURCHASING",
        thread_ts="100.00",
        event_ts="101.00",
        parsed=parsed,
        requester="Alex",
        notify_target="U_REQ",
        pdf_bytes=None,
        file_name=None,
        items=items,
        shipping=0.0,
    )

    # 1. Thread reply names BOMS_DIR via storage_problem_message
    assert say.call_count == 1
    reply_text = say.call_args[1]["text"]
    expected_msg = text_rules.storage_problem_message("BOMS_DIR", missing_boms_dir, "does not exist")
    assert reply_text == expected_msg
    assert not reply_text.startswith("Error saving/logging purchase request")
    assert say.call_args[1]["thread_ts"] == "100.00"

    # 2. Row that was appended (17) is blank afterward
    with zipfile.ZipFile(temp_workbook) as zf:
        sheet_xml = zf.read(config.SHEET_XML).decode("utf-8")
    assert log_writer.get_cell_value(sheet_xml, "I17") is None

    # 3. No BOM file anywhere under the temp tree
    for root, _, files in os.walk(str(tmp_path)):
        for f in files:
            assert not f.endswith("_BOM.xlsx")
    assert not os.path.exists(missing_boms_dir)


def test_workbook_not_set_at_approval(tmp_path, sync_queue, monkeypatch):
    """WORKBOOK_PATH empty: reply names PURCHASING_LOG_PATH, nothing written."""
    monkeypatch.setattr(config, "WORKBOOK_PATH", "")

    client = MagicMock()
    say = MagicMock()
    parsed = _valid_request(total_price=150.0, route="workday")

    lifecycle.finalize_purchase_request(
        client=client,
        say=say,
        channel="C_PURCHASING",
        thread_ts="100.00",
        event_ts="101.00",
        parsed=parsed,
        requester="Alex",
        notify_target="U_REQ",
        pdf_bytes=None,
        file_name=None,
    )

    assert say.call_count == 1
    reply_text = say.call_args[1]["text"]
    expected_msg = text_rules.storage_problem_message("PURCHASING_LOG_PATH", "", "not set")
    assert reply_text == expected_msg
    assert not reply_text.startswith("Error saving/logging purchase request")
    assert say.call_args[1]["thread_ts"] == "100.00"

    # Nothing written to any temp folder
    files = list(tmp_path.iterdir())
    # Only roster.json exists
    assert all(f.name == "roster.json" for f in files)


def test_non_storage_error_keeps_old_text(temp_workbook, sync_queue, monkeypatch):
    """Non-storage error in append_row keeps 'Error saving/logging purchase request' text."""
    def _exploding_append(*args, **kwargs):
        raise ValueError("boom")

    monkeypatch.setattr(log_writer, "append_row", _exploding_append)

    client = MagicMock()
    say = MagicMock()
    parsed = _valid_request(total_price=150.0, route="workday")

    lifecycle.finalize_purchase_request(
        client=client,
        say=say,
        channel="C_PURCHASING",
        thread_ts="100.00",
        event_ts="101.00",
        parsed=parsed,
        requester="Alex",
        notify_target="U_REQ",
        pdf_bytes=None,
        file_name=None,
    )

    assert say.call_count == 1
    reply_text = say.call_args[1]["text"]
    assert reply_text.startswith("Error saving/logging purchase request")
    assert "boom" in reply_text


def test_stage_updates_handle_storage_problem(temp_workbook, sync_queue, monkeypatch):
    """Stage updates (handle_processed, handle_delivery) report storage problems via storage_problem_message."""
    # Test handle_processed when WORKBOOK_PATH does not exist
    missing_wb = temp_workbook + ".missing"
    monkeypatch.setattr(config, "WORKBOOK_PATH", missing_wb)

    client = MagicMock()
    say = MagicMock()

    lifecycle.handle_processed(
        client=client,
        say=say,
        channel="C_PURCHASING",
        thread_ts="100.00",
        user_id="U_BUYER",
        event_ts="101.00",
        text="Row 12",
        card_ts="100.00",
        req_data={},
        history=[],
    )

    assert say.call_count == 1
    reply_text = say.call_args[1]["text"]
    expected_msg = text_rules.storage_problem_message("PURCHASING_LOG_PATH", missing_wb, "does not exist")
    assert reply_text == expected_msg

    # Test handle_delivery when WORKBOOK_PATH does not exist
    say.reset_mock()
    lifecycle.handle_delivery(
        client=client,
        say=say,
        channel="C_PURCHASING",
        thread_ts="100.00",
        user_id="U_BUYER",
        event_ts="101.00",
        text="Row 12",
        card_ts="100.00",
        req_data={},
        history=[],
    )

    assert say.call_count == 1
    reply_text = say.call_args[1]["text"]
    assert reply_text == expected_msg
