"""Tests for Ticket 85: Add items takes files on PDF-born cards.

Acceptance criteria:
- [ ] The form: optional items box + BOM blocks + quotes block
- [ ] Empty is refused
- [ ] Same rules as Screen 2 (not-both, one-vendor)
- [ ] Files only: attachments in card metadata, uploaded to thread, edit line, items unchanged
- [ ] Approval archives them
"""
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


def _view(items_text="", bom_files=None, one_vendor=False, quote_files=None):
    values = {"block_line_items": {"action_line_items": {"value": items_text or None}}}
    if bom_files is not None:
        values["block_bom"] = {"bom": {"files": bom_files}}
    values["block_bom_one_vendor"] = {
        "bom_one_vendor": {"selected_options": [{"value": "one_vendor"}] if one_vendor else []}
    }
    if quote_files is not None:
        values["block_quotes"] = {"quotes": {"files": quote_files}}
    return {
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
    data = {"F_BOM": BOM_BYTES, "Q1": b"quote-1", "Q2": b"quote-2"}
    monkeypatch.setattr(slack_io, "download_file", lambda f: data[f["id"]])
    return data


def _submit(client, view):
    ack = MagicMock()
    app.handle_items_modal_submit(ack, {"user": {"id": "U_ISAAC"}}, client, view)
    return ack


def test_form_has_optional_items_box_bom_and_quotes():
    view = blocks.build_items_view("C1", "T1", "CT1")
    by_id = {b["block_id"]: b for b in view["blocks"]}
    assert by_id["block_line_items"]["optional"] is True
    assert {"block_bom", "block_bom_one_vendor", "block_quotes"} <= set(by_id)


def test_empty_submit_is_refused():
    client = _client(_sample_epif_card_payload())
    ack = _submit(client, _view())
    ack.assert_called_once_with(
        response_action="errors", errors={"block_line_items": "Add line items, a BOM or quotes."}
    )
    client.chat_update.assert_not_called()


def test_bom_with_pasted_items_and_bom_without_one_vendor_are_refused():
    client = _client(_sample_epif_card_payload())
    files = [{"id": "F_BOM", "name": "o.xlsx"}]
    ack = _submit(client, _view("1 | Coupling | C-1 | 100.00 | |", files, one_vendor=True))
    ack.assert_called_once_with(
        response_action="errors", errors={"block_bom": "Attach a BOM or paste line items, not both."}
    )
    ack = _submit(client, _view("", files, one_vendor=False))
    ack.assert_called_once_with(response_action="errors", errors=bom.attachment_errors(files, False, ""))
    assert "block_bom_one_vendor" in ack.call_args[1]["errors"]
    client.chat_update.assert_not_called()


def test_files_only_updates_card_uploads_and_keeps_items(downloads):
    card = _sample_epif_card_payload(items=ITEMS, shipping=0.0, total_price=100.0)
    client = _client(card)
    view = _view(
        "", [{"id": "F_BOM", "name": "o.xlsx"}], one_vendor=True,
        quote_files=[{"id": "Q1", "name": "a.pdf"}, {"id": "Q2", "name": "b.pdf"}],
    )
    ack = _submit(client, view)
    ack.assert_called_once_with()

    payload = client.chat_update.call_args[1]["metadata"]["event_payload"]
    assert [(a["role"], a["id"]) for a in payload["attachments"]] == [
        ("bom", "F_BOM"), ("quote", "Q1"), ("quote", "Q2"),
    ]
    assert payload["items"] == ITEMS
    assert client.files_upload_v2.call_count == 3
    lines = [c[1]["text"] for c in client.chat_postMessage.call_args_list if c[1].get("thread_ts") == "1000.1000"]
    edit = [t for t in lines if "attached BOM" in t]
    # Ticket 86 names each quote instead of counting them.
    assert len(edit) == 1
    assert "added quote a.pdf" in edit[0] and "added quote b.pdf" in edit[0]


def test_new_bom_replaces_old_and_quotes_append(downloads):
    card = _sample_epif_card_payload()
    card["attachments"] = [{"role": "bom", "id": "OLD", "name": "old.xlsx"}, {"role": "quote", "id": "QOLD", "name": "q.pdf"}]
    client = _client(card)
    _submit(client, _view("", [{"id": "F_BOM", "name": "new.xlsx"}], one_vendor=True, quote_files=[{"id": "Q1", "name": "a.pdf"}]))
    ids = [a["id"] for a in client.chat_update.call_args[1]["metadata"]["event_payload"]["attachments"]]
    # Ticket 86: merge_attachments lists the BOM first, then the kept and new quotes.
    assert ids == ["F_BOM", "QOLD", "Q1"]


def test_approval_archives_added_files(temp_workbook, dirs, sync_queue, downloads):
    card = _sample_epif_card_payload()
    client = _client(card)
    _submit(client, _view(
        "", [{"id": "F_BOM", "name": "o.xlsx"}], one_vendor=True,
        quote_files=[{"id": "Q1", "name": "a.pdf"}, {"id": "Q2", "name": "b.pdf"}],
    ))
    atts = client.chat_update.call_args[1]["metadata"]["event_payload"]["attachments"]

    approve_client = MagicMock()
    approve_client.files_info.side_effect = lambda file: {"file": {"id": file}}
    lifecycle.finalize_purchase_request(
        client=approve_client, say=MagicMock(), channel="C_PURCHASING", thread_ts="100.00", event_ts="100.10",
        parsed=_parsed(), requester="Alex", notify_target="U_REQ", card_ts="100.00",
        approver="U_CHARLIE", attachments=atts,
    )
    _, row = _row(temp_workbook)
    with open(os.path.join(dirs["BOMS_DIR"], f"{row:04d}_Swagelok_BOM.xlsx"), "rb") as f:
        assert f.read() == BOM_BYTES
    assert sorted(os.listdir(dirs["QUOTES_DIR"])) == [
        f"{row:04d}_Swagelok_Quote_1.pdf", f"{row:04d}_Swagelok_Quote_2.pdf",
    ]
