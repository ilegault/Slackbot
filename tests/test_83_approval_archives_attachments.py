"""Tests for Ticket 83: approval archives attached BOMs and quotes and hands them to the buyer.

Acceptance criteria:
- [ ] Attached BOM archived as-is (bytes equal, Notes '(attached)', uploaded, no made BOM built)
- [ ] CSV keeps its extension
- [ ] Quotes numbered _Quote_1.._Quote_3, card carries quote_count 3
- [ ] The buyer gets them (at approval and via the picker later)
- [ ] One failed fetch does not stop approval
- [ ] Decline archives nothing
"""
import io
import json
import os
import zipfile
from datetime import date
from unittest.mock import MagicMock

import openpyxl
import pytest

from src import app, bom, config, lifecycle, log_writer, queue_worker, roster, slack_io

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
def dirs(tmp_path, monkeypatch):
    out = {}
    for name in ("BOMS_DIR", "QUOTES_DIR", "EPIFS_DIR"):
        d = str(tmp_path / name)
        os.makedirs(d)
        monkeypatch.setattr(config, name, d)
        out[name] = d
    monkeypatch.setattr(config, "EPIF_TEMPLATE_PATH", os.path.join(FIXTURES, "EPIF_TEMPLATE_HIRST.pdf"))
    monkeypatch.setattr(config, "ADMIN_ALERT_CHANNEL", "C_ADMIN")
    return out


@pytest.fixture
def temp_workbook(tmp_path, monkeypatch):
    from tests.test_29_approval_archives_bom import create_test_workbook
    p = str(tmp_path / "Purchasing-Log.xlsx")
    create_test_workbook(p)
    monkeypatch.setattr(config, "WORKBOOK_PATH", p)
    return p


@pytest.fixture
def sync_queue(monkeypatch):
    def _sync(action_fn, channel="", thread_ts="", user_id="", task_type="append",
              description="", success_callback=None, failure_callback=None, client=None):
        try:
            res = action_fn()
        except Exception as exc:
            if failure_callback:
                failure_callback(exc)
            return
        if success_callback:
            success_callback(res)
    monkeypatch.setattr(queue_worker, "submit_write_task", _sync)


def _xlsx_with_formula() -> bytes:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws["A1"], ws["A2"], ws["A3"] = 1, 2, "=SUM(A1:A2)"
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


BOM_BYTES = _xlsx_with_formula()


def _parsed(route_epif=False):
    return {
        "item_description": "Tube fittings",
        "purpose": "Loop build",
        "total_price": 150.0,
        "vendor": "Swagelok",
        "vendor_contact_name": "Sales",
        "vendor_contact_email": "sales@swagelok.com",
        "date_of_purchase": date(2026, 9, 22),
        "project_id": "PG000025831",
        "fund": "133",
        "category": "Research/Lab Supplies (3105)",
        "delivery_room": "ERB 212",
        "payment_method": "Workday",
        "link": "https://swagelok.com",
        "name_of_system": "",
        "asset_id": "",
        **({"route": "epif"} if route_epif else {}),
    }


def _client(contents: dict, fail=()):
    """Fake Slack client: files_info returns the id; slack_io.download_file is patched to read it."""
    client = MagicMock()
    client.files_info.side_effect = lambda file: {"file": {"id": file}}
    client.conversations_open.return_value = {"channel": {"id": "D_BUYER"}}
    return client


@pytest.fixture
def downloads(monkeypatch):
    store = {"fail": set(), "data": {}}

    def fake_download(file_obj):
        fid = file_obj["id"]
        if fid in store["fail"]:
            raise RuntimeError("download failed")
        return store["data"][fid]
    monkeypatch.setattr(slack_io, "download_file", fake_download)
    return store


def _approve(client, attachments, assignee=None, route_epif=False, items=None):
    lifecycle.finalize_purchase_request(
        client=client, say=MagicMock(), channel="C_PURCHASING", thread_ts="100.00", event_ts="100.10",
        parsed=_parsed(route_epif), requester="Alex", notify_target="U_REQ", card_ts="100.00",
        approver="U_CHARLIE", attachments=attachments, items=items,
        assignee_id="U_BUYER" if assignee else None, assignee_name="Dylan" if assignee else None,
    )


