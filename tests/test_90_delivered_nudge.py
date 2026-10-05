"""Tests for Ticket 90: the delivered nudge and the nudge card.

nudge, nudge_settings, store, blocks, admin and the app action handler are real on temp
files; only the Slack client, log_writer.get_row_info and (for the click) the thread-card
read and lifecycle.handle_delivery are faked. 46300 is the Excel serial for Monday
2026-10-05, so day 10 is 2026-10-19 and day 20 is 2026-11-02.
"""
import copy
import json
from datetime import date
from unittest.mock import MagicMock

import pytest

from src import app, config, lifecycle, log_writer, nudge_settings, roster, slack_io, store, text_rules
from src.blocks import build_nudge_card_blocks
from src.nudge import run_nudges
from tests.test_78_nudge_assigned import _make_fake_client, _make_thread_card_message

DAY_9 = date(2026, 10, 16)
DAY_10 = date(2026, 10, 19)
DAY_20 = date(2026, 11, 2)


@pytest.fixture
def clean_roster(tmp_path, monkeypatch):
    roster_file = str(tmp_path / "roster.json")
    monkeypatch.setattr(roster, "ROSTER_PATH", roster_file)
    roster._DATA = None
    with open(roster_file, "w", encoding="utf-8") as f:
        json.dump({"admins": [], "approvers": [], "buyers": ["U_B"],
                   "requesters": {"U_B": "Dylan", "U_R": "Alex", "U_X": "Stranger"},
                   "vendors": []}, f)
    yield
    roster._DATA = None


def _setup(monkeypatch, confirmed="46300", delivered="", state="confirmed"):
    monkeypatch.setattr(log_writer, "get_row_info", lambda row: {
        "date_processed": "46300", "date_confirmed": confirmed, "date_delivered": delivered})
    req_data = {"item_description": "Laser Diode", "vendor": "Thorlabs", "total_price": 120.0,
                "row": 18, "assignee_id": "U_B", "user_id": "U_R"}
    card = _make_thread_card_message(ts="111.200", state=state, req_data=req_data)
    client = _make_fake_client({"111.200": card})
    req_id = store.create(
        channel="C_PURCHASING", thread_ts="111.100", card_ts="111.200",
        requester="Alex", buyer="Dylan", buyer_id="U_B", rows=[18],
        buyer_set_at="2026-09-01T09:00:00", approved_at="2026-09-01T09:00:00",
        cancelled=False, last_nudged=None,
    )
    return client, req_id


def _posts(client):
    return [c[1] for c in client.chat_postMessage.call_args_list]


def _buttons(blocks):
    return [e for b in blocks if b.get("type") == "actions" for e in b.get("elements", [])]


def test_day_10_posts_card_to_channel(monkeypatch):
    client, req_id = _setup(monkeypatch)
    assert run_nudges(client, DAY_9) == []
    assert client.chat_postMessage.call_count == 0
    assert run_nudges(client, DAY_10) == [req_id]
    posts = _posts(client)
    assert len(posts) == 1
    p = posts[0]
    assert p["channel"] == "C_PURCHASING" and p["thread_ts"] == "111.100"
    assert p["reply_broadcast"] is True
    text = json.dumps(p["blocks"])
    assert "<@U_B>" in text and "<@U_R>" in text
    assert "Has this been delivered?" in text
    assert "confirmed 10 working days ago" in text
    assert [b["action_id"] for b in _buttons(p["blocks"])] == ["nudge_delivered"]
    entry = store.get(req_id)
    assert entry["nudge_cards"] == [["C_PURCHASING", "post_ts_1"]]
    assert entry["last_nudged"] == "2026-10-19"


def test_dm_option(monkeypatch):
    s = copy.deepcopy(nudge_settings.DEFAULTS)
    s["delivered"].update(enabled=True, every=10, dm=True, channel=False)
    nudge_settings.save(s)
    client, req_id = _setup(monkeypatch)
    assert run_nudges(client, DAY_10) == [req_id]
    posts = _posts(client)
    assert sorted(p["channel"] for p in posts) == ["U_B", "U_R"]
    assert not any(p.get("reply_broadcast") for p in posts)
    assert all("nudge_delivered" in json.dumps(p["blocks"]) for p in posts)
    assert len(store.get(req_id)["nudge_cards"]) == 2


def test_requester_same_as_buyer_mentioned_once(monkeypatch):
    client, _ = _setup(monkeypatch)
    entry_id = store.find_id_by_card("C_PURCHASING", "111.200")
    store.update(entry_id, buyer_id="U_R")
    run_nudges(client, DAY_10)
    assert json.dumps(_posts(client)[0]["blocks"]).count("<@U_R>") == 1


