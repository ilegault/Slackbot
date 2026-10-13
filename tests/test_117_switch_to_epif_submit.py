"""Tests for Ticket 117 (ADR 0018, ADR 0007 decisions 5-7): submitting the Switch to EPIF form.

Acceptance criteria:
- [ ] Switching an approved Workday row rewrites the SAME row (row number, row count and the
      requester cell unchanged; payment method and vendor updated) and archives exactly one
      filled EPIF that epif_parser reads back.
- [ ] The thread says "Switched to EPIF by", the card's payload reads as the EPIF path, and the
      assigned buyer gets the "Send this email to purchasing" DM plus an upload naming the PDF.
- [ ] If the row was processed between the click and the write, nothing is written or archived,
      the card is not updated, and the submitter is DM'd "Already processed".
- [ ] A missing template changes nothing: the sheet is byte-identical, no PDF, no card update.

Real: log_writer on a temp workbook, epif_filler on the fixture template, epif_parser,
interview.build_parsed_from_stages, validators.validate, blocks. Fake: the Slack client and
the lock queue (run synchronously).
"""
import json
import os
import zipfile
from datetime import date
from unittest.mock import MagicMock

import pytest

from src import blocks, config, epif_parser, interview, lifecycle, log_writer, queue_worker, roster

CHANNEL = "C_PURCHASING"
THREAD = "100.00"
CARD_TS = "101.00"
FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")


@pytest.fixture(autouse=True)
def clean_roster(tmp_path, monkeypatch):
    roster_file = str(tmp_path / "roster.json")
    monkeypatch.setattr(roster, "ROSTER_PATH", roster_file)
    roster._DATA = None
    data = {
        "admins": ["U_ADMIN"],
        "approvers": ["U_CHARLIE"],
        "buyers": ["U_BUYER"],
        "requesters": {"U_ADMIN": "Isaac", "U_CHARLIE": "Charlie H.", "U_BUYER": "Dylan", "U_REQ": "Alex"},
        "vendors": [],
    }
    with open(roster_file, "w", encoding="utf-8") as f:
        json.dump(data, f)
    return roster_file


@pytest.fixture
def temp_workbook(tmp_path, monkeypatch):
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
        rows_xml.append(f'<row r="{r}">' + "".join(f'<c r="{col}{r}" s="46"/>' for col in cols) + "</row>")
    sheet1_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:x14="http://schemas.microsoft.com/office/spreadsheetml/2009/9/main">\n'
        "<sheetData>" + "".join(rows_xml) + "</sheetData>\n</worksheet>"
    )
    path = str(tmp_path / "Purchasing-Log.xlsx")
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(config.SHEET_XML, sheet1_xml)
    monkeypatch.setattr(config, "WORKBOOK_PATH", path)
    epifs = tmp_path / "EPIFs"
    epifs.mkdir()
    monkeypatch.setattr(config, "EPIFS_DIR", str(epifs))
    monkeypatch.setattr(config, "EPIF_TEMPLATE_PATH", os.path.join(FIXTURES, "EPIF_TEMPLATE_HIRST.pdf"))
    return path


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


def _workday_parsed():
    return {
        "item_description": "Optical post",
        "purpose": "Alignment",
        "total_price": 80.0,
        "vendor": "Winford",
        "vendor_contact_name": "",
        "vendor_contact_email": "",
        "date_of_purchase": date(2026, 9, 22),
        "project_id": "PG000025831",
        "fund": "133",
        "category": "Research/Lab Supplies (3105)",
        "payment_method": "Workday",
        "delivery_room": "ERB 212",
        "name_of_system": "",
        "asset_id": "",
        "link": "",
    }


def _approved_row_and_card(client):
    """Append an approved Workday row and make the fake thread hold its approved card."""
    parsed = _workday_parsed()
    row = log_writer.append_row(log_writer.build_row(parsed, "Alex"))
    req = {
        "parsed": {**parsed, "date_of_purchase": parsed["date_of_purchase"].isoformat()},
        "requester": "Alex",
        "user_id": "U_REQ",
        "approver": "U_CHARLIE",
        "assignee_id": "U_BUYER",
        "assignee": "Dylan",
        "state": "approved",
        "thread_ts": THREAD,
    }
    card_blocks = blocks.build_request_blocks("approved", req, history=["Approved by Charlie H. on 09/22/26 10:00"])
    client.conversations_replies.return_value = {
        "messages": [{
            "ts": CARD_TS,
            "blocks": card_blocks,
            "metadata": {"event_type": "purchase_request", "event_payload": req},
        }]
    }
    return row


def _client():
    client = MagicMock()
    client.chat_postMessage.return_value = {"channel": "D_BUYER", "ts": "900.1"}
    client.chat_getPermalink.return_value = {"permalink": "https://example.invalid/p/1"}
    client.conversations_open.return_value = {"channel": {"id": "D_BUYER"}}
    return client


