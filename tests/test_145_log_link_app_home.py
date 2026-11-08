"""Tests for Ticket 145: the Log link rule, the App Home button and the silent click.

Acceptance criteria:
- App Home's Welcome section carries an Open Purchasing Log button that opens the Log link
- A missing or non-web-address setting shows the "not set up" sentence and no `url` key anywhere
- The setting is read at render time
- A malformed setting warns once; an empty one does not
- The click is acknowledged and nothing else happens
- PURCHASING_LOG_URL is not one of the six storage settings
"""
import inspect
import os
import sys
from unittest.mock import MagicMock

import pytest
from slack_bolt import BoltRequest, BoltResponse

_CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(_CURRENT_DIR) if os.path.basename(_CURRENT_DIR) == "tests" else _CURRENT_DIR
SRC_DIR = os.path.join(PROJECT_ROOT, "src")
for p in (PROJECT_ROOT, SRC_DIR):
    if p not in sys.path:
        sys.path.insert(0, p)

from src import app, blocks, config, slack_io  # noqa: E402


def _view(monkeypatch, value):
    monkeypatch.setattr(config, "PURCHASING_LOG_URL", value)
    return blocks.build_app_home_view("U_TEST")


def _welcome(view):
    """The section right after the 'Hirst Lab Purchasing Bot' header."""
    assert view["blocks"][0]["type"] == "header"
    section = view["blocks"][1]
    assert section["type"] == "section"
    return section


def _has_url_key(node) -> bool:
    if isinstance(node, dict):
        return "url" in node or any(_has_url_key(v) for v in node.values())
    if isinstance(node, list):
        return any(_has_url_key(v) for v in node)
    return False


@pytest.mark.parametrize("raw, expected", [
    ("https://example.sharepoint.com/:x:/r/log?e=1", "https://example.sharepoint.com/:x:/r/log?e=1"),
    ("HTTP://example.org/log", "HTTP://example.org/log"),
    ("  https://example.org/log  ", "https://example.org/log"),
])
def test_app_home_button_opens_the_log_link(monkeypatch, raw, expected):
    accessory = _welcome(_view(monkeypatch, raw))["accessory"]
    assert accessory["type"] == "button"
    assert accessory["url"] == expected
    assert accessory["text"]["text"] == blocks._LOG_LINK_LABEL == "Open Purchasing Log"
    assert accessory["action_id"] == config.ACTION_OPEN_PURCHASING_LOG


@pytest.mark.parametrize("raw", ["", "www.example.com/log", "C:\\Users\\x\\Purchasing-Log.xlsx", "https://exa mple.com"])
def test_app_home_not_set_shows_the_sentence_and_no_url(monkeypatch, raw):
    view = _view(monkeypatch, raw)
    assert not _has_url_key(view)
    welcome = _welcome(view)
    assert "accessory" not in welcome
    assert blocks._LOG_LINK_NOT_SET == "The Purchasing Log link isn't set up yet. Ask an admin."
    assert blocks._LOG_LINK_NOT_SET in welcome["text"]["text"]


def test_app_home_reads_the_setting_at_render_time(monkeypatch):
    first = _view(monkeypatch, "")
    assert not _has_url_key(first)
    second = _view(monkeypatch, "https://example.org/log")
    assert _welcome(second)["accessory"]["url"] == "https://example.org/log"


def test_malformed_setting_warns_and_empty_does_not(monkeypatch, caplog):
    with caplog.at_level("WARNING"):
        _view(monkeypatch, "www.example.com/log")
    hits = [r for r in caplog.records if r.levelname == "WARNING" and "PURCHASING_LOG_URL" in r.getMessage()]
    assert len(hits) == 1
    assert "not a web address" in hits[0].getMessage()

    caplog.clear()
    with caplog.at_level("WARNING"):
        _view(monkeypatch, "")
    assert not [r for r in caplog.records if "PURCHASING_LOG_URL" in r.getMessage()]


def _click_body(action_id):
    return {
        "type": "block_actions",
        "user": {"id": "U_TEST"},
        "actions": [{"action_id": action_id, "type": "button"}],
    }


def test_log_link_click_is_acked_and_silent(monkeypatch):
    listener = next(
        (lst for lst in app.app._listeners if getattr(lst, "ack_function", None) is app.handle_open_purchasing_log_action),
        None,
    )
    assert listener is not None, "handle_open_purchasing_log_action must be registered with Bolt"

    def matches(action_id):
        return listener.matches(
            req=BoltRequest(body=_click_body(action_id), mode="socket_mode"),
            resp=BoltResponse(status=200),
        )

    assert matches(config.ACTION_OPEN_PURCHASING_LOG) is True
    assert matches("start_purchase_interview") is False

    assert list(inspect.signature(app.handle_open_purchasing_log_action).parameters) == ["ack", "body"]

    tell, deny, alert = MagicMock(), MagicMock(), MagicMock()
    monkeypatch.setattr(slack_io, "tell", tell)
    monkeypatch.setattr(slack_io, "deny", deny)
    monkeypatch.setattr(slack_io, "alert_admins", alert)
    ack = MagicMock()
    app.handle_open_purchasing_log_action(ack=ack, body=_click_body(config.ACTION_OPEN_PURCHASING_LOG))
    ack.assert_called_once()
    tell.assert_not_called()
    deny.assert_not_called()
    alert.assert_not_called()


def test_log_link_is_not_a_storage_setting():
    # It is a setting (so this fails before the ticket lands) but not one of the six storage settings.
    assert hasattr(config, "PURCHASING_LOG_URL")
    assert not any("PURCHASING_LOG_URL" in entry for entry in config.STORAGE_SETTINGS)
    assert len(config.STORAGE_SETTINGS) == 6
