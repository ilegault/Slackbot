"""Tests for Ticket 33: A corrected EPIF supersedes the old card.

WHY THIS EXISTS:
----------------
Covers ADR 0006 decision 9: when an EPIF is dropped in a thread that already has a
posted card from the same requester for the same vendor, the older card is rewritten
as 'superseded' (no buttons, context line, history appended) and the new card is
posted normally.

Acceptance criteria exercised:
1. A second EPIF for the same vendor from the same requester rewrites the older posted
   card with no buttons and a line saying it was superseded.
2. The superseded card keeps its summary text.
3. The new card is posted as usual with its own buttons.
4. An EPIF for a different vendor leaves the existing card untouched — asserted on the
   absence of a chat_update call.
5. An EPIF from a different requester leaves the existing card untouched.
6. An approved card in the thread is never superseded.
7. Vendor comparison ignores case and surrounding whitespace.
8. Line items on a superseded card do not appear on the new card.
"""
from unittest.mock import MagicMock, patch

import pytest

from src import blocks, lifecycle, slack_io

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_parsed_epif(
    vendor="Ruland",
    total_price=100.0,
    item_description="Couplings",
    fund="133",
):
    return {
        "item_description": item_description,
        "total_price": total_price,
        "vendor": vendor,
        "payment_method": "EPIF",
        "category": "Research/Lab Supplies (3105)",
        "project_id": "PG000025831",
        "fund": fund,
        "delivery_room": "ERB 212",
        "purpose": "Shaft alignment",
        "link": "https://example.com",
        "date_of_purchase": None,
    }


def _make_posted_card_message(
    ts="1000.100",
    thread_ts="1000.000",
    user_id="U_ISAAC",
    requester="Isaac",
    vendor="Ruland",
    state="posted",
    items=None,
    shipping=0.0,
):
    """Build a fake Slack message dict representing an existing posted card."""
    parsed = _make_parsed_epif(vendor=vendor)
    payload = {
        "parsed": parsed,
        "requester": requester,
        "user_id": user_id,
        "is_pending_name": False,
        "thread_ts": thread_ts,
        "source": "epif",
    }
    if items is not None:
        payload["items"] = items
        payload["shipping"] = shipping

    card_blocks = blocks.build_request_blocks(state, payload, items=items)

    return {
        "ts": ts,
        "thread_ts": thread_ts,
        "text": f"🛒 Purchase Request ({state.capitalize()})",
        "blocks": card_blocks,
        "metadata": {
            "event_type": "purchase_request",
            "event_payload": payload,
        },
    }


def _make_client_with_thread(messages):
    """Fake Slack client whose conversations_replies returns the given messages."""
    client = MagicMock()
    client.conversations_replies.return_value = {"messages": messages}
    client.chat_postMessage.return_value = {"ts": "2000.200"}
    return client


def _run_epif_drop(client, vendor="Ruland", user_id="U_ISAAC", thread_ts="1000.000"):
    """Call handle_epif_drop with a mocked download and epif_parser."""
    parsed_epif = _make_parsed_epif(vendor=vendor)
    with (
        patch("src.lifecycle.slack_io.download", return_value=b"%PDF-fake"),
        patch("src.lifecycle.epif_parser.parse_epif", return_value=parsed_epif),
        patch("src.lifecycle.slack_io.resolve_requester", return_value="Isaac"),
    ):
        lifecycle.handle_epif_drop(
            client=client,
            say=lambda **kw: None,
            channel="C_PURCHASE",
            thread_ts=thread_ts,
            user_id=user_id,
            file_obj={"name": "epif.pdf", "url_private_download": "https://fake"},
            event_ts="2000.000",
        )


# ---------------------------------------------------------------------------
# 1. Same vendor + same requester → older posted card is superseded
# ---------------------------------------------------------------------------

