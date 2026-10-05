"""Tests for Ticket 87: the nudge settings file drives the processed nudge.

Covers loading (missing, corrupt, bad field), is_due, validate, .gitignore, and the
processed nudge following the settings (defaults, DM off / channel on, disabled).
nudge_settings.SETTINGS_PATH and store.STORE_PATH are on temp files (conftest);
the nudge settings, run_nudges, store and blocks are real; only the Slack client
and log_writer.get_row_info are faked.
"""
import copy
import json
from datetime import date
from pathlib import Path

from src import log_writer, nudge_settings, store
from src.nudge import is_due, run_nudges
from tests.test_78_nudge_assigned import _make_fake_client, _make_thread_card_message

REPO = Path(__file__).resolve().parent.parent


def test_load_missing_file_gives_defaults():
    assert nudge_settings.load() == nudge_settings.DEFAULTS


def test_load_corrupt_file_gives_defaults_and_one_alert():
    Path(nudge_settings.SETTINGS_PATH).write_text("not json")
    alerts = []
    assert nudge_settings.load(alert_callback=alerts.append) == nudge_settings.DEFAULTS
    assert len(alerts) == 1
    assert "nudge_settings.json" in alerts[0]


def test_load_non_object_gives_defaults_and_alert():
    Path(nudge_settings.SETTINGS_PATH).write_text("[1, 2]")
    alerts = []
    assert nudge_settings.load(alert_callback=alerts.append) == nudge_settings.DEFAULTS
    assert len(alerts) == 1


def test_bad_every_takes_that_stage_default_others_default():
    Path(nudge_settings.SETTINGS_PATH).write_text(json.dumps(
        {"processed": {"enabled": True, "every": 0, "dm": True, "channel": False}}))
    got = nudge_settings.load()
    assert got["processed"]["every"] == 3
    for stage in ("approved", "confirmed", "delivered"):
        assert got[stage] == nudge_settings.DEFAULTS[stage]


def test_good_stage_in_file_is_used_and_missing_stages_default():
    Path(nudge_settings.SETTINGS_PATH).write_text(json.dumps(
        {"confirmed": {"enabled": False, "every": 7, "dm": False, "channel": True}}))
    got = nudge_settings.load()
    assert got["confirmed"] == {"enabled": False, "every": 7, "dm": False, "channel": True}
    assert got["processed"] == nudge_settings.DEFAULTS["processed"]


def test_save_then_load_round_trips():
    x = copy.deepcopy(nudge_settings.DEFAULTS)
    x["delivered"]["every"] = 4
    x["approved"]["enabled"] = True
    nudge_settings.save(x)
    assert nudge_settings.load() == x


def test_defaults_are_exactly_the_adr_values():
    d = nudge_settings.DEFAULTS
    assert d["approved"] == {"enabled": False, "every": 3, "dm": True, "channel": False}
    assert d["processed"] == {"enabled": True, "every": 3, "dm": True, "channel": False}
    assert d["confirmed"] == {"enabled": True, "every": 5, "dm": True, "channel": False}
    assert d["delivered"] == {"enabled": True, "every": 10, "dm": False, "channel": True}


def test_gitignore_lists_settings_file():
    lines = (REPO / ".gitignore").read_text().splitlines()
    assert "nudge_settings.json" in [ln.strip() for ln in lines]


def test_is_due():
    assert not is_due(2, 3)
    assert is_due(3, 3)
    assert is_due(6, 3)
    assert not is_due(7, 3)
    assert not is_due(0, 3)


def test_validate():
    s = copy.deepcopy(nudge_settings.DEFAULTS)
    assert nudge_settings.validate(s) == {}
    s["processed"]["dm"] = False
    s["processed"]["channel"] = False
    assert nudge_settings.validate(s) == {"processed_send": "Pick DM, Channel or both."}
    s["processed"]["enabled"] = False
    assert nudge_settings.validate(s) == {}
    s["delivered"]["every"] = 0
    assert nudge_settings.validate(s) == {"delivered_every": "Whole number, 1 or more."}


