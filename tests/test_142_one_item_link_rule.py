"""Tests for Ticket 142: A one-item request needs a link or 'No web page'.

WHY THIS EXISTS:
----------------
Ticket 142 / ADR 0020 Decision 4; ADR 0001:
On interview Screen 2 a request with no BOM must give its item link or tick No web page.
A URL already in Purpose counts as the link. A ticked box shows 'No web page' where the
card would show the link. When a BOM is attached, this rule is skipped because line-item
links are checked on the BOM check view (Ticket 141).
"""
from unittest.mock import MagicMock

import pytest

from src import app, blocks, config, roster
from tests.test_81_quotes_on_new_purchase import (
    _make_stage2_view_submission,
    _sample_stage1_meta,
)
from tests.test_82_bom_on_new_purchase import _with_bom


@pytest.fixture(autouse=True)
def isolate_roster(tmp_path, monkeypatch):
    """Ensure tests run against an isolated roster.json copy."""
    test_roster_file = str(tmp_path / "roster.json")
    monkeypatch.setattr(roster, "ROSTER_PATH", test_roster_file)
    roster.load_roster()
    return test_roster_file


def _with_no_link_box(view: dict, ticked: bool = False) -> dict:
    view["state"]["values"]["block_no_link"] = {
        "no_link": {
            "type": "checkboxes",
            "selected_options": [{"value": "no_web_page"}] if ticked else [],
        }
    }
    return view


def test_screen2_renders_link_and_no_link_blocks():
    """AC: build_stage2_view has block_link with new label & hint, followed by block_no_link checkbox."""
    view = blocks.build_stage2_view(_sample_stage1_meta())
    blocks_list = view["blocks"]
    block_ids = [b.get("block_id") for b in blocks_list]

    assert "block_link" in block_ids
    assert "block_no_link" in block_ids

    link_idx = block_ids.index("block_link")
    no_link_idx = block_ids.index("block_no_link")
    assert no_link_idx == link_idx + 1, "block_no_link must directly follow block_link"

    link_block = blocks_list[link_idx]
    assert link_block["type"] == "input"
    assert link_block["optional"] is True
    assert link_block["label"]["text"] == "Link to the item's web page"
    assert link_block["hint"]["text"] == "Required unless you attach a BOM or tick No web page."

    no_link_block = blocks_list[no_link_idx]
    assert no_link_block["type"] == "input"
    assert no_link_block["block_id"] == "block_no_link"
    assert no_link_block["optional"] is True
    assert no_link_block["label"]["text"] == "No link?"
    assert no_link_block["element"]["type"] == "checkboxes"
    assert no_link_block["element"]["action_id"] == "no_link"
    assert no_link_block["element"]["options"] == [
        {"text": {"type": "plain_text", "text": "No web page"}, "value": "no_web_page"}
    ]


def test_blank_link_no_url_no_tick_is_refused():
    """AC: ack is called with response_action='errors' and errors == {'block_link': ...}; postMessage not called."""
    meta = _sample_stage1_meta()
    view = _make_stage2_view_submission(meta, link="", purpose="Need new sensors for lab")
    view = _with_no_link_box(view, ticked=False)

    ack = MagicMock()
    body = {"user": {"id": "U_ISAAC"}}
    client = MagicMock()

    app.handle_stage2_submit(ack, body, client, view)

    ack.assert_called_once_with(
        response_action="errors",
        errors={"block_link": "Paste the item's web page, or tick No web page."},
    )
    client.chat_postMessage.assert_not_called()


def test_bad_link_is_refused():
    """AC: link 'see the quote' gives the 'That isn't a web address...' error on block_link."""
    meta = _sample_stage1_meta()
    view = _make_stage2_view_submission(meta, link="see the quote", purpose="Sensors")
    view = _with_no_link_box(view, ticked=False)

    ack = MagicMock()
    body = {"user": {"id": "U_ISAAC"}}
    client = MagicMock()

    app.handle_stage2_submit(ack, body, client, view)

    ack.assert_called_once_with(
        response_action="errors",
        errors={"block_link": "That isn't a web address. Paste the item's web page, or tick No web page."},
    )
    client.chat_postMessage.assert_not_called()