def _submit(client, row):
    meta = {
        "route": "epif",
        "vendor_choice": config.VENDOR_OTHER_OPTION,
        "vendor_custom": "Ruland",
        "resolved_name": "Alex",
        "user_id": "U_REQ",
        "switch": {
            "channel": CHANNEL, "thread_ts": THREAD, "card_ts": CARD_TS, "row": row,
            "approver": "U_CHARLIE", "assignee_id": "U_BUYER", "assignee_name": "Dylan",
        },
    }
    stage2 = {
        "item_description": "Shaft Couplings",
        "purpose": "Motor test stand alignment",
        "total_price": "150.00",
        "vendor_contact_name": "Sales",
        "vendor_contact_email": "sales@ruland.com",
        "date_of_purchase": "2026-09-22",
        "delivery_room": "ERB 212",
        "project_id": "PG000025831",
        "fund": "133",
        "category": "Research/Lab Supplies (3105)",
        "payment_method": "P-card",
        "link": "https://ruland.example/coupling",
    }
    ack = MagicMock()
    body = {"user": {"id": "U_BUYER"}}
    lifecycle._process_interview_completion(ack, client, body, meta, stage2, None)
    return ack


def _sheet(path):
    with zipfile.ZipFile(path) as zf:
        return zf.read(config.SHEET_XML).decode("utf-8")


def _texts(client, channel=None):
    out = []
    for c in client.chat_postMessage.call_args_list:
        if channel is None or c.kwargs.get("channel") == channel:
            out.append(c.kwargs.get("text") or "")
    return out


def test_switching_an_approved_workday_row_to_epif(temp_workbook, sync_queue):
    client = _client()
    row = _approved_row_and_card(client)
    before = _sheet(temp_workbook)
    first_empty_before = log_writer.find_first_empty_row(before)
    requester_before = log_writer.get_cell_value(before, f"B{row}")

    _submit(client, row)

    after = _sheet(temp_workbook)
    assert log_writer.find_first_empty_row(after) == first_empty_before
    assert log_writer.get_cell_value(after, f"B{row}") == requester_before == "Alex"
    assert log_writer.get_cell_value(after, f"{config.COLUMN_HOW_BUYING}{row}") == "P-card"
    assert log_writer.get_cell_value(after, f"I{row}") == "Ruland"

    pdfs = os.listdir(config.EPIFS_DIR)
    assert len(pdfs) == 1 and pdfs[0].endswith(".pdf")
    with open(os.path.join(config.EPIFS_DIR, pdfs[0]), "rb") as f:
        reparsed = epif_parser.parse_epif(f.read())
    assert reparsed["vendor"] == "Ruland"
    assert reparsed["total_price"] == 150.0

    assert any("🔁 Switched to EPIF by" in t for t in _texts(client, CHANNEL))
    updates = [c for c in client.chat_update.call_args_list if c.kwargs.get("channel") == CHANNEL]
    assert updates, "the thread card was not updated"
    payload = updates[-1].kwargs["metadata"]["event_payload"]
    assert payload["parsed"]["payment_method"] == "P-card"
    assert interview.get_request_route(payload) == "epif"
    assert payload["epif_file"] == pdfs[0]

    assert any("Send this email to purchasing" in t for t in _texts(client, "U_BUYER"))
    uploads = client.files_upload_v2.call_args_list
    assert any(c.kwargs.get("filename") == pdfs[0] for c in uploads)


def test_switch_is_refused_when_the_row_was_processed_meanwhile(temp_workbook, sync_queue):
    client = _client()
    row = _approved_row_and_card(client)
    log_writer.update_row(row, {config.COLUMN_DATE_PROCESSED: date(2026, 9, 25)})
    before = _sheet(temp_workbook)

    _submit(client, row)

    assert _sheet(temp_workbook) == before
    assert os.listdir(config.EPIFS_DIR) == []
    client.chat_update.assert_not_called()
    assert not any("🔁" in t for t in _texts(client))
    assert any("Already processed" in t for t in _texts(client, "U_BUYER"))


def test_switch_with_a_missing_template_changes_nothing(temp_workbook, sync_queue, monkeypatch):
    client = _client()
    row = _approved_row_and_card(client)
    before = _sheet(temp_workbook)
    monkeypatch.setattr(config, "EPIF_TEMPLATE_PATH", "/does/not/exist.pdf")

    _submit(client, row)

    assert _sheet(temp_workbook) == before
    assert os.listdir(config.EPIFS_DIR) == []
    client.chat_update.assert_not_called()
    assert not any("🔁" in t for t in _texts(client))
    assert any("couldn't switch" in t.lower() for t in _texts(client, CHANNEL))


def test_switch_restores_the_row_when_the_epif_cannot_be_archived(temp_workbook, sync_queue, monkeypatch, tmp_path):
    """EPIFS_DIR missing -> save_epif raises after the row was rewritten -> the row goes back exactly."""
    client = _client()
    row = _approved_row_and_card(client)
    before = _sheet(temp_workbook)
    monkeypatch.setattr(config, "EPIFS_DIR", str(tmp_path / "gone"))

    _submit(client, row)

    assert _sheet(temp_workbook) == before
    client.chat_update.assert_not_called()
    assert not any("🔁" in t for t in _texts(client))
    assert any("EPIFS_DIR" in t for t in _texts(client, CHANNEL))
