"""Tests for Ticket 85: Add items takes files on PDF-born cards.

Acceptance criteria:
- [ ] The form: BOM blocks + quotes block (no paste box: ADR 0019 / Ticket 135) block
- [ ] Empty is refused
- [ ] Same rules as Screen 2 (one-vendor); a BOM goes through the BOM check
- [ ] Quotes only: attachments in card metadata, uploaded to thread, edit line, items unchanged
- [ ] Approval archives them
"""
import datetime
import json
import os
from unittest.mock import MagicMock

import pytest

from src import app, blocks, bom, lifecycle, slack_io
from tests import test_83_approval_archives_attachments as t83
from tests.test_27_line_items_epif_path import _make_thread_message, _sample_epif_card_payload

# Reuse ticket 83's real-workbook fixtures (assignment, not import, so ruff sees no shadowing).
clean_roster = t83.clean_roster
dirs = t83.dirs
sync_queue = t83.sync_queue
temp_workbook = t83.temp_workbook
BOM_BYTES = t83.BOM_BYTES
_parsed = t83._parsed
_row = t83._row

ITEMS = [{"qty": 1, "name": "Coupling", "part_number": "C-1", "unit_price": 100.0, "link": "", "description": ""}]
FIXTURE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "BOM_TEMPLATE_FILLED_EXAMPLE.xlsx")


def _view(bom_files=None, one_vendor=False, quote_files=None):
    values = {}
    if bom_files is not None:
        values["block_bom"] = {"bom": {"files": bom_files}}
    values["block_bom_one_vendor"] = {
        "bom_one_vendor": {"selected_options": [{"value": "one_vendor"}] if one_vendor else []}
    }
    if quote_files is not None:
        values["block_quotes"] = {"quotes": {"files": quote_files}}
    return {
        "id": "V_ITEMS",
        "private_metadata": json.dumps({"channel": "C123", "thread_ts": "1000.1000", "card_ts": "1000.1000"}),
        "state": {"values": values},
    }


def _client(card_payload):
    client = MagicMock()
    client.conversations_replies.return_value = {"ok": True, "messages": [_make_thread_message(card_payload)]}
    client.files_info.side_effect = lambda file: {"file": {"id": file}}
    return client


@pytest.fixture
def downloads(monkeypatch):
    with open(FIXTURE, "rb") as f:
        data = {"F_BOM": f.read(), "Q1": b"quote-1", "Q2": b"quote-2"}
    monkeypatch.setattr(slack_io, "download_file", lambda f: data[f["id"]])
    monkeypatch.setattr(app, "_run_in_background", lambda fn, *a: fn(*a))
    return data


def _submit(client, view):
    ack = MagicMock()
    app.handle_items_modal_submit(ack, {"user": {"id": "U_ISAAC"}}, client, view)
    return ack


def _submit_through_the_check(client, view):
    """Submit Add items with a BOM, then submit the check view it produced; returns that second ack."""
    first = _submit(client, view)
    assert first.call_args.kwargs["response_action"] == "update"
    shown = client.views_update.call_args.kwargs["view"]
    check = {"id": "V_ITEMS", "private_metadata": shown["private_metadata"],
             "state": {"values": {"block_bom_reupload": {"bom_reupload": {"files": []}}}}}
    ack = MagicMock()
    app.handle_bom_check_submit(ack, {"user": {"id": "U_ISAAC"}, "view": {"id": "V_ITEMS"}}, client, check)
    return ack


def test_form_has_optional_items_box_bom_and_quotes():
    view = blocks.build_items_view("C1", "T1", "CT1")
    by_id = {b["block_id"]: b for b in view["blocks"]}
    assert "block_line_items" not in by_id  # ADR 0019: a BOM file replaces the paste box
    assert by_id["block_bom"]["element"]["filetypes"] == ["xlsx"]
    assert {"block_bom", "block_bom_one_vendor", "block_quotes"} <= set(by_id)


