"""Tests for Ticket 51: Unknown word in app_mention or DM no longer crashes the bot.

WHY THIS EXISTS:
----------------
On 2026-09-28, typing an unknown word in an @Purchasing mention or DM crashed the bot in
production with `ValueError: respond is unsupported here as there is no response_url`.
Bolt puts a `respond` object in the event context, but calling it raises because events
have no response_url.

Per ADR 0009 Decision 2:
A mention or DM never replies through respond. Replies on those paths go through say in
the thread. slack_io.deny is for slash commands and block actions only.
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


def test_unknown_word_app_mention_does_not_crash():
    """An unknown word in an app_mention replies via say in thread and does not call respond."""
    listener = _find_listener("app_mention")

    event = {
        "text": "<@BOT> flurb",
        "channel": "C_TEST_CHANNEL",
        "ts": "1700000000.123456",
        "user": "U_USER",
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
    assert call_kwargs.get("thread_ts") == "1700000000.123456"
    assert "flurb" in call_kwargs.get("text", "")


def test_unknown_word_dm_does_not_crash():
    """An unknown word in a direct message replies via say and does not call respond."""
    listener = _find_listener("message")

    event = {
        "text": "flurb",
        "channel": "D_TEST_DM",
        "ts": "1700000000.654321",
        "user": "U_USER",
        "channel_type": "im",
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
    # Under ADR 0010 Decision 5 (Ticket 63): an unknown word in DM with no close match gets help text
    assert blocks.get_help_message() in call_kwargs.get("text", "")


def test_event_path_denial_goes_to_thread_and_leaves_roster_intact(tmp_path, monkeypatch):
    """A non-admin sending remove-member via mention replies in-thread via say without calling respond."""
    temp_roster_file = str(tmp_path / "roster.json")
    initial_roster = {
        "admins": ["U_ADMIN"],
        "approvers": ["U_APPROVER"],
        "buyers": ["U_BUYER"],
        "requesters": {
            "U_ADMIN": "Admin User",
            "U_APPROVER": "Approver User",
            "U_BUYER": "Buyer User",
            "U2": "Member Two",
        },
        "vendors": ["Thorlabs"],
    }
    with open(temp_roster_file, "w", encoding="utf-8") as f:
        json.dump(initial_roster, f)

    monkeypatch.setattr(roster, "ROSTER_PATH", temp_roster_file)
    roster.load_roster()

    listener = _find_listener("app_mention")
    event = {
        "text": "@Purchasing remove-member <@U2>",
        "channel": "C_TEST_CHANNEL",
        "ts": "1700000000.999999",
        "user": "U_NON_ADMIN",
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
    assert "Only bot administrators" in call_kwargs.get("text", "")

    # Assert absence of removal: U2 is still present in the roster file
    with open(temp_roster_file, "r", encoding="utf-8") as f:
        saved_roster = json.load(f)
    assert "U2" in saved_roster["requesters"]