def _row(temp_workbook):
    with zipfile.ZipFile(temp_workbook) as zf:
        xml = zf.read(config.SHEET_XML).decode("utf-8")
    return xml, log_writer.find_first_empty_row(xml) - 1


def _uploads(client):
    return [c[1] for c in client.files_upload_v2.call_args_list]


def test_attached_bom_archived_as_is(temp_workbook, dirs, sync_queue, downloads, monkeypatch):
    downloads["data"]["F_BOM"] = BOM_BYTES
    spy = MagicMock()
    monkeypatch.setattr(bom, "build_bom_workbook", spy)
    client = _client({})
    _approve(client, [{"id": "F_BOM", "name": "order.xlsx", "role": "bom"}])

    xml, row = _row(temp_workbook)
    assert row == 17
    name = f"{row:04d}_Swagelok_BOM.xlsx"
    with open(os.path.join(dirs["BOMS_DIR"], name), "rb") as f:
        assert f.read() == BOM_BYTES
    assert log_writer.get_cell_value(xml, f"{config.COLUMN_NOTES}{row}") == f"BOM: {name} (attached)"
    ups = [u for u in _uploads(client) if u["filename"] == name]
    assert len(ups) == 1 and ups[0]["thread_ts"] == "100.00"
    spy.assert_not_called()


def test_attached_csv_keeps_extension(temp_workbook, dirs, sync_queue, downloads):
    downloads["data"]["F_CSV"] = b"a,b\n1,2\n"
    _approve(_client({}), [{"id": "F_CSV", "name": "Order.CSV", "role": "bom"}])
    assert os.listdir(dirs["BOMS_DIR"]) == ["0017_Swagelok_BOM.csv"]


def test_quotes_numbered_and_card_carries_count(temp_workbook, dirs, sync_queue, downloads):
    atts = []
    for k in (1, 2, 3):
        downloads["data"][f"Q{k}"] = f"quote-{k}".encode()
        atts.append({"id": f"Q{k}", "name": f"q{k}.pdf", "role": "quote"})
    client = _client({})
    _approve(client, atts)

    for k in (1, 2, 3):
        with open(os.path.join(dirs["QUOTES_DIR"], f"0017_Swagelok_Quote_{k}.pdf"), "rb") as f:
            assert f.read() == f"quote-{k}".encode()
    kwargs = client.chat_update.call_args[1]
    actions = next(b for b in kwargs["blocks"] if b.get("type") == "actions")
    assert json.loads(actions["elements"][0]["value"])["request"]["quote_count"] == 3
    assert "attachments" not in kwargs["metadata"]["event_payload"]
    assert bom.quote_filename(7, "Swagelok", 2) == bom.bom_filename(7, "Swagelok").replace("_BOM.xlsx", "_Quote_2.pdf")


def test_buyer_gets_bom_and_quotes_at_approval_and_on_later_assign(temp_workbook, dirs, sync_queue, downloads):
    downloads["data"]["F_BOM"] = BOM_BYTES
    atts = [{"id": "F_BOM", "name": "order.xlsx", "role": "bom"}]
    for k in (1, 2, 3):
        downloads["data"][f"Q{k}"] = f"quote-{k}".encode()
        atts.append({"id": f"Q{k}", "name": f"q{k}.pdf", "role": "quote"})
    client = _client({})
    _approve(client, atts, assignee=True, route_epif=True)
    dm = [u for u in _uploads(client) if u.get("channel") == "D_BUYER"]
    names = sorted(u["filename"] for u in dm)
    assert "0017_Swagelok_BOM.xlsx" in names
    assert [n for n in names if "_Quote_" in n] == [f"0017_Swagelok_Quote_{k}.pdf" for k in (1, 2, 3)]

    # Later assignment through the picker: approve unassigned, then pick the buyer.
    for f in os.listdir(dirs["BOMS_DIR"]):
        pass
    client2 = _client({})
    req = {"parsed": {**_parsed(True), "date_of_purchase": "2026-09-22"}, "requester": "Alex", "user_id": "U_REQ", "state": "approved",
           "quote_count": 3, "source": "epif", "epif_file": None}
    body = {
        "user": {"id": "U_CHARLIE"}, "channel": {"id": "C_PURCHASING"},
        "message": {"ts": "100.00", "blocks": [{"type": "actions", "elements": [
            {"type": "button", "value": json.dumps({"state": "approved", "request": req, "history": []})}]}]},
        "container": {"thread_ts": "100.00"},
        "actions": [{"selected_user": "U_BUYER"}],
    }
    client2.conversations_replies.return_value = {"messages": []}
    # row lookup is a Slack thread scan; pin it to the archived row
    import unittest.mock as um
    with um.patch.object(slack_io, "find_row_in_thread", return_value=17):
        app.handle_req_assign_select_action(MagicMock(), body, MagicMock(), client2)
    dm2 = [u["filename"] for u in _uploads(client2) if u.get("channel") == "D_BUYER"]
    assert sorted(dm2) == [f"0017_Swagelok_Quote_{k}.pdf" for k in (1, 2, 3)]


