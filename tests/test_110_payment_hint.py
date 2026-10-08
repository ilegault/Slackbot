"""Ticket 110 (ADR 0017 decisions 3-4): the P-card vs Req/PO difference is explained
where the choice is made -- a hint under the Payment Method dropdown and the FAQ."""

import pytest

from src import blocks, config, interview


def _meta(route="epif", is_edit=False):
    return {
        "vendor_choice": "DigiKey",
        "vendor_custom": "",
        "route": route,
        "resolved_name": "Isaac",
        "user_id": "U_ISAAC",
        "is_pending_name": False,
        "is_edit": is_edit,
    }


def _blocks_by_id(view):
    return {b.get("block_id"): b for b in view.get("blocks", [])}


def test_hint_text_is_the_adr_wording():
    assert config.PAYMENT_METHOD_HINT == (
        "P-card — the lab's university credit card, for orders under $5,000. "
        "Req/PO — a purchase order placed through UW purchasing; required at $5,000 "
        "and over (get 3 quotes), or whenever a vendor only accepts a PO."
    )
    assert len(config.PAYMENT_METHOD_HINT) <= 2000


def test_epif_route_screen2_payment_method_has_hint():
    blk = _blocks_by_id(blocks.build_stage2_view(_meta("epif")))["block_payment_method"]
    assert blk["hint"] == {"type": "plain_text", "text": config.PAYMENT_METHOD_HINT}


def test_edit_view_for_epif_card_carries_the_same_hint():
    blk = _blocks_by_id(blocks.build_stage2_view(_meta("epif", is_edit=True)))[
        "block_payment_method"
    ]
    assert blk["hint"]["text"] == config.PAYMENT_METHOD_HINT


def test_workday_route_has_no_payment_method_block():
    assert "block_payment_method" not in _blocks_by_id(
        blocks.build_stage2_view(_meta("workday"))
    )


@pytest.mark.parametrize("key", ["p-card", "req/po", "req po"])
def test_faq_keys_return_the_hint(key):
    assert interview.FAQ_ANSWERS[key] == config.PAYMENT_METHOD_HINT
