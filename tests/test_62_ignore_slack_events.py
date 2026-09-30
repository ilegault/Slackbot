"""Tests for Ticket 62: The bot ignores Slack's own message events.

WHY THIS EXISTS:
----------------
In production a member's DM containing a link was followed two seconds later by a second
message event with no user and empty text — Slack editing the message when it unfurled
the link. on_direct_message in src/app.py only returned early for subtype == "bot_message"
or a bot_id, so the edit event reached dispatch_command as if a person had typed nothing.
After ticket 51 stops the crash, the bot would answer that event with an "I don't know"
reply nobody asked for.

Per ADR 0010 Decision 6:
Slack's own events are not messages from people. A message event with no user, or with a
subtype other than a plain message, file share, or thread broadcast (e.g. edits, link unfurls,
deletions), is ignored. It never reaches the dispatcher.
"""
import logging
from unittest.mock import MagicMock

from src import app, blocks, lifecycle


def test_on_direct_message_is_registered_listener():
    """Verify app.on_direct_message is registered in Bolt's real listener registry."""
    found = [
        listener
        for listener in app.app._listeners
        if getattr(listener, "ack_function", None) is app.on_direct_message
    ]
    assert len(found) == 1, (
        "app.on_direct_message must be the ack_function of a listener in app.app._listeners"
    )


def test_edit_event_with_no_user_does_nothing(caplog):
    """An edit event with no user does nothing and logs nothing at INFO."""
    event = {
        "type": "message",
        "subtype": "message_changed",
        "channel": "D1",
        "channel_type": "im",
        "message": {"text": "x"},
    }
    fake_client = MagicMock()
    fake_say = MagicMock()

    with caplog.at_level(logging.INFO):
        app.on_direct_message(event=event, client=fake_client, say=fake_say)

    assert not fake_say.called
    assert fake_client.mock_calls == []
    assert not any("Received DM" in record.message for record in caplog.records)


def test_deletion_by_real_user_does_nothing(caplog):
    """A deletion by a real user does nothing and logs nothing at INFO."""
    event = {
        "type": "message",
        "user": "U1",
        "subtype": "message_deleted",
        "channel": "D1",
        "channel_type": "im",
    }
    fake_client = MagicMock()
    fake_say = MagicMock()

    with caplog.at_level(logging.INFO):
        app.on_direct_message(event=event, client=fake_client, say=fake_say)

    assert not fake_say.called
    assert fake_client.mock_calls == []
    assert not any("Received DM" in record.message for record in caplog.records)


def test_person_dm_still_works():
    """A person's DM still works and routes to help."""
    event = {
        "user": "U1",
        "channel": "D1",
        "channel_type": "im",
        "ts": "1.1",
        "text": "help",
    }
    fake_client = MagicMock()
    fake_say = MagicMock()

    app.on_direct_message(event=event, client=fake_client, say=fake_say)

    assert fake_say.call_count == 1
    call_kwargs = fake_say.call_args[1]
    assert blocks.get_help_message() in call_kwargs.get("text", "")


def test_dropped_pdf_reaches_drop_handler(monkeypatch):
    """A dropped PDF in a channel still reaches the lifecycle.handle_epif_drop handler."""
    calls = []

    def fake_handle_epif_drop(**kwargs):
        calls.append(kwargs)

    monkeypatch.setattr(lifecycle, "handle_epif_drop", fake_handle_epif_drop)

    event = {
        "subtype": "file_share",
        "channel": "C1",
        "channel_type": "channel",
        "ts": "2.2",
        "user": "U1",
        "files": [{"name": "EPIF_x.pdf"}],
    }
    fake_client = MagicMock()
    fake_say = MagicMock()

    app.on_direct_message(event=event, client=fake_client, say=fake_say)

    assert len(calls) == 1
    call_data = calls[0]
    assert call_data["channel"] == "C1"
    assert call_data["thread_ts"] == "2.2"
    assert call_data["user_id"] == "U1"
