"""Ticket 50: one items box everywhere. Real builders, real parser; only inputs are faked."""
import json
import pathlib
from unittest.mock import MagicMock

import pytest

from src import app, blocks, bom, lifecycle, slack_io, validators


def _views():
    return {
        "items": blocks.build_items_view("C1", "T1", "CT1"),
        "workday": blocks.build_workday_details_view("C1", "T1", "CT1", ["Grainger"]),
    }


def _box(view):
    found = [b for b in view["blocks"] if b.get("block_id") == "block_line_items"]
    assert len(found) == 1
    return found[0]


@pytest.mark.parametrize("name", ["items", "workday"])  # Screen 2 lost its box in Ticket 134
def test_the_example_we_show_parses(name):
    text = _box(_views()[name])["element"]["placeholder"]["text"]
    items, shipping, errors = bom.parse_line_items(text)
    assert errors == []
    assert len(items) == 1
    assert shipping == 24.50


def test_same_hint_and_placeholder_in_all_three():
    boxes = [_box(v) for v in _views().values()]
    assert len({json.dumps(b["hint"]) for b in boxes}) == 1
    assert len({json.dumps(b["element"]["placeholder"]) for b in boxes}) == 1
    assert "max_length" not in _box(_views()["workday"])["element"]
    # Screen 2 no longer has the box (Ticket 134 / ADR 0019): it takes the BOM file instead.
    screen2 = blocks.build_stage2_view({})["blocks"]
    assert "block_line_items" not in [b.get("block_id") for b in screen2]

    # Each view keeps its action id and optional flag, so no submit handler changes its lookup.
    v = _views()
    assert _box(v["items"])["element"]["action_id"] == "action_line_items"
    assert _box(v["workday"])["element"]["action_id"] == "line_items"
    assert next(b for b in screen2 if b.get("block_id") == "block_bom")["element"]["action_id"] == "bom"
    # Ticket 85: Add items may carry only a BOM / quotes, so its box is optional too.
    assert _box(v["items"])["optional"] is True
    assert _box(v["workday"])["optional"] is True
    assert next(b for b in screen2 if b.get("block_id") == "block_bom")["optional"] is True


def test_block_line_items_literal_appears_once_in_blocks_source():
    src = pathlib.Path(blocks.__file__).read_text(encoding="utf-8")
    assert src.count('"block_line_items"') == 1


def test_bad_paste_in_workday_modal_shows_the_error(monkeypatch):
    client = MagicMock()
    ack = MagicMock()
    monkeypatch.setattr(validators, "validate", MagicMock(return_value=[]))
    monkeypatch.setattr(lifecycle, "finalize_purchase_request", MagicMock())
    card_payload = {"state": "waiting_for_details", "assignee_id": "U_ASSIGNEE",
                    "assignee": "Assignee", "approver": "Charlie", "requester": "Katarina"}
    monkeypatch.setattr(slack_io, "get_card_payload", MagicMock(return_value=card_payload))
    monkeypatch.setattr(slack_io, "resolve_requester", MagicMock(return_value="Katarina"))

    view = {
        "private_metadata": json.dumps({"channel_id": "C123", "thread_ts": "T123", "card_ts": "C_TS"}),
        "state": {"values": {
            "block_vendor": {"vendor": {"selected_option": {"value": "Grainger"}}},
            "block_item_description": {"item_description": {"value": "Widget"}},
            "block_total_price": {"total_price": {"value": "10.00"}},
            "block_category": {"category": {"selected_option": {"value": "Lab Consumable"}}},
            "block_line_items": {"line_items": {"value": "2 EA | Flask | FL-1 | 10.00"}},
        }},
    }
    app.handle_workday_details_submit(ack, {"user": {"id": "U_REQUESTER"}}, client, view)

    ack.assert_called_once()
    kwargs = ack.call_args[1]
    assert kwargs["response_action"] == "errors"
    err = kwargs["errors"]["block_line_items"]
    assert isinstance(err, str) and "line 1:" in err
    lifecycle.finalize_purchase_request.assert_not_called()
