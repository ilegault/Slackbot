"""Tests for ticket 124: the Filled EPIF is dated at approval; the interview stops asking for a date.

Acceptance criteria:
- [ ] No modal (Screen 2 new, Screen 2 edit, Workday details) renders block_date_of_purchase.
- [ ] A request posted on D1 and approved on D2 has a Filled EPIF dated D2 and column M = D1;
      an uploaded EPIF dated 09/01/2026 logs column M = 09/01/2026 and is archived unchanged.
- [ ] Existing Screen 2 / Edit / Workday-details submit tests no longer send the date block
      (rewritten in place).
"""
import os
from datetime import date
from unittest.mock import MagicMock

import pytest

from src import (
    blocks,
    config,
    epif_filler,
    epif_parser,
    interview,
    lifecycle,
    log_writer,
    queue_worker,
    roster,
    validators,
)
from tests.test_45_epif_approval_archives import create_test_workbook

FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")
D1 = date(2026, 10, 1)
D2 = date(2026, 10, 9)


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    roster_file = str(tmp_path / "roster.json")
    monkeypatch.setattr(roster, "ROSTER_PATH", roster_file)
    roster._DATA = None
    import json
    with open(roster_file, "w", encoding="utf-8") as f:
        json.dump({
            "admins": ["U_ADMIN"], "approvers": ["U_CHARLIE"], "buyers": ["U_BUYER"],
            "requesters": {"U_REQ": "Alex", "U_BUYER": "Dylan"}, "vendors": [],
        }, f)

    workbook = str(tmp_path / "Purchasing-Log.xlsx")
    create_test_workbook(workbook)
    monkeypatch.setattr(config, "WORKBOOK_PATH", workbook)
    epifs = str(tmp_path / "EPIFs")
    os.makedirs(epifs)
    monkeypatch.setattr(config, "EPIFS_DIR", epifs)
    monkeypatch.setattr(config, "EPIF_TEMPLATE_PATH", os.path.join(FIXTURES, "EPIF_TEMPLATE_HIRST.pdf"))

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


def _stage2():
    return {
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


def _view_meta(**extra):
    return {
        "vendor_choice": "DigiKey", "vendor_custom": "", "route": "epif",
        "resolved_name": "Isaac", "user_id": "U_ISAAC", "is_pending_name": False, **extra,
    }


def test_no_modal_asks_for_a_date():
    views = [
        blocks.build_stage2_view(_view_meta()),
        blocks.build_stage2_view(_view_meta(is_edit=True, date_of_purchase="2026-09-14")),
        blocks.build_workday_details_view("C1", "1.0", "2.0", ["DigiKey"]),
    ]
    for view in views:
        ids = [b.get("block_id") for b in view["blocks"]]
        assert "block_date_of_purchase" not in ids


def test_filled_epif_is_dated_the_approval_day(monkeypatch):
    rows = []
    real_append = log_writer.append_row

    def capture(values, *a, **kw):
        rows.append(dict(values))
        return real_append(values, *a, **kw)

    monkeypatch.setattr(log_writer, "append_row", capture)

    # Posted on D1: the interview stamps the request date.
    monkeypatch.setattr(interview, "today", lambda: D1)
    stage1 = {"vendor_choice": "Ruland", "vendor_custom": "", "route": "epif"}
    posted = interview.build_parsed_from_stages(stage1, _stage2(), None)
    assert posted["request_date"] == D1
    # The card payload carries dates as ISO strings.
    posted["request_date"] = posted["request_date"].isoformat()

    # Approved on D2.
    monkeypatch.setattr(interview, "today", lambda: D2)
    client = MagicMock()
    lifecycle.finalize_purchase_request(
        client=client, say=MagicMock(), channel="C_PURCHASING", thread_ts="100.00",
        event_ts="101.00", parsed=posted, requester="Alex", notify_target="U_REQ",
        new_card=True,
    )

    assert len(rows) == 1
    assert rows[0][config.COLUMN_DATE_OF_REQUEST] == D1

    files = os.listdir(config.EPIFS_DIR)
    assert len(files) == 1
    with open(os.path.join(config.EPIFS_DIR, files[0]), "rb") as f:
        filled = epif_parser.parse_epif(f.read())
    assert filled["date_of_purchase"] == D2

    # The card carries the EPIF date for ticket 125 to read.
    metas = [c.kwargs["metadata"]["event_payload"] for c in client.chat_postMessage.call_args_list
             if c.kwargs.get("metadata")]
    assert metas[-1]["epif_date"] == D2.isoformat()

    # An uploaded EPIF keeps its own date: column M is that date, the file is filed unchanged.
    uploaded_values = {**posted, "request_date": None, "date_of_purchase": date(2026, 9, 1)}
    with open(config.EPIF_TEMPLATE_PATH, "rb") as f:
        uploaded = epif_filler.fill_epif(f.read(), uploaded_values)
    parsed_up = epif_parser.parse_epif(uploaded)
    assert parsed_up["request_date"] == parsed_up["date_of_purchase"] == date(2026, 9, 1)
    lifecycle.finalize_purchase_request(
        client=MagicMock(), say=MagicMock(), channel="C_PURCHASING", thread_ts="200.00",
        event_ts="201.00", parsed=parsed_up, requester="Alex", notify_target="U_REQ",
        pdf_bytes=uploaded, file_name="quote.pdf", new_card=True,
    )
    assert rows[1][config.COLUMN_DATE_OF_REQUEST] == date(2026, 9, 1)
    archived = [n for n in os.listdir(config.EPIFS_DIR) if n != files[0]]
    assert len(archived) == 1
    with open(os.path.join(config.EPIFS_DIR, archived[0]), "rb") as f:
        assert f.read() == uploaded


def test_validate_accepts_a_request_date_in_place_of_date_of_purchase():
    """The interview no longer sets date_of_purchase; the request date satisfies the check."""
    monkeypatch_free = interview.build_parsed_from_stages(
        {"vendor_choice": "Ruland", "vendor_custom": "", "route": "epif"}, _stage2(), None
    )
    assert monkeypatch_free["date_of_purchase"] is None
    problems = validators.validate(monkeypatch_free, requester_name="Alex")
    assert not any("date" in p.lower() for p in problems)


def test_edit_keeps_the_cards_dates():
    """Edit asks for no date and must not re-stamp the request date with the editing day."""
    from unittest.mock import patch

    from tests.test_32_edit_a_posted_card import _make_client, _sample_modal_card_payload

    card_payload = _sample_modal_card_payload(total_price=100.0)
    card_payload["parsed"]["request_date"] = "2026-01-15"
    client = _make_client(card_payload, card_ts="2000.100", thread_ts="2000.000")

    with patch("src.lifecycle.slack_io.resolve_requester", return_value="Isaac"):
        lifecycle.handle_request_edit(
            client=client, channel="C_CHAN", thread_ts="2000.000", card_ts="2000.100",
            stage2={**_stage2(), "total_price": "150.00", "link": "https://example.com",
                    "payment_method": config.WORKDAY_PAYMENT_METHOD},
            stage3=None, items=[], shipping=0.0, user_id="U_ISAAC",
            card_payload=card_payload,
            meta={"vendor_choice": "VWR-AVANTOR", "vendor_custom": "", "route": "workday"},
        )

    parsed = client.chat_update.call_args.kwargs["metadata"]["event_payload"]["parsed"]
    assert parsed["request_date"] == "2026-01-15"
    assert parsed["date_of_purchase"] == "2026-01-15"
