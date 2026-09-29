"""Tests for Ticket 53: "Did you mean ...?" suggestions for unknown keywords.

WHY THIS EXISTS:
----------------
After Ticket 51 stopped unknown words from crashing on the event path, an unknown word
got text_rules.format_unknown_keyword_message, which listed only lifecycle keywords
and did not help with a typo.
Ticket 53 / ADR 0009 Decision 3:
An unknown word gets a public, in-thread reply. If the word is close to a real keyword,
it teaches the right command ("Did you mean `@Purchasing <suggestion>`?"), marking
admin-only commands *(admin only)*. If nothing is close, it points to `@Purchasing help`.
"""
import ast
import json
from unittest.mock import MagicMock

import pytest

from src import app, config, roster, text_rules


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


def test_closest_keyword_direct():
    """closest_keyword matches typos using the real canonical vocabulary from config."""
    vocab = getattr(config, "CANONICAL_KEYWORDS", tuple(kw[0] for kw in config.ALL_KEYWORD_TUPLES))

    assert hasattr(text_rules, "closest_keyword"), "text_rules must define closest_keyword"
    assert text_rules.closest_keyword("remve-vendor", vocab) == "remove-vendor"
    assert text_rules.closest_keyword("remve vendor", vocab) == "remove-vendor"
    assert text_rules.closest_keyword("aprooved", vocab) == "approved"
    assert text_rules.closest_keyword("flurb", vocab) is None
    assert text_rules.closest_keyword("banana", vocab) is None


def test_app_mention_suggests_admin_keyword(tmp_path, monkeypatch):
    """<@BOT> remve-vendor Thorlabs suggests @Purchasing remove-vendor and marks it admin only."""
    temp_roster_file = str(tmp_path / "roster.json")
    initial_roster = {
        "admins": ["U_ADMIN"],
        "approvers": ["U_APPROVER"],
        "buyers": ["U_BUYER"],
        "requesters": {},
        "vendors": ["Thorlabs"],
    }
    with open(temp_roster_file, "w", encoding="utf-8") as f:
        json.dump(initial_roster, f)

    monkeypatch.setattr(roster, "ROSTER_PATH", temp_roster_file)
    roster.load_roster()

    listener = _find_listener("app_mention")
    event = {
        "text": "<@BOT> remve-vendor Thorlabs",
        "channel": "C_TEST_CHANNEL",
        "ts": "1700000000.111111",
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
    assert call_kwargs.get("thread_ts") == "1700000000.111111"
    reply_text = call_kwargs.get("text", "")
    assert "@Purchasing remove-vendor" in reply_text
    assert "admin only" in reply_text.lower()

    # Roster remains intact: Thorlabs was not removed
    with open(temp_roster_file, "r", encoding="utf-8") as f:
        saved_roster = json.load(f)
    assert "Thorlabs" in saved_roster["vendors"]


def test_app_mention_suggests_admin_keyword_space_phrase(tmp_path, monkeypatch):
    """<@BOT> remve vendor Thorlabs suggests @Purchasing remove-vendor."""
    listener = _find_listener("app_mention")
    event = {
        "text": "<@BOT> remve vendor Thorlabs",
        "channel": "C_TEST_CHANNEL",
        "ts": "1700000000.222222",
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
    assert call_kwargs.get("thread_ts") == "1700000000.222222"
    reply_text = call_kwargs.get("text", "")
    assert "@Purchasing remove-vendor" in reply_text
    assert "admin only" in reply_text.lower()


def test_app_mention_no_close_match_points_to_help():
    """<@BOT> flurb says unknown word and points to @Purchasing help without 'Did you mean'."""
    listener = _find_listener("app_mention")
    event = {
        "text": "<@BOT> flurb",
        "channel": "C_TEST_CHANNEL",
        "ts": "1700000000.333333",
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
    reply_text = call_kwargs.get("text", "")
    assert "@Purchasing help" in reply_text
    assert "Did you mean" not in reply_text


def test_app_mention_lifecycle_suggestion_not_marked_admin_only():
    """<@BOT> aprooved suggests @Purchasing approved without 'admin only'."""
    listener = _find_listener("app_mention")
    event = {
        "text": "<@BOT> aprooved",
        "channel": "C_TEST_CHANNEL",
        "ts": "1700000000.444444",
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
    reply_text = call_kwargs.get("text", "")
    assert "@Purchasing approved" in reply_text
    assert "admin only" not in reply_text.lower()


def test_cutoff_lives_only_in_config():
    """KEYWORD_SUGGESTION_CUTOFF lives in config; text_rules has no numeric literal cutoff."""
    assert hasattr(config, "KEYWORD_SUGGESTION_CUTOFF"), "config must define KEYWORD_SUGGESTION_CUTOFF"
    assert config.KEYWORD_SUGGESTION_CUTOFF == 0.75
    assert hasattr(config, "ADMIN_ONLY_KEYWORDS"), "config must define ADMIN_ONLY_KEYWORDS"

    # AST check on text_rules.py: no float literal 0.75
    import inspect
    source = inspect.getsource(text_rules)
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, float) and node.value == 0.75:
            pytest.fail("Found literal 0.75 in text_rules.py; cutoff must come from config.KEYWORD_SUGGESTION_CUTOFF")
