"""Ticket 123: a request below its category's minimum is refused, wherever it comes in.

WHY THIS EXISTS: nothing compared the amount with the category, and a $109.00
Fabrication Component EPIF was approved in production. The form itself says
"at least $200" (Fabrication, 4670) and "more than 5k" (Standalone, 4602). The bot
refuses; it never changes the category itself.
"""
import os
from unittest.mock import MagicMock, patch

import pytest

from src import app, config, epif_filler, epif_parser, validators
from tests.test_28_line_items_modal_path import (
    _make_stage2_view_submission,
    _sample_stage1_meta,
)
from tests.test_32_edit_a_posted_card import (
    _make_client,
    _make_edit_view_submission,
    _sample_modal_card_payload,
)

FIXTURE_PATH = os.path.join(os.path.dirname(__file__), "fixtures", "EPIF_TEMPLATE_HIRST.pdf")
FABRICATION = "Fabrication Component (4670) > $200"
STANDALONE = "Standalone Equipment >$5k (4602)"

FAB_109 = (
    "Fabrication Component (4670) needs a total of at least $200.00 — this is $109.00. "
    "Pick another category (usually Research/Lab Supplies or Repair & Maintenance)."
)


def _fab(amount):
    return (
        "Fabrication Component (4670) needs a total of at least $200.00 — this is "
        f"{amount}. Pick another category (usually Research/Lab Supplies or Repair & Maintenance)."
    )


@pytest.mark.parametrize(
    "category,total,expected",
    [
        (FABRICATION, 109.00, FAB_109),
        (FABRICATION, 199.99, _fab("$199.99")),
        (FABRICATION, 200.00, None),
        (
            STANDALONE,
            5000.00,
            "Standalone Equipment (4602) needs a total of more than $5,000.00 — this is "
            "$5,000.00. Pick another category.",
        ),
        (STANDALONE, 5000.01, None),
        ("Research/Lab Supplies (3105)", 5.00, None),
        (FABRICATION, None, None),
    ],
)
def test_category_minimum_problem(category, total, expected):
    assert validators.category_minimum_problem(category, total) == expected
    assert config.CATEGORY_MINIMUMS == {FABRICATION: (200.00, True), STANDALONE: (5000.00, False)}


def _screen2(category, total):
    meta = _sample_stage1_meta(route="epif")
    view = _make_stage2_view_submission(
        meta, total_price=total, payment_method="Req/PO", category=category
    )
    ack, client = MagicMock(), MagicMock()
    app.handle_stage2_submit(ack, {"user": {"id": "U_REQ"}}, client, view)
    return ack, client


def test_screen2_refuses_fabrication_under_200():
    ack, client = _screen2(FABRICATION, "109")
    ack.assert_called_once()
    assert ack.call_args.kwargs["response_action"] == "errors"
    assert ack.call_args.kwargs["errors"] == {"block_category": FAB_109}
    client.views_open.assert_not_called()
    client.views_update.assert_not_called()
    client.chat_postMessage.assert_not_called()

    ack, _ = _screen2(FABRICATION, "200")
    assert ack.call_args.kwargs.get("response_action") != "errors"


def test_screen2_refuses_standalone_at_5000():
    ack, client = _screen2(STANDALONE, "5000")
    assert ack.call_args.kwargs["response_action"] == "errors"
    assert "$5,000.00" in ack.call_args.kwargs["errors"]["block_category"]
    client.views_open.assert_not_called()
    client.views_update.assert_not_called()


def test_edit_refuses_fabrication_under_200():
    card_payload = _sample_modal_card_payload()
    client = _make_client(card_payload)
    meta = {
        "is_edit": True, "channel": "C_CHAN", "thread_ts": "1000.000", "card_ts": "1000.100",
        "vendor_choice": "VWR-AVANTOR", "vendor_custom": "", "route": "workday",
    }
    body = _make_edit_view_submission(
        meta,
        stage2_overrides={"category": FABRICATION, "total_price": "109"},
        stage3_overrides={"asset_id": "A-1", "name_of_system": "Loop"},
    )
    ack_calls = []
    with (
        patch("src.app.roster.get_valid_requesters", return_value={"U_ISAAC": "Isaac"}),
        patch("src.app.slack_io.get_card_payload", return_value=card_payload),
    ):
        app.handle_edit_submit(lambda **kw: ack_calls.append(kw), body, client, body["view"])
    assert len(ack_calls) == 1
    assert ack_calls[0]["response_action"] == "errors"
    assert ack_calls[0]["errors"]["block_category"] == FAB_109
    client.chat_update.assert_not_called()


def test_dropped_epif_with_fabrication_under_200_is_refused():
    with open(FIXTURE_PATH, "rb") as f:
        template = f.read()
    filled = epif_filler.fill_epif(template, {
        "item_description": "Frame", "purpose": "Build", "total_price": 109.0,
        "vendor": "Acme", "vendor_contact_name": "Sales", "vendor_contact_email": "s@acme.com",
        "project_id": "PG000025831", "fund": "133", "delivery_room": "ERB 212",
        "category": FABRICATION, "payment_method": "Req/PO", "link": "https://acme.com",
        "name_of_system": "Loop", "asset_id": "A-1",
    })
    parsed = epif_parser.parse_epif(filled)
    assert parsed["category"] == FABRICATION
    problems = validators.validate(parsed, requester_name="Alex")
    assert FAB_109 in problems
