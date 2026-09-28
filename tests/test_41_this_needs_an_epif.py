"""Tests for Ticket 41: "This needs an EPIF" turns a waiting request into an EPIF order.

Acceptance criteria:
- [ ] handle_req_needs_epif keeps its permission check and opens the Screen 2 modal on the
      EPIF path, with the bare-thread context (channel, thread, card ts, requester, approver,
      assignee) in private metadata.
- [ ] On completion no new card is posted and no req_approve button exists anywhere.
- [ ] Row, EPIF and card update are one queued task; a missing template leaves the card
      waiting_for_details with no row and a failure line in the thread.
- [ ] Scenario: bare approval, then This needs an EPIF submitted by the assignee: one row with
      route epif, one PDF named by epif_archive_name, card approved, assignee DM has the PDF.
"""
import copy
import json
import os
import zipfile
from unittest.mock import MagicMock

import pytest

from src import admin, app, config, epif_parser, lifecycle, log_writer, queue_worker, roster, slack_io

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIXTURES = os.path.join(PROJECT_ROOT, "tests", "fixtures")

CHANNEL = "C123"
THREAD = "T123"


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
        "vendors": [{"name": "Grainger", "id": "V1"}],
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
def temp_epifs_dir(tmp_path, monkeypatch):
    epifs_path = str(tmp_path / "EPIFs")
    os.makedirs(epifs_path, exist_ok=True)
    monkeypatch.setattr(config, "EPIFS_DIR", epifs_path)
    monkeypatch.setattr(config, "EPIF_TEMPLATE_PATH", os.path.join(FIXTURES, "EPIF_TEMPLATE_HIRST.pdf"))
    return epifs_path


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

    @property
    def card(self):
        return self.messages[0]


def _post_waiting_card(fake, monkeypatch):
    monkeypatch.setattr(slack_io, "find_epif_in_thread", MagicMock(return_value=(None, None)))
    monkeypatch.setattr(slack_io, "get_thread_parent_author", MagicMock(return_value="U_REQ"))
    monkeypatch.setattr(slack_io, "resolve_requester", MagicMock(side_effect=lambda c, u: roster.resolve_requester(u) if hasattr(roster, "resolve_requester") else {"U_REQ": "Alex", "U_BUYER": "Dylan", "U_CHARLIE": "Charlie H."}.get(u)))
    say = MagicMock()
    lifecycle.handle_epif_processing(
        client=fake.client, say=say, channel=CHANNEL, thread_ts=THREAD,
        approver="U_CHARLIE", event_ts="E123",
        assignee_id="U_BUYER", assignee_name="Dylan",
    )
    return say


def _button(msg, action_id):
    for b in msg["blocks"]:
        if b.get("type") == "actions":
            for el in b["elements"]:
                if el.get("action_id") == action_id:
                    return el
    return None


def _click_needs_epif(fake, user_id):
    btn = _button(fake.card, "req_needs_epif")
    assert btn is not None, "waiting card must carry a This needs an EPIF button"
    body = {
        "user": {"id": user_id},
        "channel": {"id": CHANNEL},
        "message": {"ts": fake.card["ts"], "thread_ts": THREAD},
        "container": {"message_ts": fake.card["ts"], "thread_ts": THREAD},
        "trigger_id": "TRIG",
        "actions": [{"action_id": "req_needs_epif", "value": btn["value"]}],
    }
    ack, respond = MagicMock(), MagicMock()
    app.handle_req_needs_epif(ack, body, respond, fake.client)
    return ack, respond


def _submit_stage2(fake, ack, values_override=None):
    view = fake.client.views_open.call_args[1]["view"]
    values = {
        "block_vendor_name": {"vendor_name": {"value": "Winford"}},
        "block_item_description": {"item_description": {"value": "Widget"}},
        "block_purpose": {"purpose": {"value": "Test purpose"}},
        "block_link": {"link": {"value": "https://winford.example/widget"}},
        "block_total_price": {"total_price": {"value": "17.10"}},
        "block_vendor_contact_name": {"vendor_contact_name": {"value": "Sales Rep"}},
        "block_vendor_contact_email": {"vendor_contact_email": {"value": "rep@winford.example"}},
        "block_date_of_purchase": {"date_of_purchase": {"selected_date": "2026-09-24"}},
        "block_project_id": {"project_id": {"selected_option": {"value": "PG000025831"}}},
        "block_fund": {"fund": {"selected_option": {"value": "133"}}},
        "block_category": {"category": {"selected_option": {"value": "Research/Lab Supplies (3105)"}}},
        "block_delivery_room": {"delivery_room": {"selected_option": {"value": "ERB 212"}}},
        "block_payment_method": {"payment_method": {"selected_option": {"value": "P-card"}}},
    }
    values.update(values_override or {})
    submitted = {"private_metadata": view["private_metadata"], "state": {"values": values}}
    app.handle_stage2_submit(ack, {"user": {"id": "U_BUYER"}}, fake.client, submitted)


def _sheet_xml(path):
    with zipfile.ZipFile(path) as zf:
        return zf.read(config.SHEET_XML).decode("utf-8")


def _all_action_ids(messages):
    ids = []
    for msg in messages:
        for b in msg.get("blocks", []) or []:
            if b.get("type") == "actions":
                ids.extend(el.get("action_id") for el in b["elements"])
    return ids


