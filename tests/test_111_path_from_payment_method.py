"""Tests for Ticket 111: the path is read from the payment method (ADR 0018 decision 1).

Acceptance criteria:
- [ ] get_request_route reads only the payment method (plus has_file); a stale `route` key is ignored.
- [ ] End to end from the real interview: an EPIF-path request gets a filled EPIF, the thread says
      "to email to purchasing", the buyer's DM says "Send this email to purchasing" and the PDF is uploaded.
      A Workday-path request in the same test adds no file and says "to place in Workday".
- [ ] Late assignment of an approved EPIF-path request sends the same EPIF DM.

WHY THE END-TO-END TEST STARTS AT THE INTERVIEW:
Screen 1's path used to live only in modal metadata and was never written onto the posted card, so
approval fell back to Workday. Every earlier test built the request by hand with a `route` key the
interview never wrote. Starting from `_process_interview_completion` and taking the Approve button's
value off the posted card exercises exactly the gap between posting and approval.
"""
import copy
import json
import os
import zipfile
from unittest.mock import MagicMock

import pytest

from src import config, epif_parser, interview, lifecycle, queue_worker, roster, slack_io

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIXTURES = os.path.join(PROJECT_ROOT, "tests", "fixtures")

CHANNEL = "C_PURCHASING"


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
        "vendors": ["Grainger"],
    }
    with open(roster_file, "w", encoding="utf-8") as f:
        json.dump(data, f)
    roster.load_roster()
    return roster_file


def _create_test_workbook(dest_path: str) -> str:
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
    copy_path = str(tmp_path / "Purchasing-Log.xlsx")
    _create_test_workbook(copy_path)
    monkeypatch.setattr(config, "WORKBOOK_PATH", copy_path)
    return copy_path


@pytest.fixture
def epifs_dir(tmp_path, monkeypatch):
    path = str(tmp_path / "EPIFs")
    os.makedirs(path, exist_ok=True)
    monkeypatch.setattr(config, "EPIFS_DIR", path)
    monkeypatch.setattr(config, "EPIF_TEMPLATE_PATH", os.path.join(FIXTURES, "EPIF_TEMPLATE_HIRST.pdf"))
    monkeypatch.setattr(config, "PURCHASING_CHANNEL", CHANNEL)
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
    return _sync_submit


class FakeSlack:
    """A MagicMock client whose channel remembers what was posted and updated."""

    def __init__(self):
        self.messages = []
        self.client = MagicMock()
        self.client.chat_postMessage.side_effect = self._post
        self.client.chat_update.side_effect = self._update
        self.client.conversations_replies.side_effect = lambda **kw: {"messages": copy.deepcopy(self.messages)}
        self.client.conversations_open.return_value = {"channel": {"id": "D_BUYER"}}

    def _post(self, **kwargs):
        msg = dict(kwargs)
        msg["ts"] = "1000.2000" if not self.messages else f"1000.{2000 + len(self.messages)}"
        self.messages.append(msg)
        return msg

    def _update(self, **kwargs):
        for msg in self.messages:
            if msg["ts"] == kwargs["ts"]:
                msg.update(kwargs)
        return {"ok": True}

    def say(self, text=None, thread_ts=None, **kwargs):
        return self.client.chat_postMessage(channel=CHANNEL, text=text, thread_ts=thread_ts, **kwargs)

    @property
    def card(self):
        return self.messages[0]

    def thread_texts(self, after=0):
        return [m.get("text") or "" for m in self.messages[after:] if m.get("channel") == CHANNEL and m.get("thread_ts")]

    def dm_texts(self, user_id="U_BUYER"):
        return [c[1].get("text") or "" for c in self.client.chat_postMessage.call_args_list
                if c[1].get("channel") == user_id]


def _stage2(payment_method, vendor_contact=True):
    return {
        "item_description": "Shaft Couplings",
        "purpose": "Motor test stand alignment",
        "link": "https://ruland.example/couplings",
        "total_price": "150.00",
        "vendor_contact_name": "Sales" if vendor_contact else "",
        "vendor_contact_email": "sales@ruland.example" if vendor_contact else "",
        "date_of_purchase": "2026-09-22",
        "project_id": "PG000025831",
        "fund": "133",
        "category": "Research/Lab Supplies (3105)",
        "delivery_room": "ERB 212",
        "payment_method": payment_method,
    }


def _approve_button(msg):
    for b in msg["blocks"]:
        if b.get("type") == "actions":
            for el in b["elements"]:
                if el.get("action_id") == "req_approve":
                    return el
    raise AssertionError("posted card has no Approve button")


def _post_from_interview(fake, vendor_choice, vendor_custom, payment_method):
    """Run Screen 1's route decision and Screen 2's answers through the real interview."""
    meta = {
        "vendor_choice": vendor_choice,
        "vendor_custom": vendor_custom,
        "route": interview.route_vendor(vendor_choice),
        "resolved_name": "Alex",
        "user_id": "U_REQ",
        "is_pending_name": False,
    }
    ack = MagicMock()
    lifecycle._process_interview_completion(
        ack, fake.client, {"user": {"id": "U_REQ"}}, meta, _stage2(payment_method)
    )
    ack.assert_called_once_with()
    return json.loads(_approve_button(fake.card)["value"])


