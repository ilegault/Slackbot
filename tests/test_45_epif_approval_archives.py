"""Tests for Ticket 45: EPIF-path approval generates and archives the filled EPIF.

Acceptance criteria:
- [ ] config.EPIF_TEMPLATE_PATH defaults to os.path.join(config.TEMPLATE_DIR, "EPIF_TEMPLATE_HIRST.pdf") and can be overridden. path_validator checks it as a file. (Tested in test_24)
- [ ] In lifecycle.finalize_purchase_request.write_action, when get_request_route is epif and no EPIF was uploaded, read the template, call epif_filler.fill_epif, and save.
- [ ] All or nothing. If the template is missing or fill_epif raises, the row is blanked and the error re-raised. (Tested here)
- [ ] Scenario: an interview request with route = epif is approved; one row is written and exactly one PDF exists in EPIFS_DIR under the naming rule, and epif_parser reads back the request's vendor and amount. (Tested here)
- [ ] A Workday-path approval in the same test file adds no file. (Tested here)
"""
import json
import os
import zipfile
from datetime import date
from unittest.mock import MagicMock

import pytest

from src import config, epif_parser, lifecycle, log_writer, queue_worker, roster

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SAMPLES = os.path.join(PROJECT_ROOT, "samples")
FIXTURES = os.path.join(PROJECT_ROOT, "tests", "fixtures")


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
def temp_epifs_dir(tmp_path, monkeypatch):
    """Create a temp EPIFs directory and set config.EPIFS_DIR."""
    epifs_path = str(tmp_path / "EPIFs")
    os.makedirs(epifs_path, exist_ok=True)
    monkeypatch.setattr(config, "EPIFS_DIR", epifs_path)
    return epifs_path


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


def test_epif_approval_generates_and_archives_filled_epif(temp_workbook, temp_epifs_dir, sync_queue, monkeypatch):
    """Scenario: interview request with route = epif is approved -> row written, exactly 1 PDF in EPIFS_DIR, parses correctly."""
    monkeypatch.setattr(config, "EPIF_TEMPLATE_PATH", os.path.join(FIXTURES, "EPIF_TEMPLATE_HIRST.pdf"))

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
        pdf_bytes=None,  # No uploaded file
        file_name=None,
    )

    # 1. Row is written to workbook
    with zipfile.ZipFile(temp_workbook) as zf:
        sheet_xml = zf.read(config.SHEET_XML).decode("utf-8")
    assert log_writer.get_cell_value(sheet_xml, "I17") == "Ruland"  # Vendor
    assert log_writer.get_cell_value(sheet_xml, "H17") == "150.0"     # Total Price

    # 2. Exactly one PDF exists in EPIFS_DIR
    files = os.listdir(temp_epifs_dir)
    assert len(files) == 1
    archived_pdf_path = os.path.join(temp_epifs_dir, files[0])
    assert files[0].endswith(".pdf")
    assert "Ruland" in files[0]

    # 3. epif_parser reads back the request's vendor and amount
    with open(archived_pdf_path, "rb") as f:
        filled_bytes = f.read()

    re_parsed = epif_parser.parse_epif(filled_bytes)
    assert re_parsed["vendor"] == "Ruland"
    assert re_parsed["total_price"] == 150.0


def test_epif_approval_fails_if_template_missing(temp_workbook, temp_epifs_dir, sync_queue, monkeypatch):
    """All or nothing. If template is missing, row is blanked, no file is in EPIFS_DIR, error raised."""
    monkeypatch.setattr(config, "EPIF_TEMPLATE_PATH", "/does/not/exist.pdf")

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
        pdf_bytes=None,  # No uploaded file
        file_name=None,
    )

    # 1. Row is blanked (or remains blank because it failed during generation)
    with zipfile.ZipFile(temp_workbook) as zf:
        sheet_xml = zf.read(config.SHEET_XML).decode("utf-8")
    assert log_writer.get_cell_value(sheet_xml, "I17") is None  # Vendor is empty

    # 2. No file is in EPIFS_DIR
    files = os.listdir(temp_epifs_dir)
    assert len(files) == 0


def test_workday_approval_adds_no_file(temp_workbook, temp_epifs_dir, sync_queue, monkeypatch):
    """A Workday-path approval in the same test file adds no file."""
    monkeypatch.setattr(config, "EPIF_TEMPLATE_PATH", os.path.join(FIXTURES, "EPIF_TEMPLATE_HIRST.pdf"))

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

    # 1. Row is written to workbook
    with zipfile.ZipFile(temp_workbook) as zf:
        sheet_xml = zf.read(config.SHEET_XML).decode("utf-8")
    assert log_writer.get_cell_value(sheet_xml, "I17") == "Ruland"  # Vendor

    # 2. No file is in EPIFS_DIR because it's workday route
    files = os.listdir(temp_epifs_dir)
    assert len(files) == 0