def test_link_without_scheme_is_stored_with_https(monkeypatch):
    """AC: link 'mcmaster.com/91251A540' posts a card whose text contains https://mcmaster.com/91251A540."""
    monkeypatch.setattr(config, "PURCHASING_CHANNEL", "C_PURCHASING")
    roster.add_requester("U_ISAAC", "Isaac")

    meta = _sample_stage1_meta()
    view = _make_stage2_view_submission(meta, link="mcmaster.com/91251A540", purpose="Fasteners")
    view = _with_no_link_box(view, ticked=False)

    ack = MagicMock()
    body = {"user": {"id": "U_ISAAC"}}
    client = MagicMock()
    client.chat_postMessage.return_value = {"ok": True, "ts": "1234.5678"}

    app.handle_stage2_submit(ack, body, client, view)

    ack.assert_called_once_with()
    client.chat_postMessage.assert_called()

    call_kwargs = next(c[1] for c in client.chat_postMessage.call_args_list if "metadata" in c[1])
    parsed = call_kwargs["metadata"]["event_payload"]["parsed"]
    assert parsed["link"] == "https://mcmaster.com/91251A540"

    card_text = call_kwargs["blocks"][0]["text"]["text"]
    assert "https://mcmaster.com/91251A540" in card_text


def test_url_in_purpose_counts_and_no_web_page_shows_on_card(monkeypatch):
    """AC: blank link with URL in Purpose accepted; blank link, no URL, no_web_page ticked shows '• *Link:* No web page'."""
    monkeypatch.setattr(config, "PURCHASING_CHANNEL", "C_PURCHASING")
    roster.add_requester("U_ISAAC", "Isaac")

    # Part 1: blank link with URL in purpose
    meta1 = _sample_stage1_meta()
    view1 = _make_stage2_view_submission(meta1, link="", purpose="Measuring device https://x.org/p for beamline")
    view1 = _with_no_link_box(view1, ticked=False)

    ack1 = MagicMock()
    body1 = {"user": {"id": "U_ISAAC"}}
    client1 = MagicMock()
    client1.chat_postMessage.return_value = {"ok": True, "ts": "1234.5678"}

    app.handle_stage2_submit(ack1, body1, client1, view1)

    ack1.assert_called_once_with()
    client1.chat_postMessage.assert_called()
    call1 = next(c[1] for c in client1.chat_postMessage.call_args_list if "metadata" in c[1])
    parsed1 = call1["metadata"]["event_payload"]["parsed"]
    assert parsed1["link"] == "https://x.org/p"

    # Part 2: blank link, no URL, no_web_page ticked
    meta2 = _sample_stage1_meta()
    view2 = _make_stage2_view_submission(meta2, link="", purpose="Custom machined part")
    view2 = _with_no_link_box(view2, ticked=True)

    ack2 = MagicMock()
    body2 = {"user": {"id": "U_ISAAC"}}
    client2 = MagicMock()
    client2.chat_postMessage.return_value = {"ok": True, "ts": "1234.5679"}

    app.handle_stage2_submit(ack2, body2, client2, view2)

    ack2.assert_called_once_with()
    client2.chat_postMessage.assert_called()
    call2 = next(c[1] for c in client2.chat_postMessage.call_args_list if "metadata" in c[1])
    parsed2 = call2["metadata"]["event_payload"]["parsed"]
    assert not parsed2.get("link")
    assert parsed2.get("no_link_reason") == "No web page"

    card_text2 = call2["blocks"][0]["text"]["text"]
    assert "• *Link:* No web page" in card_text2


def test_rule_skipped_with_a_bom(monkeypatch):
    """AC: blank link, no tick, a BOM attached: no block_link error (BOM check view is shown instead)."""
    monkeypatch.setattr(config, "PURCHASING_CHANNEL", "C_PURCHASING")
    roster.add_requester("U_ISAAC", "Isaac")

    meta = _sample_stage1_meta()
    s2 = blocks.build_stage2_view(meta)
    assert "block_no_link" in [b.get("block_id") for b in s2["blocks"]]

    base_view = _make_stage2_view_submission(meta, link="", purpose="Multiple parts")
    base_view = _with_no_link_box(base_view, ticked=False)
    view = _with_bom(base_view, [{"id": "F_BOM", "name": "order.xlsx"}], ticked=True)
    view["id"] = "V_MODAL"

    ack = MagicMock()
    body = {"user": {"id": "U_ISAAC"}, "view": {"id": "V_MODAL"}}
    client = MagicMock()

    app.handle_stage2_submit(ack, body, client, view)

    ack.assert_called_once()
    # It must NOT be called with errors on block_link
    if ack.call_args and ack.call_args.kwargs.get("response_action") == "errors":
        assert "block_link" not in ack.call_args.kwargs.get("errors", {})