def test_click_opens_epif_stage2_with_bare_thread_context(monkeypatch):
    fake = FakeSlack()
    _post_waiting_card(fake, monkeypatch)

    ack, respond = _click_needs_epif(fake, "U_BUYER")

    ack.assert_called_once()
    fake.client.views_open.assert_called_once()
    view = fake.client.views_open.call_args[1]["view"]
    assert view["callback_id"] == config.STAGE2_CALLBACK_ID
    meta = json.loads(view["private_metadata"])
    assert meta["route"] == "epif"
    ctx = meta["bare_thread"]
    assert ctx["channel"] == CHANNEL
    assert ctx["thread_ts"] == THREAD
    assert ctx["card_ts"] == fake.card["ts"]
    assert ctx["approver"] == "U_CHARLIE"
    assert ctx["assignee_id"] == "U_BUYER"
    assert ctx["assignee_name"] == "Dylan"
    assert meta["user_id"] == "U_REQ"
    assert meta["resolved_name"] == "Alex"
    # the vendor is typed on the first screen shown, and the EPIF path asks for a payment method
    block_ids = [b.get("block_id") for b in view["blocks"]]
    assert "block_vendor_name" in block_ids
    assert "block_payment_method" in block_ids


def test_stranger_is_denied_and_no_modal_opens(monkeypatch):
    fake = FakeSlack()
    _post_waiting_card(fake, monkeypatch)
    monkeypatch.setattr(admin, "is_admin_user", MagicMock(return_value=False))
    posted_before = len(fake.messages)

    ack, respond = _click_needs_epif(fake, "U_STRANGER")

    fake.client.views_open.assert_not_called()
    assert len(fake.messages) == posted_before


def test_scenario_bare_approval_then_needs_epif(temp_workbook, temp_epifs_dir, sync_queue, monkeypatch):
    fake = FakeSlack()
    _post_waiting_card(fake, monkeypatch)
    assert "Approved — waiting for details" in fake.card["text"]
    assert not any(a == "req_approve" for a in _all_action_ids(fake.messages))

    posts_before = fake.client.chat_postMessage.call_count
    _click_needs_epif(fake, "U_BUYER")
    ack = MagicMock()
    _submit_stage2(fake, ack)

    ack.assert_called_once_with()

    # one row, route epif (Excel is the reference)
    sheet_xml = _sheet_xml(temp_workbook)
    assert log_writer.get_cell_value(sheet_xml, "I17") == "Winford"
    assert log_writer.get_cell_value(sheet_xml, "B17") == "Alex"
    assert log_writer.get_cell_value(sheet_xml, "I18") is None

    # one PDF, named by the archive rule, that reads back the request
    files = os.listdir(temp_epifs_dir)
    expected = log_writer.epif_archive_name("Winford", 17.10, "PG000025831", [])
    assert files == [expected]
    with open(os.path.join(temp_epifs_dir, expected), "rb") as fh:
        reparsed = epif_parser.parse_epif(fh.read())
    assert reparsed["vendor"] == "Winford"
    assert reparsed["total_price"] == 17.10

    # the same card became approved; no new card and no req_approve button anywhere
    assert "Approved" in fake.card["text"] and "waiting" not in fake.card["text"]
    assert _button(fake.card, "req_needs_epif") is None
    assert not any(a == "req_approve" for a in _all_action_ids(fake.messages))
    for call in fake.client.chat_postMessage.call_args_list[posts_before:]:
        assert not call[1].get("blocks"), "no new card blocks may be posted"

    # the assignee's DM carries the EPIF PDF
    uploads = [c for c in fake.client.files_upload_v2.call_args_list if c[1].get("channel") == "D_BUYER"]
    assert [c[1]["filename"] for c in uploads] == [expected]
    dm_texts = [c[1]["text"] for c in fake.client.chat_postMessage.call_args_list if c[1].get("channel") == "U_BUYER"]
    assert dm_texts, "assignee must be DM'd"

    # approval is not asked again: the requester's "sent for approval" DM never goes out
    assert not [c for c in fake.client.chat_postMessage.call_args_list
                if "awaiting approval" in (c[1].get("text") or "")]


def test_missing_template_leaves_card_waiting_and_writes_no_row(temp_workbook, temp_epifs_dir, sync_queue, monkeypatch):
    fake = FakeSlack()
    _post_waiting_card(fake, monkeypatch)
    _click_needs_epif(fake, "U_BUYER")
    monkeypatch.setattr(config, "EPIF_TEMPLATE_PATH", "/does/not/exist.pdf")
    card_before = copy.deepcopy(fake.card)
    ack = MagicMock()

    _submit_stage2(fake, ack)

    assert log_writer.get_cell_value(_sheet_xml(temp_workbook), "I17") is None
    assert os.listdir(temp_epifs_dir) == []
    fake.client.chat_update.assert_not_called()
    assert fake.card == card_before
    assert _button(fake.card, "req_needs_epif") is not None
    thread_lines = [c[1]["text"] for c in fake.client.chat_postMessage.call_args_list
                    if c[1].get("thread_ts") == THREAD and "Error" in c[1].get("text", "")]
    assert thread_lines, "a failure line must be posted in the thread"


def test_submit_after_card_left_waiting_state_is_refused(temp_workbook, temp_epifs_dir, sync_queue, monkeypatch):
    """A card cancelled while the modal was open must not be revived into a row."""
    fake = FakeSlack()
    _post_waiting_card(fake, monkeypatch)
    _click_needs_epif(fake, "U_BUYER")
    fake.card["blocks"] = []
    fake.card["metadata"]["event_payload"]["state"] = "cancelled"
    ack = MagicMock()

    _submit_stage2(fake, ack)

    assert ack.call_args[1].get("response_action") == "errors"
    assert log_writer.get_cell_value(_sheet_xml(temp_workbook), "I17") is None
    assert os.listdir(temp_epifs_dir) == []
