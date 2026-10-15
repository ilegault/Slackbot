"""Tests for Ticket 126: Change date works on a hand-filled (uploaded) EPIF.

Acceptance criteria:
- [ ] test_redate_epif_changes_only_the_date
- [ ] test_change_date_on_uploaded_epif
"""
import datetime
import io
import os
from unittest.mock import MagicMock

from pypdf import PdfReader, PdfWriter

from src import config, epif_filler, epif_parser, lifecycle, queue_worker
from tests.test_45_epif_approval_archives import create_test_workbook
from tests.test_125_change_epif_date import (  # noqa: F401  (fixtures and fakes shared with 125)
    CHANNEL,
    TEMPLATE,
    THREAD,
    FakeClient,
    _request,
    isolated_roster,
)


def _hand_edit(pdf_bytes, field, value):
    """Stand in for a requester typing into a field the bot's filler never writes."""
    reader = PdfReader(io.BytesIO(pdf_bytes))
    root = reader.trailer["/Root"]
    if "/Metadata" in root:
        del root["/Metadata"]
    writer = PdfWriter(clone_from=reader)
    for page in writer.pages:
        writer.update_page_form_field_values(page, {field: value}, auto_regenerate=False)
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


def test_redate_epif_changes_only_the_date():
    with open(TEMPLATE, "rb") as f:
        template = f.read()
    req = _request()
    req.update({
        "category": "Fabrication Component (4670) > $200",
        "payment_method": "P-card",
        "name_of_system": "Test Rig",
        "asset_id": "A123",
        "date_of_purchase": datetime.date(2026, 9, 1),
    })
    filled = epif_filler.fill_epif(template, req)
    redated = epif_filler.redate_epif(filled, datetime.date(2026, 11, 2))

    before = epif_parser.parse_epif(filled)
    after = epif_parser.parse_epif(redated)
    assert before["date_of_purchase"] == datetime.date(2026, 9, 1)
    assert after["date_of_purchase"] == datetime.date(2026, 11, 2)
    assert after["category"] == "Fabrication Component (4670) > $200"
    for key in before:
        if key in ("date_of_purchase", "raw_fields"):
            continue
        assert after[key] == before[key], key
    other = {k: v for k, v in before["raw_fields"].items() if k != "Date of Purchase"}
    assert {k: v for k, v in after["raw_fields"].items() if k != "Date of Purchase"} == other


def test_change_date_on_uploaded_epif(tmp_path, monkeypatch):
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

    with open(TEMPLATE, "rb") as f:
        template = f.read()
    req = _request()
    req["date_of_purchase"] = datetime.date(2026, 9, 1)
    uploaded = _hand_edit(epif_filler.fill_epif(template, req), "List of Other", "written by the requester")
    parsed = epif_parser.parse_epif(uploaded)
    parsed["source"] = "epif"

    client = FakeClient()
    lifecycle.finalize_purchase_request(
        client=client, say=MagicMock(), channel=CHANNEL, thread_ts=THREAD, event_ts="101.00",
        parsed=parsed, requester="Alex", notify_target="U_REQ", pdf_bytes=uploaded, file_name="mine.pdf",
        assignee_id="U_BUYER", assignee_name="Dylan",
    )
    (card_ts,) = [ts for (ch, ts), m in client.messages.items() if ch == CHANNEL and "metadata" in m]
    (epif_name,) = os.listdir(epifs)
    path = os.path.join(epifs, epif_name)
    with open(path, "rb") as f:
        archived = epif_parser.parse_epif(f.read())
    assert archived["date_of_purchase"] == datetime.date(2026, 9, 1)

    assert lifecycle.handle_change_epif_date(
        client, CHANNEL, THREAD, card_ts, "U_BUYER", datetime.date(2026, 11, 2)) is True

    assert os.listdir(epifs) == [epif_name]
    with open(path, "rb") as f:
        after = epif_parser.parse_epif(f.read())
    assert after["date_of_purchase"] == datetime.date(2026, 11, 2)
    assert after["purpose"] == archived["purpose"]
    assert after["total_price"] == archived["total_price"]
    # The hand-filled file was re-dated, not rebuilt from the template: a field the bot's
    # filler would have overwritten stays as the requester wrote it.
    assert after["raw_fields"]["Date of Purchase"] == "11/02/2026"
    assert after["raw_fields"]["List of Other"] == "written by the requester"
