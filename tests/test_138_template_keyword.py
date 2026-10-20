"""Ticket 138: ``@Purchasing template`` is no longer a keyword.

The template kit comes only from ``/blank-template`` (ADR 0002: a thing with no
target is a slash command). Typing the old keyword gets the ordinary unknown-word
reply, and nothing is uploaded to the channel.
"""
from unittest.mock import MagicMock

from src import app, config


def test_template_is_not_a_keyword():
    assert not hasattr(config, "TEMPLATE_KEYWORDS")
    removed = {"template", "blank epif", "blank form"}
    for group in config.ALL_KEYWORD_TUPLES:
        assert not removed & set(group)
    assert "template" not in config.CANONICAL_KEYWORDS


def test_template_mention_gets_the_unknown_word_reply():
    client = MagicMock()
    say = MagicMock()

    app.dispatch_command(
        client=client,
        say=say,
        channel="C_TEST",
        thread_ts="5555.66",
        user="U123",
        event_ts="5555.67",
        text="@Purchasing template",
    )

    say.assert_called_once()
    assert "I don't know \"template\"" in say.call_args[1]["text"]
    client.files_upload_v2.assert_not_called()