def test_empty_submit_is_refused():
    client = _client(_sample_epif_card_payload())
    ack = _submit(client, _view())
    ack.assert_called_once_with(
        response_action="errors", errors={"block_bom": "Add a BOM or quotes."}
    )
    client.chat_update.assert_not_called()


def test_files_only_updates_card_uploads_and_keeps_items(downloads):
    card = _sample_epif_card_payload(items=ITEMS, shipping=0.0, total_price=100.0)
    client = _client(card)
    view = _view(quote_files=[{"id": "Q1", "name": "a.pdf"}, {"id": "Q2", "name": "b.pdf"}])
    ack = _submit(client, view)
    ack.assert_called_once_with()

    payload = client.chat_update.call_args[1]["metadata"]["event_payload"]
    assert [(a["role"], a["id"]) for a in payload["attachments"]] == [("quote", "Q1"), ("quote", "Q2")]
    assert payload["items"] == ITEMS
    assert client.files_upload_v2.call_count == 2
    lines = [c[1]["text"] for c in client.chat_postMessage.call_args_list if c[1].get("thread_ts") == "1000.1000"]
    edit = [t for t in lines if "quote" in t]
    # Ticket 86 names each quote instead of counting them.
    assert len(edit) == 1
    assert "added quote a.pdf" in edit[0] and "added quote b.pdf" in edit[0]


def test_new_bom_replaces_old_and_quotes_append(downloads):
    card = _sample_epif_card_payload(total_price=858.50)
    card["attachments"] = [{"role": "bom", "id": "OLD", "name": "old.xlsx"}, {"role": "quote", "id": "QOLD", "name": "q.pdf"}]
    client = _client(card)
    ack = _submit_through_the_check(client, _view([{"id": "F_BOM", "name": "new.xlsx"}], one_vendor=True, quote_files=[{"id": "Q1", "name": "a.pdf"}]))
    ack.assert_called_once_with()
    payload = client.chat_update.call_args[1]["metadata"]["event_payload"]
    # The new BOM is read, not kept: its rows replace the old BOM, and only the quotes stay attached.
    assert [a["id"] for a in payload["attachments"]] == ["QOLD", "Q1"]
    assert len(payload["items"]) == 4


def test_approval_archives_added_files(temp_workbook, dirs, sync_queue, downloads):
    card = _sample_epif_card_payload(total_price=858.50)
    client = _client(card)
    _submit_through_the_check(client, _view(
        [{"id": "F_BOM", "name": "o.xlsx"}], one_vendor=True,
        quote_files=[{"id": "Q1", "name": "a.pdf"}, {"id": "Q2", "name": "b.pdf"}],
    ))
    payload = client.chat_update.call_args[1]["metadata"]["event_payload"]

    approve_client = MagicMock()
    approve_client.files_info.side_effect = lambda file: {"file": {"id": file}}
    parsed = _parsed()
    parsed["total_price"] = 858.50
    lifecycle.finalize_purchase_request(
        client=approve_client, say=MagicMock(), channel="C_PURCHASING", thread_ts="100.00", event_ts="100.10",
        parsed=parsed, requester="Alex", notify_target="U_REQ", card_ts="100.00",
        approver="U_CHARLIE", items=payload["items"], attachments=payload["attachments"],
    )
    _, row = _row(temp_workbook)
    (bom_file,) = os.listdir(dirs["BOMS_DIR"])
    assert bom_file == f"HIRST_LAB_BOM_Tube-fittings_{datetime.date.today():%m.%d.%Y}.xlsx"
    with open(os.path.join(dirs["BOMS_DIR"], bom_file), "rb") as f:
        rows, problems = bom.read_bom_template(f.read())
    assert problems == [] and len(rows) == 4
    assert sorted(os.listdir(dirs["QUOTES_DIR"])) == [
        f"{row:04d}_Swagelok_Quote_1.pdf", f"{row:04d}_Swagelok_Quote_2.pdf",
    ]
