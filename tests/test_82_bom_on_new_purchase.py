"""Tests for Ticket 82: BOM field on /new-purchase.

WHY THIS EXISTS:
----------------
Ticket 82 / ADR 0012 Decisions 1-4; ADR 0006 Decision 3; ADR 0001:
A requester may attach their own BOM spreadsheet on Screen 2 instead of pasting line
items. The bot carries it (posts it into the thread like a quote) and never opens it,
so no made BOM is built. The one-vendor and attach-or-paste rules live in the pure
function bom.attachment_errors, which tickets 85 and 86 reuse.
"""
import json
from unittest.mock import MagicMock

from src import app, blocks, bom, config, lifecycle, roster, slack_io
from tests.test_81_quotes_on_new_purchase import (  # noqa: F401  (autouse fixture is reused)
    _make_stage2_view_submission,
    _sample_stage1_meta,
    isolate_roster,
)

ONE_VENDOR = "One EPIF per vendor — split this into one request per vendor."


def _with_bom(view: dict, files: list[dict], ticked: bool) -> dict:
    values = view["state"]["values"]
    values["block_bom"] = {"bom": {"type": "file_input", "files": files}}
    values["block_bom_one_vendor"] = {
        "bom_one_vendor": {
            "type": "checkboxes",
            "selected_options": [{"value": "one_vendor"}] if ticked else [],
        }
    }
    return view


def _blk_map(meta):
    return {b.get("block_id"): b for b in blocks.build_stage2_view(meta)["blocks"]}


# 1. The fields

def test_screen2_has_bom_fields_when_not_edit():
    blk = _blk_map(_sample_stage1_meta(is_edit=False))
    bom_block = blk["block_bom"]
    assert bom_block["type"] == "input"
    assert bom_block["optional"] is True
    assert bom_block["element"]["type"] == "file_input"
    assert bom_block["element"]["action_id"] == "bom"
    assert bom_block["element"]["filetypes"] == ["xlsx"]  # Ticket 134 / ADR 0019: the lab template only
    assert bom_block["element"]["max_files"] == 1
    assert bom_block["label"]["text"] == "BOM spreadsheet (optional)"
    assert bom_block["hint"]["text"] == (
        "Two or more items? Fill in the lab BOM template."
    )

    box = blk["block_bom_one_vendor"]
    assert box["type"] == "input"
    assert box["optional"] is True
    assert box["element"]["type"] == "checkboxes"
    assert box["element"]["action_id"] == "bom_one_vendor"
    assert [o["value"] for o in box["element"]["options"]] == ["one_vendor"]
    assert box["element"]["options"][0]["text"]["text"] == "Every item in this BOM comes from one vendor"
    assert box["label"]["text"] == "Required if you attach a BOM"


def test_screen2_omits_bom_fields_when_edit():
    # Name kept from ticket 82; the assertion is reversed by ticket 86: Edit now carries
    # the BOM fields as well, so a new BOM can replace the old one.
    new_blk = _blk_map(_sample_stage1_meta())
    assert "block_bom" in new_blk
    assert "block_bom_one_vendor" in new_blk
    blk = _blk_map(_sample_stage1_meta(is_edit=True))
    assert "block_bom" in blk
    assert "block_bom_one_vendor" in blk


# 2. The rules, directly

def test_attachment_errors_rules():
    # ADR 0019 / Ticket 135: there is no paste box, so the only rule left is the one-vendor box.
    assert bom.attachment_errors([{"id": "F"}], False) == {"block_bom_one_vendor": ONE_VENDOR}
    assert bom.attachment_errors([{"id": "F"}], True) == {}
    assert bom.attachment_errors([], False) == {}
    assert bom.attachment_errors([], True) == {}
    # Without a paste box, the rule is the same however many files a form passes in.
    assert bom.attachment_errors([{"id": "F"}, {"id": "G"}], False) == {"block_bom_one_vendor": ONE_VENDOR}
    assert bom.attachment_errors([{"id": "F"}, {"id": "G"}], True) == {}
    assert set(bom.attachment_errors([{"id": "F"}], False)) == {"block_bom_one_vendor"}


# 3. The rules, through the form

def _submit(monkeypatch, view_kwargs, files, ticked):
    monkeypatch.setattr(config, "PURCHASING_CHANNEL", "C_PURCHASING")
    roster.add_requester("U_ISAAC", "Isaac")
    client = MagicMock()
    client.chat_postMessage.return_value = {"ok": True, "ts": "1234.5678"}
    client.files_info.side_effect = lambda file: {"ok": True, "file": {"id": file, "name": f"{file}.x"}}
    monkeypatch.setattr(slack_io, "download_file", lambda f: b"bytes-" + f["id"].encode())
    draft_spy = MagicMock()
    monkeypatch.setattr(lifecycle, "upload_draft_bom", draft_spy)
    ack = MagicMock()
    view = _with_bom(_make_stage2_view_submission(_sample_stage1_meta(), **view_kwargs), files, ticked)
    app.handle_stage2_submit(ack, {"user": {"id": "U_ISAAC"}}, client, view)
    return ack, client, draft_spy


def test_form_rejects_bom_without_one_vendor_box(monkeypatch):
    ack, client, _ = _submit(monkeypatch, {}, [{"id": "F1", "name": "order.xlsx"}], False)
    ack.assert_called_once_with(
        response_action="errors", errors={"block_bom_one_vendor": ONE_VENDOR}
    )
    client.chat_postMessage.assert_not_called()


# 4. A BOM is carried, never read or rebuilt

def test_help_text_teaches_bom_in_form():
    new = "Attach a BOM spreadsheet and quote PDFs in the purchase form"
    old = "Drop quote files or confirmation receipts"
    home = json.dumps(blocks.build_app_home_view())
    for text in (blocks.get_help_message(), home):
        assert new in text
        assert old not in text
