"""Tests for Ticket 94: the approved nudge (ADR 0013 decision 1).

Temp request log, settings and roster; real nudge, nudge_settings, store and roster;
only the Slack client and log_writer.get_row_info are faked.
"""
import json
from datetime import date

import pytest

from src import log_writer, nudge_settings, roster, store
from src.nudge import run_nudges
from tests.test_78_nudge_assigned import _make_fake_client, _make_thread_card_message

CHANNEL = "C_PURCHASING"
LINK = "https://slack.com/archives/C123/p111"
ON = {"enabled": True, "every": 3, "dm": True, "channel": False}


@pytest.fixture(autouse=True)
def env(tmp_path, monkeypatch):
    rf = str(tmp_path / "roster.json")
    monkeypatch.setattr(roster, "ROSTER_PATH", rf)
    roster._DATA = None
    with open(rf, "w", encoding="utf-8") as f:
        json.dump({"admins": ["U_ADMIN"], "approvers": ["U_A1", "U_A2"], "buyers": ["U_B"],
                   "requesters": {}, "vendors": []}, f)
    monkeypatch.setattr(roster, "_trigger_roster_sync", lambda: None)
    monkeypatch.setattr(log_writer, "get_row_info", lambda row: {})


def _settings(**approved):
    s = json.loads(json.dumps(nudge_settings.DEFAULTS))
    s["approved"] = {**ON, **approved}
    nudge_settings.save(s)


def _setup(card_state="posted", **entry):
    req = {"item_description": "Laser Diode", "total_price": 120.0}
    card = _make_thread_card_message(ts="111.200", state=card_state, req_data=req)
    client = _make_fake_client({"111.200": card})
    fields = dict(posted_at="2026-10-05T09:00:00", requester="Alex")
    fields.update(entry)
    req_id = store.create(channel=CHANNEL, thread_ts="111.100", card_ts="111.200", **fields)
    return client, req_id


def _dms(client):
    return {c[1]["channel"]: c[1]["text"] for c in client.chat_postMessage.call_args_list}


def test_off_by_default():
    client, _ = _setup()
    assert run_nudges(client, date(2026, 10, 8)) == []
    assert client.chat_postMessage.call_count == 0
    _settings()  # control: the same entry is nudged once an admin turns it on
    assert len(run_nudges(client, date(2026, 10, 8))) == 1


def test_day_3_dms_every_approver_only_then():
    _settings()
    client, req_id = _setup()
    assert run_nudges(client, date(2026, 10, 7)) == []
    assert client.chat_postMessage.call_count == 0
    assert run_nudges(client, date(2026, 10, 8)) == [req_id]
    dms = _dms(client)
    assert set(dms) == {"U_A1", "U_A2"}
    assert client.chat_postMessage.call_count == 2
    for text in dms.values():
        assert "waiting for approval for 3 working days" in text
        assert LINK in text and "Laser Diode" in text and "Alex" in text
    for c in client.chat_postMessage.call_args_list:
        assert not any(b.get("type") == "actions" for b in c[1].get("blocks") or [])
        assert not c[1].get("thread_ts")
    assert store.get(req_id)["last_nudged"] == "2026-10-08"


def test_channel_option_broadcasts_thread_reply_no_dm():
    _settings(dm=False, channel=True)
    client, _ = _setup()
    run_nudges(client, date(2026, 10, 8))
    assert client.chat_postMessage.call_count == 1
    kw = client.chat_postMessage.call_args[1]
    assert kw["channel"] == CHANNEL and kw["thread_ts"] == "111.100"
    assert kw["reply_broadcast"] is True
    assert "<@U_A1>" in kw["text"] and "<@U_A2>" in kw["text"]


@pytest.mark.parametrize("entry,card_state", [
    ({"declined": True}, "posted"),
    ({"superseded": True}, "posted"),
    ({"approved_at": "2026-10-06T09:00:00"}, "posted"),
    ({}, "approved"),
    ({"last_nudged": "2026-10-08"}, "posted"),
])
def test_stops(entry, card_state):
    _settings()
    client, stopped = _setup(card_state=card_state, **entry)
    # control entry in the same log and thread: identical but with no stop reason
    control_card = _make_thread_card_message(ts="111.300", state="posted", req_data={"item_description": "Probe"})
    posted = client.conversations_replies.side_effect("C", ts="111.100")["messages"]
    client.conversations_replies.side_effect = lambda channel, ts=None, **kw: {
        "ok": True, "messages": posted + [control_card]}
    control = store.create(channel=CHANNEL, thread_ts="111.100", card_ts="111.300",
                           posted_at="2026-10-05T09:00:00", requester="Alex")
    assert run_nudges(client, date(2026, 10, 8)) == [control]
    assert all("Laser Diode" not in c[1]["text"] for c in client.chat_postMessage.call_args_list)
    assert stopped not in store.load_store() or store.get(stopped).get("last_nudged") == entry.get("last_nudged")


def test_day_6_repeats():
    _settings()
    client, _ = _setup(last_nudged="2026-10-08")
    run_nudges(client, date(2026, 10, 13))
    assert set(_dms(client)) == {"U_A1", "U_A2"}
    assert "6 working days" in _dms(client)["U_A1"]