def test_same_vendor_same_requester_supersedes_older_card():
    """AC1: A second EPIF for the same vendor from the same requester rewrites the older
    posted card with no buttons and a line saying it was superseded."""
    old_card = _make_posted_card_message(
        ts="1000.100", thread_ts="1000.000",
        user_id="U_ISAAC", vendor="Ruland", state="posted",
    )
    client = _make_client_with_thread([old_card])

    _run_epif_drop(client, vendor="Ruland", user_id="U_ISAAC")

    # chat_update must have been called once for the old card
    client.chat_update.assert_called_once()
    call_kwargs = client.chat_update.call_args[1]
    assert call_kwargs["ts"] == "1000.100"
    assert call_kwargs["channel"] == "C_PURCHASE"

    # The blocks sent must contain no actions block (no buttons)
    sent_blocks = call_kwargs["blocks"]
    action_blocks = [b for b in sent_blocks if b.get("type") == "actions"]
    assert action_blocks == [], "Superseded card must have no buttons"


# ---------------------------------------------------------------------------
# 2. Superseded card keeps its summary text
# ---------------------------------------------------------------------------

def test_superseded_card_keeps_summary_text():
    """AC2: The superseded card keeps its summary text."""
    old_card = _make_posted_card_message(
        ts="1000.100", user_id="U_ISAAC", vendor="Ruland", state="posted",
    )
    client = _make_client_with_thread([old_card])

    _run_epif_drop(client, vendor="Ruland", user_id="U_ISAAC")

    sent_blocks = client.chat_update.call_args[1]["blocks"]
    section_blocks = [b for b in sent_blocks if b.get("type") == "section"]
    assert section_blocks, "Superseded card must still have a section block (summary)"
    summary_text = section_blocks[0]["text"]["text"]
    # The original summary contains the requester name and item
    assert "Isaac" in summary_text
    assert "Couplings" in summary_text


# ---------------------------------------------------------------------------
# 2b. Context block reads "Superseded by a newer EPIF below"
# ---------------------------------------------------------------------------

def test_superseded_card_has_context_line():
    """The rewritten card has a context block with the superseded message."""
    old_card = _make_posted_card_message(
        ts="1000.100", user_id="U_ISAAC", vendor="Ruland", state="posted",
    )
    client = _make_client_with_thread([old_card])

    _run_epif_drop(client, vendor="Ruland", user_id="U_ISAAC")

    sent_blocks = client.chat_update.call_args[1]["blocks"]
    context_texts = []
    for b in sent_blocks:
        if b.get("type") == "context":
            for elem in b.get("elements", []):
                context_texts.append(elem.get("text", ""))
    assert any("Superseded by a newer EPIF below" in t for t in context_texts), (
        f"Expected 'Superseded by a newer EPIF below' in context blocks; got: {context_texts}"
    )


# ---------------------------------------------------------------------------
# 3. New card is posted as usual with its own Approve button
# ---------------------------------------------------------------------------

def test_new_card_is_posted_with_approve_button():
    """AC3: The new card is posted as usual with its own buttons."""
    old_card = _make_posted_card_message(
        ts="1000.100", user_id="U_ISAAC", vendor="Ruland", state="posted",
    )
    client = _make_client_with_thread([old_card])

    _run_epif_drop(client, vendor="Ruland", user_id="U_ISAAC")

    client.chat_postMessage.assert_called_once()
    call_kwargs = client.chat_postMessage.call_args[1]
    posted_blocks = call_kwargs["blocks"]
    action_blocks = [b for b in posted_blocks if b.get("type") == "actions"]
    assert action_blocks, "New card must have an actions block with buttons"
    action_ids = [e.get("action_id") for e in action_blocks[0]["elements"]]
    assert "req_approve" in action_ids, "New card must have an Approve button"


# ---------------------------------------------------------------------------
# 4. Different vendor → card untouched (assert absence of chat_update)
# ---------------------------------------------------------------------------

def test_different_vendor_leaves_card_untouched():
    """AC4: An EPIF for a different vendor in the same thread leaves the existing
    card untouched — asserted on the absence of a chat_update call."""
    old_card = _make_posted_card_message(
        ts="1000.100", user_id="U_ISAAC", vendor="Acme", state="posted",
    )
    client = _make_client_with_thread([old_card])

    _run_epif_drop(client, vendor="Ruland", user_id="U_ISAAC")

    client.chat_update.assert_not_called()


# ---------------------------------------------------------------------------
# 5. Different requester → card untouched
# ---------------------------------------------------------------------------