def test_one_live_card(monkeypatch):
    client, req_id = _setup(monkeypatch)
    run_nudges(client, DAY_10)
    assert client.chat_update.call_count == 0
    run_nudges(client, DAY_20)
    old = [c[1] for c in client.chat_update.call_args_list if c[1].get("ts") == "post_ts_1"]
    assert len(old) == 1
    assert "Replaced by a newer reminder." in json.dumps(old[0]["blocks"])
    assert not _buttons(old[0]["blocks"])
    # the replacement is posted after the retirement and is the only live card
    assert len(_posts(client)) == 2
    assert store.get(req_id)["nudge_cards"] == [["C_PURCHASING", "post_ts_2"]]


@pytest.mark.parametrize("kwargs", [{"delivered": "46310"}, {"state": "delivered"}, {"state": "processed"}])
def test_stops(monkeypatch, kwargs):
    client, _ = _setup(monkeypatch, **kwargs)
    assert run_nudges(client, DAY_10) == []
    assert client.chat_postMessage.call_count == 0


def test_disabled(monkeypatch):
    s = copy.deepcopy(nudge_settings.DEFAULTS)
    s["delivered"]["enabled"] = False
    nudge_settings.save(s)
    client, _ = _setup(monkeypatch)
    assert run_nudges(client, DAY_10) == []
    assert client.chat_postMessage.call_count == 0


def test_confirmed_nudge_does_not_fire_once_confirmed(monkeypatch):
    s = copy.deepcopy(nudge_settings.DEFAULTS)
    s["delivered"]["enabled"] = False
    nudge_settings.save(s)
    client, _ = _setup(monkeypatch)
    assert run_nudges(client, date(2026, 10, 12)) == []
    assert client.chat_postMessage.call_count == 0


def test_inactive_card_has_note_and_no_actions():
    for state in ("replaced", "delivered", "closed"):
        blocks = build_nudge_card_blocks(state, "<@U_B>", "Laser Diode", 10, "C", "1.1", "1.2", note="a note")
        assert not _buttons(blocks)
        assert "a note" in json.dumps(blocks) and "Has this been delivered?" in json.dumps(blocks)


# ---- the button -------------------------------------------------------------

def _click(monkeypatch, user_id, state="confirmed", cards=(("C_PURCHASING", "900.1"), ("D_R", "900.2"))):
    req = {"item_description": "Widget", "row": 15, "total_price": 42.0,
           "assignee_id": "U_B", "user_id": "U_R"}
    monkeypatch.setattr(slack_io, "get_card_by_ts", lambda *a, **k: (req, ["h"], state))
    calls = []
    monkeypatch.setattr(lifecycle, "handle_delivery", lambda **kw: calls.append(kw))
    store.create(channel="C_PURCHASING", thread_ts="111.100", card_ts="111.200",
                 requester="Alex", buyer_id="U_B", nudge_cards=[list(c) for c in cards])
    body = {"user": {"id": user_id}, "channel": {"id": "D_R"}, "message": {"ts": "900.2"},
            "actions": [{"action_id": "nudge_delivered", "value": json.dumps(
                {"thread_channel": "C_PURCHASING", "thread_ts": "111.100", "card_ts": "111.200"})}]}
    ack, respond, client = MagicMock(), MagicMock(), MagicMock()
    app.handle_nudge_delivered_action(ack, body, respond, client)
    ack.assert_called_once()
    return respond, client, calls


def test_requester_delivers_from_card(clean_roster, monkeypatch):
    respond, client, calls = _click(monkeypatch, "U_R")
    respond.assert_not_called()
    assert len(calls) == 1
    assert calls[0]["user_id"] == "U_R" and calls[0]["card_ts"] == "111.200"
    assert calls[0]["channel"] == "C_PURCHASING" and calls[0]["history"] == ["h"]
    updates = {(c[1]["channel"], c[1]["ts"]): c[1] for c in client.chat_update.call_args_list}
    assert set(updates) == {("C_PURCHASING", "900.1"), ("D_R", "900.2")}
    for u in updates.values():
        assert "Delivered by <@U_R>" in json.dumps(u["blocks"])
        assert not _buttons(u["blocks"])


def test_stranger_refused(clean_roster, monkeypatch):
    respond, client, calls = _click(monkeypatch, "U_X")
    respond.assert_called_once_with(text=text_rules.format_stage_denial("U_B"),
                                    response_type="ephemeral", replace_original=False)
    assert calls == []
    client.chat_update.assert_not_called()


def test_already_delivered(clean_roster, monkeypatch):
    respond, client, calls = _click(monkeypatch, "U_R", state="delivered")
    assert calls == []
    assert client.chat_update.call_count == 1
    kw = client.chat_update.call_args.kwargs
    assert (kw["channel"], kw["ts"]) == ("D_R", "900.2")
    assert "Already delivered." in json.dumps(kw["blocks"])
    assert not _buttons(kw["blocks"])


def test_config_constant():
    assert config.ACTION_NUDGE_DELIVERED == "nudge_delivered"