def _approve(fake, button_value, assignee=True):
    request = dict(button_value["request"])
    if assignee:
        request["assignee_id"] = "U_BUYER"
        request["assignee"] = "Dylan"
    lifecycle.handle_epif_processing(
        client=fake.client, say=fake.say, channel=CHANNEL, thread_ts=fake.card["ts"],
        approver="U_CHARLIE", event_ts="E1",
        posted_payload=request, card_ts=fake.card["ts"],
    )


@pytest.fixture(autouse=True)
def stub_slack_lookups(monkeypatch):
    names = {"U_REQ": "Alex", "U_BUYER": "Dylan", "U_CHARLIE": "Charlie H.", "U_ADMIN": "Isaac"}
    monkeypatch.setattr(slack_io, "resolve_requester", MagicMock(side_effect=lambda c, u: names.get(u)))


def test_route_is_read_from_the_payment_method():
    """One table, one function: the payment method is the whole record of the path."""
    cases = [
        ({"payment_method": "Workday"}, False, "workday"),
        ({"payment_method": "P-card"}, False, "epif"),
        ({"payment_method": "Req/PO"}, False, "epif"),
        ({"payment_method": None}, False, "epif"),
        ({}, False, "epif"),
        ({"parsed": {"payment_method": "Workday"}}, False, "workday"),
        ({"parsed": {"payment_method": "P-card"}}, False, "epif"),
        ({"parsed": {"payment_method": "Req/PO"}}, False, "epif"),
        ({"parsed": {"payment_method": None}}, False, "epif"),
        ({"payment_method": "Workday"}, True, "epif"),
        # a stale `route` key is ignored in both directions
        ({"route": "epif", "payment_method": "Workday"}, False, "workday"),
        ({"route": "workday", "payment_method": "P-card"}, False, "epif"),
        # `source == "epif"` no longer decides anything either
        ({"source": "epif", "payment_method": "Workday"}, False, "workday"),
    ]
    got = [(payload, has_file, interview.get_request_route(payload, has_file)) for payload, has_file, _ in cases]
    assert got == [(p, f, expected) for p, f, expected in cases]


def test_epif_request_from_the_interview_gets_a_filled_epif_and_a_buyer_email(
    temp_workbook, epifs_dir, sync_queue, tmp_path, monkeypatch
):
    # --- EPIF path: "None of these" + P-card ---
    fake = FakeSlack()
    button = _post_from_interview(fake, config.VENDOR_OTHER_OPTION, "Ruland", "P-card")
    _approve(fake, button)

    pdfs = os.listdir(epifs_dir)
    assert len(pdfs) == 1 and pdfs[0].endswith(".pdf")
    with open(os.path.join(epifs_dir, pdfs[0]), "rb") as fh:
        reparsed = epif_parser.parse_epif(fh.read())
    assert reparsed["vendor"] == "Ruland"
    assert reparsed["total_price"] == 150.0

    assert any("to email to purchasing" in t for t in fake.thread_texts()), fake.thread_texts()
    dms = fake.dm_texts()
    assert any("Send this email to purchasing" in t for t in dms), dms
    assert not any("Submit via Workday" in t for t in dms), dms
    uploads = fake.client.files_upload_v2.call_args_list
    assert [c[1]["filename"] for c in uploads] == [pdfs[0]]

    # --- Workday path: a listed vendor, Screen 1 route workday ---
    workday_epifs = str(tmp_path / "EPIFs_workday")
    os.makedirs(workday_epifs)
    monkeypatch.setattr(config, "EPIFS_DIR", workday_epifs)
    listed_vendor = sorted(interview.get_available_vendors())[0]
    assert listed_vendor == "Grainger"
    fake2 = FakeSlack()
    button2 = _post_from_interview(fake2, listed_vendor, "", config.WORKDAY_PAYMENT_METHOD)
    _approve(fake2, button2)

    assert os.listdir(workday_epifs) == []
    assert any("to place in Workday" in t for t in fake2.thread_texts()), fake2.thread_texts()
    fake2.client.files_upload_v2.assert_not_called()


def test_late_assigned_buyer_gets_the_epif_email(temp_workbook, epifs_dir, sync_queue):
    fake = FakeSlack()
    button = _post_from_interview(fake, config.VENDOR_OTHER_OPTION, "Ruland", "P-card")
    _approve(fake, button, assignee=False)
    assert len(os.listdir(epifs_dir)) == 1
    fake.client.files_upload_v2.assert_not_called()

    approved = copy.deepcopy(fake.card["metadata"]["event_payload"])
    assert approved.get("epif_file"), "approval must record the archived EPIF on the card"
    seen = len(fake.messages)
    fake.client.files_upload_v2.reset_mock()

    ok = lifecycle.handle_assign(
        fake.client, fake.say, CHANNEL, fake.card["ts"], "U_BUYER", "E2",
        target_user_id="U_BUYER", req_data=approved, msg_ts=fake.card["ts"],
        history=["Approved by Charlie H."], current_state="approved",
    )

    assert ok is not False
    assert any("to email to purchasing" in t for t in fake.thread_texts(after=seen)), fake.thread_texts(after=seen)
    dms = fake.dm_texts()
    assert any("Send this email to purchasing" in t for t in dms), dms
    assert [c[1]["filename"] for c in fake.client.files_upload_v2.call_args_list] == os.listdir(epifs_dir)
