"""Tests for Ticket 63: A DM the bot cannot read gets help text and a Start button.

WHY THIS EXISTS:
----------------
A lab member's first DM is often a natural sentence with a link, not a keyword.
Per ADR 0010 Decision 5 (amending ADR 0009 Decision 3 for DMs only):
In a DM only, when the first word has no close match, the bot replies with one
message containing a "Start a purchase request" button above the full help text.
In a channel mention, or in a DM with a close match, behaviour is unchanged.
Nothing from the DM is carried into the interview modal.
"""
import json
from unittest.mock import MagicMock

from src import app, blocks, roster


def _find_listener(event_type: str):
    """Find a registered listener in Bolt's real listener registry matching event_type."""
    for listener in app.app._listeners:
        for matcher in getattr(listener, "matchers", []):
            func = getattr(matcher, "func", None)
            if func and getattr(func, "__closure__", None):
                for cell in func.__closure__:
                    if cell.cell_contents == event_type:
                        return listener
    raise ValueError(f"No listener registered for event type '{event_type}'")


def _raising_respond(*args, **kwargs):
    raise ValueError("respond is unsupported here as there is no response_url")


# ---------------------------------------------------------------------------
# Acceptance Criterion 1: chunk_mrkdwn tested directly
# ---------------------------------------------------------------------------


def test_chunk_mrkdwn_get_help_message():
    """Real get_help_message chunks <= 2900 chars, none empty, rejoin to stripped original."""
    msg = blocks.get_help_message()
    chunks = blocks.chunk_mrkdwn(msg)
    assert len(chunks) > 0
    for chunk in chunks:
        assert len(chunk) <= 2900, f"Chunk exceeded 2900 chars: {len(chunk)}"
        assert len(chunk.strip()) > 0, "Empty chunk returned"
    assert "\n\n".join(chunks) == msg.strip()


def test_chunk_mrkdwn_synthetic_7000_chars():
    """Synthetic 7 000-char text of short lines packs into <= 2900 char chunks, rejoins cleanly."""
    paras = [
        "\n".join(f"Para {p} line {line_idx}: " + "x" * 40 for line_idx in range(6))
        for p in range(25)
    ]
    text = "\n\n".join(paras)
    assert len(text) >= 7000
    chunks = blocks.chunk_mrkdwn(text)
    assert len(chunks) > 1
    for chunk in chunks:
        assert len(chunk) <= 2900, f"Chunk exceeded 2900 chars: {len(chunk)}"
        assert len(chunk.strip()) > 0, "Empty chunk returned"
    assert "\n\n".join(chunks) == text.strip()


def test_chunk_mrkdwn_single_4000_char_line():
    """A single 4 000-char line is split with no chunk exceeding the limit."""
    text = "A" * 4000
    chunks = blocks.chunk_mrkdwn(text)
    assert len(chunks) > 1
    for chunk in chunks:
        assert len(chunk) <= 2900, f"Chunk exceeded 2900 chars: {len(chunk)}"
        assert len(chunk.strip()) > 0, "Empty chunk returned"


# ---------------------------------------------------------------------------
# Acceptance Criterion 2: Sentence in DM gets help and Start button
# ---------------------------------------------------------------------------


def test_dm_sentence_gets_help_and_start_button(tmp_path, monkeypatch):
    """A sentence in a DM gets exactly one say with Start button and full help text."""
    temp_roster_file = str(tmp_path / "roster.json")
    with open(temp_roster_file, "w", encoding="utf-8") as f:
        json.dump({"admins": [], "approvers": [], "buyers": [], "requesters": {}, "vendors": []}, f)
    monkeypatch.setattr(roster, "ROSTER_PATH", temp_roster_file)
    roster.load_roster()

    event = {
        "user": "U1",
        "channel": "D1",
        "channel_type": "im",
        "ts": "1.1",
        "text": "I want to purchase this: <https://example.com/x?a=1&amp;b=2|example.com/x>",
    }
    fake_client = MagicMock()
    fake_say = MagicMock()
    fake_context = {"bot_user_id": "BOT"}

    app.on_direct_message(event=event, client=fake_client, say=fake_say, context=fake_context)

    assert fake_say.call_count == 1
    call_kwargs = fake_say.call_args.kwargs
    msg_blocks = call_kwargs.get("blocks", [])
    assert msg_blocks, "Expected blocks in say call"

    # Must contain actions block with start_purchase_interview button
    action_buttons = [
        elem
        for blk in msg_blocks
        if blk.get("type") == "actions"
        for elem in blk.get("elements", [])
        if elem.get("action_id") == "start_purchase_interview"
    ]
    assert len(action_buttons) == 1, "Expected actions block with button action_id 'start_purchase_interview'"

    # Must contain a section whose text contains the first heading line of blocks.get_help_message()
    first_heading = blocks.get_help_message().split("\n\n")[0]
    section_texts = [
        blk.get("text", {}).get("text", "")
        for blk in msg_blocks
        if blk.get("type") == "section"
    ]
    assert any(first_heading in txt for txt in section_texts), (
        f"Expected section text containing first heading line '{first_heading}'"
    )