def test_different_requester_leaves_card_untouched():
    """AC5: An EPIF from a different requester leaves the existing card untouched."""
    old_card = _make_posted_card_message(
        ts="1000.100", user_id="U_DYLAN", vendor="Ruland", state="posted",
    )
    client = _make_client_with_thread([old_card])

    _run_epif_drop(client, vendor="Ruland", user_id="U_ISAAC")

    client.chat_update.assert_not_called()


# ---------------------------------------------------------------------------
# 6. Approved card is never superseded
# ---------------------------------------------------------------------------

def test_approved_card_is_never_superseded():
    """AC6: An approved card in the thread is never superseded, whatever is uploaded."""
    approved_card = _make_posted_card_message(
        ts="1000.100", user_id="U_ISAAC", vendor="Ruland", state="approved",
    )
    client = _make_client_with_thread([approved_card])

    _run_epif_drop(client, vendor="Ruland", user_id="U_ISAAC")

    client.chat_update.assert_not_called()


@pytest.mark.parametrize("state", ["processed", "confirmed", "delivered"])
def test_post_approval_states_never_superseded(state):
    """Post-approval states (processed, confirmed, delivered) are never superseded."""
    card = _make_posted_card_message(
        ts="1000.100", user_id="U_ISAAC", vendor="Ruland", state=state,
    )
    client = _make_client_with_thread([card])

    _run_epif_drop(client, vendor="Ruland", user_id="U_ISAAC")

    client.chat_update.assert_not_called()


# ---------------------------------------------------------------------------
# 7. Vendor comparison ignores case and surrounding whitespace
# ---------------------------------------------------------------------------

def test_vendor_comparison_case_insensitive():
    """AC7: Vendor comparison ignores case."""
    old_card = _make_posted_card_message(
        ts="1000.100", user_id="U_ISAAC", vendor="RULAND", state="posted",
    )
    client = _make_client_with_thread([old_card])

    _run_epif_drop(client, vendor="ruland", user_id="U_ISAAC")

    client.chat_update.assert_called_once()


def test_vendor_comparison_trims_whitespace():
    """AC7: Vendor comparison trims surrounding whitespace."""
    old_card = _make_posted_card_message(
        ts="1000.100", user_id="U_ISAAC", vendor="  Ruland  ", state="posted",
    )
    client = _make_client_with_thread([old_card])

    _run_epif_drop(client, vendor="Ruland", user_id="U_ISAAC")

    client.chat_update.assert_called_once()


# ---------------------------------------------------------------------------
# 8. Line items on a superseded card do not appear on the new card
# ---------------------------------------------------------------------------

def test_line_items_do_not_carry_to_new_card():
    """AC8: Line items on the superseded card do not appear on the new card."""
    old_items = [
        {"qty": 2, "name": "Coupling A", "part_number": "RA12", "unit_price": 25.0,
         "link": "", "description": ""},
        {"qty": 1, "name": "Coupling B", "part_number": "RB34", "unit_price": 50.0,
         "link": "", "description": ""},
    ]
    old_card = _make_posted_card_message(
        ts="1000.100", user_id="U_ISAAC", vendor="Ruland", state="posted",
        items=old_items, shipping=0.0,
    )
    client = _make_client_with_thread([old_card])

    _run_epif_drop(client, vendor="Ruland", user_id="U_ISAAC")

    # New card metadata must not carry the old items
    call_kwargs = client.chat_postMessage.call_args[1]
    new_payload = call_kwargs["metadata"]["event_payload"]
    assert "items" not in new_payload or new_payload["items"] is None or new_payload["items"] == [], (
        "New card must not carry items from the superseded card"
    )


# ---------------------------------------------------------------------------
# build_request_blocks("superseded") unit tests
# ---------------------------------------------------------------------------

def test_superseded_blocks_have_no_action_buttons():
    """build_request_blocks('superseded') produces no actions block."""
    req = {
        "parsed": _make_parsed_epif(),
        "requester": "Isaac",
        "user_id": "U_ISAAC",
        "is_pending_name": False,
        "source": "epif",
    }
    blks = blocks.build_request_blocks("superseded", req)
    action_blocks = [b for b in blks if b.get("type") == "actions"]
    assert action_blocks == [], "Superseded state must produce no buttons"


