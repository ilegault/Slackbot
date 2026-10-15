"""Tests for Ticket 124: the Filled EPIF is dated at approval; the interview stops asking for a date.

Acceptance criteria:
- [ ] test_no_modal_asks_for_a_date: Screen 2 (new + edit) and Workday-details carry no date block.
- [ ] test_filled_epif_is_dated_the_approval_day: posted D1, approved D2 -> archived PDF says D2,
      workbook column M says D1; an uploaded EPIF dated 09/01/2026 logs M as 09/01/2026 and is
      archived unchanged.
"""
import datetime
import json
import os
import zipfile
from unittest.mock import MagicMock

import pytest

from src import blocks, config, epif_filler, epif_parser, interview, lifecycle, log_writer, queue_worker, roster
from tests.test_45_epif_approval_archives import create_test_workbook

FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")
TEMPLATE = os.path.join(FIXTURES, "EPIF_TEMPLATE_HIRST.pdf")

D1 = datetime.date(2026, 9, 22)
D2 = datetime.date(2026, 10, 6)


@pytest.fixture(autouse=True)
def isolated_roster(tmp_path, monkeypatch):
    roster_file = str(tmp_path / "roster.json")
    monkeypatch.setattr(roster, "ROSTER_PATH", roster_file)
    roster._DATA = None
    with open(roster_file, "w", encoding="utf-8") as f:
        json.dump({"admins": ["U_ADMIN"], "approvers": ["U_CHARLIE"], "buyers": ["U_BUYER"],
                   "requesters": {"U_REQ": "Alex", "U_BUYER": "Dylan"}, "vendors": []}, f)


@pytest.fixture
def workbook_and_epifs(tmp_path, monkeypatch):
    wb = str(tmp_path / "Purchasing-Log.xlsx")
    create_test_workbook(wb)
    epifs = str(tmp_path / "EPIFs")
    os.makedirs(epifs)
    monkeypatch.setattr(config, "WORKBOOK_PATH", wb)
    monkeypatch.setattr(config, "EPIFS_DIR", epifs)
    monkeypatch.setattr(config, "EPIF_TEMPLATE_PATH", TEMPLATE)

    def _sync(action_fn, channel="", thread_ts="", user_id="", task_type="append",
              description="", success_callback=None, failure_callback=None, client=None):
        try:
            res = action_fn()
            if success_callback:
                success_callback(res)
        except Exception as exc:
            if failure_callback:
                failure_callback(exc)

    monkeypatch.setattr(queue_worker, "submit_write_task", _sync)
    return wb, epifs


def _block_ids(view):
    return [b.get("block_id") for b in view["blocks"]]


def test_no_modal_asks_for_a_date():
    """Neither Screen 2 (new request or Edit) nor the Workday-details modal renders a date picker."""
    base = {"route": "epif", "vendor_choice": "Acme", "vendor_custom": "", "resolved_name": "Alex"}
    new_view = blocks.build_stage2_view(dict(base))
    edit_view = blocks.build_stage2_view({**base, "is_edit": True, "channel": "C1", "thread_ts": "1.0",
                                          "card_ts": "1.1", "date_of_purchase": "2026-09-22"})
    workday_view = blocks.build_workday_details_view("C1", "1.0", "1.1", ["Fisher Scientific"])

    for view in (new_view, edit_view, workday_view):
        assert "block_date_of_purchase" not in _block_ids(view)
        assert not [b for b in view["blocks"] if b.get("element", {}).get("type") == "datepicker"]


def _stages():
    stage1 = {"vendor_choice": config.VENDOR_OTHER_OPTION, "vendor_custom": "Ruland", "route": "epif"}
    stage2 = {
        "item_description": "Shaft Couplings",
        "purpose": "Motor test stand alignment",
        "total_price": "150.00",
        "vendor_contact_name": "Sales",
        "vendor_contact_email": "sales@ruland.com",
        "delivery_room": "ERB 212",
        "project_id": "PG000025831",
        "fund": "133",
        "category": "Research/Lab Supplies (3105)",
        "payment_method": "P-card",
    }
    return stage1, stage2


def test_filled_epif_is_dated_the_approval_day(workbook_and_epifs, monkeypatch):
    wb, epifs = workbook_and_epifs

    rows = []
    real_append = log_writer.append_row

    def spy(row):
        rows.append(dict(row))
        return real_append(row)

    monkeypatch.setattr(log_writer, "append_row", spy)

    # Posted on D1 (the one date helper is pinned) ...
    monkeypatch.setattr(interview, "today", lambda: D1)
    parsed = interview.build_parsed_from_stages(*_stages()[:2], None)

    # ... approved on D2.
    monkeypatch.setattr(interview, "today", lambda: D2)
    lifecycle.finalize_purchase_request(
        client=MagicMock(), say=MagicMock(), channel="C_PURCHASING", thread_ts="100.00",
        event_ts="101.00", parsed=parsed, requester="Alex", notify_target="U_REQ",
        pdf_bytes=None, file_name=None,
    )

    files = os.listdir(epifs)
    assert len(files) == 1
    with open(os.path.join(epifs, files[0]), "rb") as f:
        archived = epif_parser.parse_epif(f.read())
    assert archived["date_of_purchase"] == D2
    assert rows[0][config.COLUMN_DATE_OF_REQUEST] == D1

    # An uploaded EPIF dated 09/01/2026 logs as that day and is archived unchanged.
    uploaded_parsed = {**parsed, "date_of_purchase": datetime.date(2026, 9, 1), "request_date": None,
                       "vendor": "Uploaded Co"}
    with open(TEMPLATE, "rb") as f:
        uploaded_bytes = epif_filler.fill_epif(f.read(), uploaded_parsed)
    assert epif_parser.parse_epif(uploaded_bytes)["date_of_purchase"] == datetime.date(2026, 9, 1)

    lifecycle.finalize_purchase_request(
        client=MagicMock(), say=MagicMock(), channel="C_PURCHASING", thread_ts="200.00",
        event_ts="201.00", parsed=epif_parser.parse_epif(uploaded_bytes), requester="Alex",
        notify_target="U_REQ", pdf_bytes=uploaded_bytes, file_name="upload.pdf",
    )
    assert rows[1][config.COLUMN_DATE_OF_REQUEST] == datetime.date(2026, 9, 1)
    newest = max((os.path.join(epifs, n) for n in os.listdir(epifs) if "Uploaded" in n), key=os.path.getmtime)
    with open(newest, "rb") as f:
        assert f.read() == uploaded_bytes

    with zipfile.ZipFile(wb) as zf:
        assert zf.read(config.SHEET_XML)  # workbook still readable