# ---------------------------------------------------------------------------
# Acceptance Criterion 3: Near-miss in DM keeps ticket 53's reply
# ---------------------------------------------------------------------------


def test_dm_near_miss_keeps_did_you_mean_without_actions(tmp_path, monkeypatch):
    """A near-miss in a DM keeps ticket 53's suggestion without an actions block."""
    temp_roster_file = str(tmp_path / "roster.json")
    with open(temp_roster_file, "w", encoding="utf-8") as f:
        json.dump({"admins": [], "approvers": [], "buyers": [], "requesters": {}, "vendors": []}, f)
    monkeypatch.setattr(roster, "ROSTER_PATH", temp_roster_file)
    roster.load_roster()

    event = {
        "user": "U1",
        "channel": "D1",
        "channel_type": "im",
        "ts": "1.1",
        "text": "remve-vendor Thorlabs",
    }
    fake_client = MagicMock()
    fake_say = MagicMock()
    fake_context = {"bot_user_id": "BOT"}

    app.on_direct_message(event=event, client=fake_client, say=fake_say, context=fake_context)

    assert fake_say.call_count == 1
    call_kwargs = fake_say.call_args.kwargs
    reply_text = call_kwargs.get("text", "")
    assert "@Purchasing remove-vendor" in reply_text

    msg_blocks = call_kwargs.get("blocks")
    if msg_blocks:
        action_blocks = [blk for blk in msg_blocks if blk.get("type") == "actions"]
        assert len(action_blocks) == 0, "Expected no actions block for near-miss suggestion"


# ---------------------------------------------------------------------------
# Acceptance Criterion 4: Channel mention is unchanged
# ---------------------------------------------------------------------------


def test_channel_mention_flurb_unchanged():
    """<@BOT> flurb in a channel mention says @Purchasing help with no blocks and no start button."""
    listener = _find_listener("app_mention")
    event = {
        "text": "<@BOT> flurb",
        "channel": "C_TEST",
        "ts": "1.1",
        "user": "U1",
    }
    fake_client = MagicMock()
    fake_say = MagicMock()
    fake_context = {
        "respond": _raising_respond,
        "bot_user_id": "BOT",
    }

    listener.ack_function(
        event=event,
        client=fake_client,
        say=fake_say,
        context=fake_context,
    )

    assert fake_say.call_count == 1
    call_kwargs = fake_say.call_args.kwargs
    reply_text = call_kwargs.get("text", "")
    assert "@Purchasing help" in reply_text

    # Absence asserted: no blocks and no start_purchase_interview anywhere
    assert call_kwargs.get("blocks") is None, "Expected no blocks in say call"
    full_call_str = str(fake_say.call_args)
    assert "start_purchase_interview" not in full_call_str


# ---------------------------------------------------------------------------
# Acceptance Criterion 5: Button opens blank form without carrying DM content
# ---------------------------------------------------------------------------


def test_button_opens_blank_form_ignoring_dm_text():
    """handle_start_purchase_interview opens blank Screen 1 without any DM URL or text."""
    fake_ack = MagicMock()
    fake_client = MagicMock()
    body = {
        "user": {"id": "U1"},
        "trigger_id": "trig_123",
        "channel": {"id": "D1"},
        "message": {
            "text": "I want to purchase this: <https://example.com/x?a=1&amp;b=2|example.com/x>",
        },
    }

    app.handle_start_purchase_interview(ack=fake_ack, body=body, client=fake_client)

    assert fake_ack.call_count == 1
    assert fake_client.views_open.call_count == 1
    open_call_kwargs = fake_client.views_open.call_args.kwargs
    assert open_call_kwargs.get("trigger_id") == "trig_123"

    opened_view = open_call_kwargs.get("view", {})
    view_dump = json.dumps(opened_view)
    assert "example.com" not in view_dump, "DM URL must not be carried into opened modal"