def test_superseded_blocks_have_context_line():
    """build_request_blocks('superseded') includes the 'Superseded by a newer EPIF below' context."""
    req = {
        "parsed": _make_parsed_epif(),
        "requester": "Isaac",
        "user_id": "U_ISAAC",
        "is_pending_name": False,
        "source": "epif",
    }
    blks = blocks.build_request_blocks("superseded", req)
    context_texts = []
    for b in blks:
        if b.get("type") == "context":
            for elem in b.get("elements", []):
                context_texts.append(elem.get("text", ""))
    assert any("Superseded by a newer EPIF below" in t for t in context_texts)


def test_superseded_blocks_keep_summary():
    """build_request_blocks('superseded') keeps the summary section block."""
    req = {
        "parsed": _make_parsed_epif(vendor="Ruland", item_description="Widget"),
        "requester": "Dylan",
        "user_id": "U_DYLAN",
        "is_pending_name": False,
        "source": "epif",
    }
    blks = blocks.build_request_blocks("superseded", req)
    section_blocks = [b for b in blks if b.get("type") == "section"]
    assert section_blocks, "Superseded state must keep the summary section"
    text = section_blocks[0]["text"]["text"]
    assert "Widget" in text
    assert "Dylan" in text


def test_superseded_blocks_include_history():
    """build_request_blocks('superseded') includes the history context block."""
    req = {
        "parsed": _make_parsed_epif(),
        "requester": "Isaac",
        "user_id": "U_ISAAC",
        "is_pending_name": False,
        "source": "epif",
    }
    history = ["Approved by Charlie on 01/01/26 10:00", "Superseded by a newer EPIF on 01/02/26 09:00"]
    blks = blocks.build_request_blocks("superseded", req, history=history)
    # There should be a context block containing the history text
    history_found = False
    for b in blks:
        if b.get("type") == "context":
            for elem in b.get("elements", []):
                if "History:" in elem.get("text", ""):
                    history_found = True
    assert history_found, "Superseded blocks must include history context block"


# ---------------------------------------------------------------------------
# find_posted_cards_in_thread unit tests
# ---------------------------------------------------------------------------

def test_find_posted_cards_returns_matching_card():
    """find_posted_cards_in_thread returns the posted card matching user_id + vendor."""
    old_card = _make_posted_card_message(
        ts="1000.100", user_id="U_ISAAC", vendor="Ruland", state="posted",
    )
    client = _make_client_with_thread([old_card])

    results = slack_io.find_posted_cards_in_thread(
        client, "C_PURCHASE", "1000.000", user_id="U_ISAAC", vendor="Ruland",
    )
    assert len(results) == 1
    assert results[0][0] == "1000.100"


def test_find_posted_cards_excludes_approved():
    """find_posted_cards_in_thread must not return approved cards."""
    approved = _make_posted_card_message(
        ts="1000.100", user_id="U_ISAAC", vendor="Ruland", state="approved",
    )
    client = _make_client_with_thread([approved])

    results = slack_io.find_posted_cards_in_thread(
        client, "C_PURCHASE", "1000.000", user_id="U_ISAAC", vendor="Ruland",
    )
    assert results == []


def test_find_posted_cards_excludes_different_vendor():
    """find_posted_cards_in_thread must not return cards for a different vendor."""
    card = _make_posted_card_message(
        ts="1000.100", user_id="U_ISAAC", vendor="Acme", state="posted",
    )
    client = _make_client_with_thread([card])

    results = slack_io.find_posted_cards_in_thread(
        client, "C_PURCHASE", "1000.000", user_id="U_ISAAC", vendor="Ruland",
    )
    assert results == []


def test_find_posted_cards_excludes_different_user():
    """find_posted_cards_in_thread must not return cards from a different user."""
    card = _make_posted_card_message(
        ts="1000.100", user_id="U_DYLAN", vendor="Ruland", state="posted",
    )
    client = _make_client_with_thread([card])

    results = slack_io.find_posted_cards_in_thread(
        client, "C_PURCHASE", "1000.000", user_id="U_ISAAC", vendor="Ruland",
    )
    assert results == []
