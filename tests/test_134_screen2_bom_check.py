"""Tests for Ticket 134: interview Screen 2 reads the BOM and shows the BOM check.

Acceptance criteria:
- [ ] test_screen2_has_no_paste_box
- [ ] test_submit_with_the_real_bom_shows_the_check
- [ ] test_check_refuses_a_mismatch_then_accepts_a_fix
- [ ] test_non_template_file_is_refused_on_the_check_screen
- [ ] test_fabrication_bom_goes_to_screen3_after_the_check
"""
import json
import os
from unittest.mock import MagicMock

import pytest

from src import app, blocks, bom, config, roster, slack_io
from tests.test_81_quotes_on_new_purchase import (  # noqa: F401  (autouse fixture is reused)
    _make_stage2_view_submission,
    _sample_stage1_meta,
    isolate_roster,
)
from tests.test_82_bom_on_new_purchase import _with_bom

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "BOM_TEMPLATE_FILLED_EXAMPLE.xlsx")
VIEW_ID = "V_MODAL"


def _fixture_bytes() -> bytes:
    with open(FIXTURE, "rb") as f:
        return f.read()


def _bom_totalling(total: float) -> bytes:
    """The fixture with its first unit cost moved so the rows total `total`."""
    items, problems = bom.read_bom_template(_fixture_bytes())
    assert problems == []
    items[0]["unit_price"] = round(items[0]["unit_price"] + (total - bom.bom_total(items)) / items[0]["quantity"], 2)
    assert bom.bom_total(items) == total
    return bom.build_bom_workbook({"item_description": "Copper gaskets", "requester": "Isaac"}, items)


@pytest.fixture
def world(monkeypatch):
    """A client that downloads BOMs by file id, and a background starter that runs inline."""
    monkeypatch.setattr(config, "PURCHASING_CHANNEL", "C_PURCHASING")
    roster.add_requester("U_ISAAC", "Isaac")
    files: dict[str, bytes] = {}
    client = MagicMock()
    client.chat_postMessage.return_value = {"ok": True, "ts": "1234.5678"}
    client.files_info.side_effect = lambda file: {"ok": True, "file": {"id": file, "name": f"{file}.xlsx"}}
    monkeypatch.setattr(slack_io, "download_file", lambda f: files[f["id"]])
    monkeypatch.setattr(app, "_run_in_background", lambda fn, *a: fn(*a))
    client.files = files
    return client


def _submit_stage2(client, *, total="858.50", category="Research/Lab Supplies (3105)", file_id="F_BOM"):
    view = _with_bom(
        _make_stage2_view_submission(_sample_stage1_meta(), total_price=total, category=category),
        [{"id": file_id, "name": "order.xlsx"}], True,
    )
    view["id"] = VIEW_ID
    ack = MagicMock()
    app.handle_stage2_submit(ack, {"user": {"id": "U_ISAAC"}, "view": {"id": VIEW_ID}}, client, view)
    return ack


def _check_submission(client, new_file_id=None):
    """Submit the check view most recently shown, as Slack would deliver it."""
    shown = client.views_update.call_args.kwargs["view"]
    files = [{"id": new_file_id, "name": "fixed.xlsx"}] if new_file_id else []
    view = {
        "id": VIEW_ID,
        "private_metadata": shown["private_metadata"],
        "state": {"values": {"block_bom_reupload": {"bom_reupload": {"type": "file_input", "files": files}}}},
    }
    ack = MagicMock()
    app.handle_bom_check_submit(ack, {"user": {"id": "U_ISAAC"}, "view": {"id": VIEW_ID}}, client, view)
    return ack


def _text(view) -> str:
    return json.dumps(view, ensure_ascii=False)


def test_screen2_has_no_paste_box():
    for meta in (_sample_stage1_meta(), _sample_stage1_meta(is_edit=True)):
        view = blocks.build_stage2_view(meta)
        ids = [b.get("block_id") for b in view["blocks"]]
        assert "block_line_items" not in ids
        bom_block = next(b for b in view["blocks"] if b.get("block_id") == "block_bom")
        assert bom_block["element"]["filetypes"] == ["xlsx"]


def test_submit_with_the_real_bom_shows_the_check(world):
    world.files["F_BOM"] = _fixture_bytes()
    ack = _submit_stage2(world)

    ack.assert_called_once()
    assert ack.call_args.kwargs["response_action"] == "update"
    assert ack.call_args.kwargs["view"]["callback_id"] == "bom_check_submit"
    assert "Reading your BOM" in _text(ack.call_args.kwargs["view"])
    world.views_update.assert_called_once()
    assert world.views_update.call_args.kwargs["view_id"] == VIEW_ID
    shown = _text(world.views_update.call_args.kwargs["view"])
    assert "4 items" in shown and "$858.50" in shown
    world.chat_postMessage.assert_not_called()


def test_check_refuses_a_mismatch_then_accepts_a_fix(world):
    world.files["F_BOM"] = _fixture_bytes()
    world.files["F_FIX"] = _bom_totalling(900.00)
    _submit_stage2(world, total="900")
    assert "The BOM totals $858.50 but you typed $900.00 — they must match." in _text(
        world.views_update.call_args.kwargs["view"])

    ack = _check_submission(world)
    assert ack.call_args.kwargs["response_action"] == "errors"
    assert "they must match" in ack.call_args.kwargs["errors"]["block_bom_reupload"]
    world.chat_postMessage.assert_not_called()

    # A corrected file is read again, and the screen then says it matches.
    ack = _check_submission(world, new_file_id="F_FIX")
    assert ack.call_args.kwargs["response_action"] == "update"
    assert "This matches your total." in _text(world.views_update.call_args.kwargs["view"])
    world.chat_postMessage.assert_not_called()

    # Continuing posts the card with the rows in its metadata, and the draft BOM goes to the thread.
    ack = _check_submission(world)
    ack.assert_called_once_with()
    posted = [c.kwargs for c in world.chat_postMessage.call_args_list if c.kwargs.get("metadata")]
    assert len(posted) == 1
    assert len(posted[0]["metadata"]["event_payload"]["items"]) >= 4
    names = [c.kwargs.get("filename", "") for c in world.files_upload_v2.call_args_list]
    assert any(n.startswith("DRAFT_HIRST_LAB_BOM_") for n in names)
    # The uploaded spreadsheet itself is not kept as an attachment (ADR 0019 decision 6).
    assert not any(a.get("role") == "bom" for a in posted[0]["metadata"]["event_payload"].get("attachments", []))


def test_non_template_file_is_refused_on_the_check_screen(world):
    world.files["F_BOM"] = b"item,qty,price\nflask,2,10\n"
    _submit_stage2(world)
    assert "isn't the lab BOM template" in _text(world.views_update.call_args.kwargs["view"])

    ack = _check_submission(world)
    assert ack.call_args.kwargs["response_action"] == "errors"
    assert "isn't the lab BOM template" in ack.call_args.kwargs["errors"]["block_bom_reupload"]
    world.chat_postMessage.assert_not_called()


def test_fabrication_bom_goes_to_screen3_after_the_check(world):
    world.files["F_BOM"] = _fixture_bytes()
    _submit_stage2(world, category="Fabrication Component (4670) > $200")
    ack = _check_submission(world)

    assert ack.call_args.kwargs["response_action"] == "update"
    assert ack.call_args.kwargs["view"]["callback_id"] == config.STAGE3_CALLBACK_ID
    world.chat_postMessage.assert_not_called()