def _assigned_setup(monkeypatch, last_nudged=None):
    monkeypatch.setattr(log_writer, "get_row_info", lambda row: {"date_processed": ""})
    req_data = {
        "item_description": "Laser Diode",
        "vendor": "Thorlabs",
        "total_price": 120.0,
        "row": 18,
        "dm_channel": "D_BUYER_A",
        "dm_ts": "dm_ts_1",
        "assignee_id": "U_A",
    }
    card = _make_thread_card_message(ts="111.200", state="approved", req_data=req_data)
    client = _make_fake_client({"111.200": card})
    req_id = store.create(
        channel="C_PURCHASING", thread_ts="111.100", card_ts="111.200",
        requester="Alex", buyer="Alice", buyer_id="U_A", rows=[18],
        buyer_set_at="2026-10-05T09:00:00", approved_at="2026-10-05T09:00:00",
        cancelled=False, last_nudged=last_nudged,
        dm_channel="D_BUYER_A", dm_ts="dm_ts_1",
    )
    return client, req_id


def test_default_day_6_and_9_dm_only(monkeypatch):
    client, req_id = _assigned_setup(monkeypatch, last_nudged="2026-10-08")

    assert run_nudges(client, date(2026, 10, 13)) == [req_id]  # day 6
    assert [c[1]["channel"] for c in client.chat_postMessage.call_args_list] == ["U_A"]

    client.chat_postMessage.reset_mock()
    assert run_nudges(client, date(2026, 10, 14)) == []  # day 7
    assert client.chat_postMessage.call_count == 0

    assert run_nudges(client, date(2026, 10, 16)) == [req_id]  # day 9
    assert [c[1]["channel"] for c in client.chat_postMessage.call_args_list] == ["U_A"]
    for c in client.chat_postMessage.call_args_list:
        assert not c[1].get("reply_broadcast")


def test_channel_only_every_2(monkeypatch):
    nudge_settings.save({**copy.deepcopy(nudge_settings.DEFAULTS), "processed": {
        "enabled": True, "every": 2, "dm": False, "channel": True}})
    client, req_id = _assigned_setup(monkeypatch)

    assert run_nudges(client, date(2026, 10, 7)) == [req_id]  # day 2
    posts = [c[1] for c in client.chat_postMessage.call_args_list]
    assert len(posts) == 1
    assert posts[0]["reply_broadcast"] is True
    assert posts[0]["channel"] == "C_PURCHASING"
    assert posts[0]["thread_ts"] == "111.100"
    assert "<@U_A>" in posts[0]["text"]
    assert all(p["channel"] != "U_A" for p in posts)
    assert store.get(req_id)["last_nudged"] == "2026-10-07"
    # no DM card was retired or re-posted
    assert client.chat_update.call_count == 0


def test_disabled_posts_nothing(monkeypatch):
    nudge_settings.save({**copy.deepcopy(nudge_settings.DEFAULTS), "processed": {
        "enabled": False, "every": 3, "dm": True, "channel": False}})
    client, _ = _assigned_setup(monkeypatch)
    store.create(
        channel="C_PURCHASING", thread_ts="222.100", card_ts="222.200",
        requester="Alex", buyer=None, buyer_id=None, rows=[19],
        approved_at="2026-10-05T09:00:00", cancelled=False, last_nudged=None,
    )
    assert run_nudges(client, date(2026, 10, 8)) == []
    assert client.chat_postMessage.call_count == 0
    assert client.chat_update.call_count == 0


def test_corrupt_settings_alerts_admins_and_uses_defaults(monkeypatch):
    Path(nudge_settings.SETTINGS_PATH).write_text("not json")
    client, req_id = _assigned_setup(monkeypatch)
    alerts = []
    from src import slack_io
    monkeypatch.setattr(slack_io, "alert_admins", lambda c, m: alerts.append(m))
    assert run_nudges(client, date(2026, 10, 8)) == [req_id]
    assert any("nudge_settings.json" in a for a in alerts)
