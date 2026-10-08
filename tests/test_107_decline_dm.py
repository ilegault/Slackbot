"""Tests for Ticket 107: a decline DMs the requester (ADR 0016 decision 4)."""
import json
from unittest.mock import MagicMock

import pytest

from src import config, lifecycle, log_writer, roster, slack_io

CHANNEL = "C_PURCHASING"


@pytest.fixture(autouse=True)
def env(tmp_path, monkeypatch):
    roster_file = str(tmp_path / "roster.json")
    monkeypatch.setattr(roster, "ROSTER_PATH", roster_file)
    roster._DATA = None
    with open(roster_file, "w", encoding="utf-8") as f:
        json.dump({"admins": [], "approvers": ["U_APPROVER"], "buyers": [],
                   "requesters": {"U_REQ": "Alex", "U_APPROVER": "Charlie"}, "vendors": []}, f)
    monkeypatch.setattr(roster, "_trigger_roster_sync", lambda: None)
    monkeypatch.setattr(config, "PURCHASING_CHANNEL", CHANNEL)
    monkeypatch.setattr(slack_io, "_CACHED_BOT_USER_ID", "B_BOT", raising=False)
    appended = MagicMock()
    monkeypatch.setattr(log_writer, "append_row", appended)
    return appended


def _client():
    c = MagicMock()
    c.chat_getPermalink.return_value = {"permalink": "https://example.test/p1"}
    return c


def _req(user_id="U_REQ"):
    return {"parsed": {"item_description": "Tungsten rod", "vendor": "Acme", "total_price": 1234.5},
            "user_id": user_id}


def _dms(client):
    return [(c.kwargs["channel"], c.kwargs["text"]) for c in client.chat_postMessage.call_args_list]


def test_decline_dms_requester_with_exact_sentence():
    client = _client()
    lifecycle.handle_decline(client, CHANNEL, "1.1", "U_APPROVER", _req(), [])
    dms = dict((ch, t) for ch, t in _dms(client))
    assert "U_REQ" in dms
    assert dms["U_REQ"].startswith(
        "Your request for *Tungsten rod* (Acme, $1,234.50) was declined by Charlie."
    )
    assert "https://example.test/p1" in dms["U_REQ"]


def test_decline_falls_back_to_top_level_fields():
    client = _client()
    req = {"item_description": "Gloves", "vendor": "Fisher", "total_price": 20, "user_id": "U_REQ"}
    lifecycle.handle_decline(client, CHANNEL, "1.1", "U_APPROVER", req, [])
    texts = [t for ch, t in _dms(client) if ch == "U_REQ"]
    assert texts and texts[0].startswith("Your request for *Gloves* (Fisher, $20.00) was declined by")


def test_decliner_who_is_requester_gets_one_dm():
    client = _client()
    lifecycle.handle_decline(client, CHANNEL, "1.1", "U_REQ", _req("U_REQ"), [])
    assert [ch for ch, _ in _dms(client)] == ["U_REQ"]


def test_decline_writes_no_row_and_and_updates_card(env):
    client = _client()
    lifecycle.handle_decline(client, CHANNEL, "1.1", "U_APPROVER", _req(), [])
    env.assert_not_called()
    client.chat_update.assert_called_once()
