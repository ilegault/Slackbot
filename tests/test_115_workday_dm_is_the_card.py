"""Tests for Ticket 115 (ADR 0018 decision 3): on the Workday path the DM card is the whole DM.

Acceptance criteria:
- A Workday-path approval sends the buyer exactly one chat_postMessage: the DM card.
  No "Place this in Workday:" text message.
- An EPIF-path approval sends the draft message, then the DM card, in that order.
- handle_assign on an approved Workday-path card sends one card-only DM with the Assigned to line.
- With no card_ts the Workday DM falls back to one plain-text message and logs a warning.
"""
import json
import logging
import os
import zipfile
from datetime import date
from unittest.mock import MagicMock, patch

import pytest

from src import config, lifecycle, queue_worker, roster


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


def _parsed(payment_method):
    return {
        "item_description": "Shaft Couplings",
        "purpose": "Motor test stand alignment",
        "total_price": 150.0,
        "vendor": "Ruland",
        "vendor_contact_name": "Sales",
        "vendor_contact_email": "sales@ruland.com",
        "date_of_purchase": date(2026, 9, 22),
        "project_id": "PG000025831",
        "fund": "133",
        "category": "Research/Lab Supplies (3105)",
        "payment_method": payment_method,
        "delivery_room": "ERB 212",
        "pi_of_funding": "Charlie Hirst",
        "end_user": "Alex",
        "name_of_system": "",
        "asset_id": "",
        "link": "https://ruland.example/coupling",
    }


def _approve(client, payment_method, monkeypatch):
    monkeypatch.setattr(config, "EPIF_TEMPLATE_PATH", os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "fixtures", "EPIF_TEMPLATE_HIRST.pdf"))
    lifecycle.finalize_purchase_request(
        client=client,
        say=MagicMock(),
        channel="C_PURCHASING",
        thread_ts="100.00",
        event_ts="101.00",
        parsed=_parsed(payment_method),
        requester="Alex",
        notify_target="U_REQ",
        approver="U_CHARLIE",
        assignee_id="U_BUYER",
        assignee_name="Dylan",
        card_ts="100.50",
    )


def _buyer_calls(client):
    return [c for c in client.chat_postMessage.call_args_list if c[1].get("channel") == "U_BUYER"]


def test_workday_approval_sends_one_dm_card_and_no_plain_text(temp_workbook, sync_queue, monkeypatch, caplog):
    client = MagicMock()
    _approve(client, "Workday", monkeypatch)

    calls = _buyer_calls(client)
    assert len(calls) == 1
    kwargs = calls[0][1]
    assert kwargs.get("blocks")
    section = kwargs["blocks"][0]["text"]["text"]
    assert section.startswith("🛒 *Place this in Workday*")
    assert "• *Total:*" in section
    assert "• *Row:*" in section
    ctx = next(b for b in kwargs["blocks"] if b["type"] == "context")["elements"][0]["text"]
    assert "Approved by" in ctx
    assert "Assigned to" in ctx
    assert not any(str(c[1].get("text", "")).startswith("Place this in Workday:") for c in calls)

    # No card_ts: one plain-text DM with the request lines, and a warning.
    client2 = MagicMock()
    with caplog.at_level(logging.WARNING, logger=lifecycle.log.name):
        ref = lifecycle._send_assignee_dm(
            client=client2,
            assignee_id="U_BUYER",
            assignee_name="Dylan",
            email_draft="draft",
            item_desc="Shaft Couplings",
            row=17,
            route="workday",
            parsed=_parsed("Workday"),
            thread_channel="C_PURCHASING",
            thread_ts="100.00",
            card_ts=None,
            state="approved",
        )
    assert ref is None
    texts = [c[1] for c in client2.chat_postMessage.call_args_list if c[1].get("channel") == "U_BUYER"]
    assert len(texts) == 1
    assert not texts[0].get("blocks")
    assert "• *Item:* Shaft Couplings" in texts[0]["text"]
    assert any("No card_ts; sent the Workday DM as text to U_BUYER" in r.getMessage() for r in caplog.records)


def test_epif_approval_sends_the_draft_then_the_card(temp_workbook, sync_queue, monkeypatch):
    client = MagicMock()
    _approve(client, "P-card", monkeypatch)

    calls = _buyer_calls(client)
    draft_idx = [i for i, c in enumerate(calls) if "Send this email to purchasing" in str(c[1].get("text", ""))]
    card_idx = [
        i for i, c in enumerate(calls)
        if c[1].get("blocks") and c[1]["blocks"][0]["text"]["text"].startswith("📧 *Email the EPIF to purchasing*")
    ]
    assert len(draft_idx) == 1
    assert len(card_idx) == 1
    assert draft_idx[0] < card_idx[0]


def test_assigning_a_workday_card_sends_one_card_only_dm():
    client = MagicMock()
    card_req = {
        "row": 20,
        "item_description": "Lens",
        "vendor": "Thorlabs",
        "vendor_contact_email": "sales@thorlabs.com",
        "total_price": 50.0,
        "payment_method": "Workday",
    }
    history = ["Posted on 09/16"]
    with patch.object(lifecycle.slack_io, "find_card_in_thread",
                      return_value=(card_req, "100.1", history, "approved")):
        ok = lifecycle.handle_assign(
            client=client, say=MagicMock(), channel="C1", thread_ts="100.0",
            user_id="U_BUYER", event_ts="100.2", target_user_id=None,
        )
    assert ok is True
    calls = _buyer_calls(client)
    assert len(calls) == 1
    blocks_ = calls[0][1]["blocks"]
    assert blocks_[0]["text"]["text"].startswith("🛒 *Place this in Workday*")
    ctx = next(b for b in blocks_ if b["type"] == "context")["elements"][0]["text"]
    assert "Assigned to" in ctx
