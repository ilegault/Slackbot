"""Tests for Ticket 130: a failed card update tells the person who acted.

Before this, a refused chat_update for an Edit or Add items was only logged: the requester
believed the edit had landed.

Acceptance criteria:
- [ ] test_failed_edit_update_tells_the_editor
- [ ] test_failed_items_update_tells_the_editor
"""
import json
from unittest.mock import MagicMock, patch

from slack_sdk.errors import SlackApiError

from src import app
from tests.test_27_line_items_epif_path import _make_thread_message, _sample_epif_card_payload
from tests.test_32_edit_a_posted_card import (
    _make_client,
    _make_edit_view_submission,
    _sample_modal_card_payload,
)


def _refusing(client):
    client.chat_update.side_effect = SlackApiError(
        "The request to the Slack API failed.", {"ok": False, "error": "invalid_blocks"}
    )


def _dms(client, user_id):
    return [c.kwargs for c in client.chat_postMessage.call_args_list if c.kwargs.get("channel") == user_id]


def test_failed_edit_update_tells_the_editor():
    card_payload = _sample_modal_card_payload()
    client = _make_client(card_payload)
    _refusing(client)
    meta = {"is_edit": True, "channel": "C_CHAN", "thread_ts": "1000.000", "card_ts": "1000.100",
            "vendor_choice": "VWR-AVANTOR", "vendor_custom": "", "route": "workday"}
    body = _make_edit_view_submission(meta, stage2_overrides={"purpose": "A brand new purpose"})

    with (
        patch("src.app.roster.get_valid_requesters", return_value={"U_ISAAC": "Isaac"}),
        patch("src.app.slack_io.get_card_payload", return_value=card_payload),
    ):
        app.handle_edit_submit(MagicMock(), body, client, body["view"])

    dms = _dms(client, "U_ISAAC")
    assert len(dms) == 1
    assert "was not saved" in dms[0]["text"]
    assert "invalid_blocks" in dms[0]["text"]
    assert "Nitrile Gloves" in dms[0]["text"]
    assert "Nothing changed on the card." in dms[0]["text"]
    thread_posts = [c.kwargs for c in client.chat_postMessage.call_args_list if c.kwargs.get("thread_ts")]
    assert not any("Edited by" in p.get("text", "") for p in thread_posts)


def test_failed_items_update_tells_the_editor():
    card_payload = _sample_epif_card_payload(total_price=100.0)
    client = MagicMock()
    client.conversations_replies.return_value = {"ok": True, "messages": [_make_thread_message(card_payload)]}
    _refusing(client)
    view = {
        "private_metadata": json.dumps({"channel": "C123", "thread_ts": "1000.1000", "card_ts": "1000.1000"}),
        "state": {"values": {"block_line_items": {"action_line_items": {"value": (
            "2 | Couplings | C-1 | 40.00 | | Two couplings\n"
            "1 | Set Screws | SS-2 | 10.00 | | Screws\n"
            "shipping | 10.00\n"
        )}}}},
    }

    app.handle_items_modal_submit(MagicMock(), {"user": {"id": "U_ISAAC"}}, client, view)

    dms = _dms(client, "U_ISAAC")
    assert len(dms) == 1
    assert "was not saved" in dms[0]["text"]
    assert "invalid_blocks" in dms[0]["text"]
    assert "Couplings" in dms[0]["text"]
    thread_posts = [c.kwargs for c in client.chat_postMessage.call_args_list if c.kwargs.get("thread_ts")]
    assert not any("Edited by" in p.get("text", "") or "Items" in p.get("text", "") for p in thread_posts)
