"""Ticket 114 (ADR 0018 decision 2): the buyer's DM card shows the whole request.

blocks, interview and lifecycle.sync_dm_card are real; only the Slack client is faked.
"""
from unittest.mock import MagicMock

import pytest

from src import blocks, lifecycle


def _request(payment_method="Workday", **extra):
    request = {
        "parsed": {
            "item_description": "Laser Diode",
            "total_price": 1234.56,
            "vendor": "Thorlabs",
            "payment_method": payment_method,
            "category": "Lab Consumable",
            "project_id": "PRJ-123",
            "fund": "FND-456",
            "delivery_room": "Room 101",
            "purpose": "Alignment rig",
            "link": "https://example.com/diode",
        },
        "requester": "Test Requester",
        "assignee_id": "U12345",
        "assignee": "Test Buyer",
        "expected_delivery": "2026-11-16",
        "row": 7,
        "items": [
            {"qty": 1, "description": "item 1", "price": 10},
            {"qty": 1, "description": "item 2", "price": 10},
            {"qty": 1, "description": "item 3", "price": 10},
        ],
        "attachments": [
            {"role": "bom", "name": "bom.xlsx"},
            {"role": "quote", "id": "q1", "name": "quote1.pdf"},
        ],
    }
    request.update(extra)
    return request


def _dm(state, request, **kwargs):
    return blocks.build_dm_card_blocks(
        state=state,
        request=request,
        thread_channel="C123",
        thread_ts="111.222",
        card_ts="333.444",
        thread_link="https://example.com/thread",
        **kwargs,
    )


def test_dm_card_shows_every_line_of_the_request():
    request = _request()
    result = _dm("approved", request, history=["Approved by the approver on 10/09/26 10:00"], route="workday")
    text = result[0]["text"]["text"]

    assert text.startswith("🛒 *Place this in Workday*")
    for line in blocks.request_summary_lines(request, "approved")[1:]:
        assert line in text
    assert "• *Row:* 7" in text
    assert "Stage: *approved*" in text
    assert "<https://example.com/thread|Open the request thread>" in text
    assert result[1]["type"] == "context"
    ctx = result[1]["elements"][0]["text"]
    assert "*History:*" in ctx
    assert "Approved by the approver on 10/09/26 10:00" in ctx
    assert result[2]["type"] == "actions"
    # No history: no context block.
    assert [b["type"] for b in _dm("approved", request)] == ["section", "actions"]


@pytest.mark.parametrize("state,note", [
    ("processed", None),
    ("confirmed", None),
    ("cancelled", None),
    ("reassigned", "Reassigned to another buyer"),
    ("delivered", None),
])
def test_dm_card_header_and_retired_states_follow_the_path(state, note):
    request = _request(payment_method="P-card")
    result = _dm(state, request, history=["h1"], route="epif", note=note)
    text = result[0]["text"]["text"]

    assert text.startswith("📧 *Email the EPIF to purchasing*")
    for line in blocks.request_summary_lines(request, state)[1:]:
        assert line in text
    assert f"Stage: *{state}*" in text
    if state in ("cancelled", "reassigned", "delivered"):
        assert not any(b["type"] == "actions" for b in result)
        expected = {"cancelled": "🚫 Cancelled", "reassigned": "↪️ Reassigned to another buyer", "delivered": "✅ Delivered"}[state]
        assert expected in text
    else:
        assert any(b["type"] == "actions" for b in result)


def test_sync_dm_card_rebuilds_the_whole_card():
    request = _request(payment_method="P-card", dm_channel="D_BUYER", dm_ts="999.000")
    client = MagicMock()
    client.chat_getPermalink.return_value = {"permalink": "https://example.com/thread"}

    ok = lifecycle.sync_dm_card(
        client, request, "approved", "C123", "111.222", "333.444",
        history=["Approved by the approver on 10/09/26 10:00"],
    )

    assert ok is True
    client.chat_update.assert_called_once()
    sent = client.chat_update.call_args.kwargs["blocks"]
    assert sent[0]["text"]["text"].startswith("📧 *Email the EPIF to purchasing*")
    assert sent[1]["type"] == "context"
    assert "Approved by the approver on 10/09/26 10:00" in sent[1]["elements"][0]["text"]