def test_one_failed_fetch_does_not_stop_approval(temp_workbook, dirs, sync_queue, downloads):
    atts = []
    for k in (1, 2, 3):
        downloads["data"][f"Q{k}"] = b"x"
        atts.append({"id": f"Q{k}", "name": f"vendor-quote-{k}.pdf", "role": "quote"})
    downloads["fail"].add("Q2")
    client = _client({})
    _approve(client, atts)

    _, row = _row(temp_workbook)
    assert row == 17
    assert sorted(os.listdir(dirs["QUOTES_DIR"])) == ["0017_Swagelok_Quote_1.pdf", "0017_Swagelok_Quote_3.pdf"]
    alerts = [c[1]["text"] for c in client.chat_postMessage.call_args_list if c[1].get("channel") == "C_ADMIN"]
    assert any("vendor-quote-2.pdf" in t and "17" in t for t in alerts)


def test_approval_through_handle_epif_processing_reads_card_metadata(temp_workbook, dirs, sync_queue, downloads):
    """The real entry point: attachments come off the card's Slack metadata, not the button value."""
    downloads["data"]["Q1"] = b"pdf"
    payload = {"parsed": {**_parsed(), "date_of_purchase": "2026-09-22"}, "requester": "Alex", "user_id": "U_REQ",
               "thread_ts": "100.00", "attachments": [{"id": "Q1", "name": "q.pdf", "role": "quote"}]}
    client = _client({})
    client.conversations_replies.return_value = {"messages": [{
        "ts": "100.00", "blocks": [],
        "metadata": {"event_type": "purchase_request", "event_payload": payload}}]}
    lifecycle.handle_epif_processing(
        client, MagicMock(), "C_PURCHASING", "100.00", "U_CHARLIE", "100.10",
        posted_payload=payload, card_ts="100.00")
    assert os.listdir(dirs["QUOTES_DIR"]) == ["0017_Swagelok_Quote_1.pdf"]


def test_decline_archives_nothing(temp_workbook, dirs, sync_queue, downloads):
    downloads["data"]["F_BOM"] = BOM_BYTES
    downloads["data"]["Q1"] = b"x"
    atts = [{"id": "F_BOM", "name": "order.xlsx", "role": "bom"}, {"id": "Q1", "name": "q.pdf", "role": "quote"}]
    payload = {"parsed": {**_parsed(), "date_of_purchase": "2026-09-22"}, "requester": "Alex", "user_id": "U_REQ",
               "attachments": atts}
    client = _client({})
    body = {
        "user": {"id": "U_CHARLIE"}, "channel": {"id": "C_PURCHASING"},
        "message": {"ts": "100.00", "blocks": [{"type": "actions", "elements": [
            {"type": "button", "action_id": "req_decline",
             "value": json.dumps({"state": "posted", "request": payload, "history": []})}]}]},
        "container": {"thread_ts": "100.00"},
        "actions": [{"action_id": "req_decline", "value": json.dumps({"state": "posted", "request": payload, "history": []})}],
    }
    handler = getattr(app, "handle_req_decline_action", None)
    assert handler is not None
    handler(MagicMock(), body, MagicMock(), client)
    assert os.listdir(dirs["BOMS_DIR"]) == [] and os.listdir(dirs["QUOTES_DIR"]) == []
    client.files_info.assert_not_called()

    # Control: the very same card, approved instead, does archive both files, so the
    # emptiness above is the decline's doing and not a broken fixture.
    _approve(_client({}), atts)
    assert os.listdir(dirs["BOMS_DIR"]) == ["0017_Swagelok_BOM.xlsx"]
    assert os.listdir(dirs["QUOTES_DIR"]) == ["0017_Swagelok_Quote_1.pdf"]
