"""Tests for Ticket 109: a P-card at $5,000 or more is refused (ADR 0017).

Covers pcard_problem directly, the Screen 2 submit (including a category that
needs asset details, where validate() would otherwise not run), and the EPIF
approval path with a real workbook write on a temp copy.
"""
import json
import zipfile
from datetime import date
from unittest.mock import MagicMock

import pytest

from src import app, config, lifecycle, log_writer, queue_worker, roster, validators
from tests.test_28_line_items_modal_path import (
    _make_stage2_view_submission,
    _sample_stage1_meta,
)
from tests.test_57_approval_storage_problems import create_test_workbook

MSG = "P-card is for orders under $5,000. Pick Req/PO."


@pytest.mark.parametrize(
    "method,total,expected",
    [
        ("P-card", 4999.99, None),
        ("P-card", 5000.00, MSG),
        ("p-card", 12000, MSG),
        ("Req/PO", 2520, None),
        ("Req/PO", 9000, None),
        ("P-card", None, None),
        (None, 9000, None),
    ],
)
def test_pcard_problem(method, total, expected):
    assert validators.pcard_problem(method, total) == expected


def test_constants_live_in_config():
    assert config.PCARD_LIMIT == 5000.00
    assert config.PCARD_LIMIT_MESSAGE == MSG


@pytest.fixture(autouse=True)
def isolate_roster(tmp_path, monkeypatch):
    path = str(tmp_path / "roster.json")
    monkeypatch.setattr(roster, "ROSTER_PATH", path)
    roster._DATA = None
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"admins": ["U_ADMIN"], "approvers": ["U_CHARLIE"], "buyers": [],
                   "requesters": {"U_REQ": "Alex"}, "vendors": []}, f)


@pytest.mark.parametrize(
    "category",
    ["Research/Lab Supplies (3105)", "Fabrication Component (4670) > $200"],
)
def test_screen2_refuses_pcard_over_limit(category):
    """Also for a category that needs Screen 3: the view must not advance."""
    meta = _sample_stage1_meta(route="epif")
    view = _make_stage2_view_submission(
        meta, total_price="6000.00", payment_method="P-card", category=category
    )
    ack = MagicMock()
    app.handle_stage2_submit(ack, {"user": {"id": "U_REQ"}}, MagicMock(), view)
    ack.assert_called_once()
    assert ack.call_args.kwargs["response_action"] == "errors"
    assert ack.call_args.kwargs["errors"] == {"block_payment_method": MSG}
    assert "view" not in ack.call_args.kwargs


@pytest.fixture
def temp_workbook(tmp_path, monkeypatch):
    p = str(tmp_path / "Purchasing-Log.xlsx")
    create_test_workbook(p)
    monkeypatch.setattr(config, "WORKBOOK_PATH", p)
    epifs = tmp_path / "epifs"
    epifs.mkdir()
    monkeypatch.setattr(config, "EPIFS_DIR", str(epifs))
    return p


@pytest.fixture
def sync_queue(monkeypatch):
    def _submit(action_fn, channel="", thread_ts="", user_id="", task_type="append",
                description="", success_callback=None, failure_callback=None, client=None):
        try:
            res = action_fn()
            if success_callback:
                success_callback(res)
        except Exception as exc:
            if failure_callback:
                failure_callback(exc)
    monkeypatch.setattr(queue_worker, "submit_write_task", _submit)


def _parsed(total, method):
    return {
        "item_description": "Shaft Couplings", "purpose": "Alignment",
        "total_price": total, "vendor": "Ruland", "vendor_contact_name": "Sales",
        "vendor_contact_email": "sales@ruland.com", "date_of_purchase": date(2026, 9, 22),
        "project_id": "PG000025831", "fund": "133",
        "category": "Research/Lab Supplies (3105)", "delivery_room": "ERB 212",
        "payment_method": method, "link": "https://ruland.com",
        "name_of_system": "", "asset_id": "", "route": "epif",
    }


def _approve(parsed):
    client = MagicMock()
    client.auth_test.return_value = {"ok": True, "user_id": "B_BOT"}
    client.chat_getPermalink.return_value = {"permalink": "https://slack.com/archives/C1/p2"}
    say = MagicMock()
    lifecycle.finalize_purchase_request(
        client=client, say=say, channel="C_PURCHASING", thread_ts="100.0",
        event_ts="100.1", parsed=parsed, requester="Alex", notify_target="U_REQ",
        approver="U_CHARLIE", pdf_bytes=b"%PDF-1.4 x", file_name="e.pdf",
    )
    return client, say


def _cell_i17(path):
    with zipfile.ZipFile(path) as zf:
        return log_writer.get_cell_value(zf.read(config.SHEET_XML).decode("utf-8"), "I17")


def test_epif_pcard_7500_writes_no_row_and_dms_requester(temp_workbook, sync_queue):
    client, say = _approve(_parsed(7500.0, "P-card"))
    assert _cell_i17(temp_workbook) is None
    assert say.call_args.kwargs["text"].startswith("Not logged")
    dms = [c.kwargs for c in client.chat_postMessage.call_args_list if c.kwargs.get("thread_ts") is None]
    req_dms = [d for d in dms if d["channel"] == "U_REQ"]
    assert req_dms and MSG in req_dms[0]["text"]


def test_req_po_2520_approves_and_writes_row(temp_workbook, sync_queue):
    _client, say = _approve(_parsed(2520.0, "Req/PO"))
    assert _cell_i17(temp_workbook) is not None
    assert not say.call_args.kwargs["text"].startswith("Not logged")
