"""Tests for Ticket 88: the confirmed nudge (processed, not yet confirmed).

nudge, nudge_settings, store, blocks and lifecycle.sync_dm_card are real on temp files;
only the Slack client and log_writer.get_row_info are faked. Date Processed is the
Excel serial string the workbook really yields (46300 = Monday 2026-10-05).
"""
import copy
import json
from datetime import date

import pytest

from src import log_writer, nudge_settings, store
from src.nudge import parse_sheet_date, run_nudges
from tests.test_78_nudge_assigned import _make_fake_client, _make_thread_card_message

D = date(2026, 10, 5)


@pytest.mark.parametrize("value", ["46300", 46300, 46300.0, "2026-10-05", "2026-10-05 13:45:00", "10/5/2026", "10/5/26"])
def test_parse_sheet_date_accepts(value):
    assert parse_sheet_date(value) == D


@pytest.mark.parametrize("value", ["", None, "soon", "   "])
def test_parse_sheet_date_rejects(value):
    assert parse_sheet_date(value) is None


def _setup(monkeypatch, processed="46300", confirmed="", delivered="", state="processed"):
    monkeypatch.setattr(log_writer, "get_row_info", lambda row: {
        "date_processed": processed, "date_confirmed": confirmed, "date_delivered": delivered})
    req_data = {
        "item_description": "Laser Diode", "vendor": "Thorlabs", "total_price": 120.0,
        "row": 18, "dm_channel": "D_BUYER_A", "dm_ts": "old_dm_ts_111", "assignee_id": "U_A",
    }
    card = _make_thread_card_message(ts="111.200", state=state, req_data=req_data)
    client = _make_fake_client({"111.200": card})
    req_id = store.create(
        channel="C_PURCHASING", thread_ts="111.100", card_ts="111.200",
        requester="Alex", buyer="Alice", buyer_id="U_A", rows=[18],
        buyer_set_at="2026-09-01T09:00:00", approved_at="2026-09-01T09:00:00",
        cancelled=False, last_nudged=None, dm_channel="D_BUYER_A", dm_ts="old_dm_ts_111",
    )
    return client, req_id


def _posts(client):
    return [c[1] for c in client.chat_postMessage.call_args_list]


def test_day_4_nothing(monkeypatch):
    client, _ = _setup(monkeypatch)
    assert run_nudges(client, date(2026, 10, 9)) == []
    assert client.chat_postMessage.call_count == 0
    assert client.chat_update.call_count == 0


def test_day_5_dm_with_mark_confirmed(monkeypatch):
    client, req_id = _setup(monkeypatch)
    assert run_nudges(client, date(2026, 10, 12)) == [req_id]
    posts = _posts(client)
    assert len(posts) == 1
    assert posts[0]["channel"] == "U_A"
    assert not posts[0].get("reply_broadcast")
    text = json.dumps(posts[0]["blocks"])
    assert "processed 5 working days ago" in text
    assert "isn't marked Confirmed yet" in text
    buttons = [e["text"]["text"] for b in posts[0]["blocks"] if b.get("type") == "actions"
               for e in b.get("elements", []) if e.get("type") == "button"]
    assert "Mark Confirmed" in buttons
    assert "Mark Processed" not in buttons
    old = [c[1] for c in client.chat_update.call_args_list
           if c[1].get("channel") == "D_BUYER_A" and c[1].get("ts") == "old_dm_ts_111"]
    assert len(old) == 1
    assert "Replaced by the reminder below" in json.dumps(old[0]["blocks"])
    entry = store.get(req_id)
    assert entry["last_nudged"] == "2026-10-12"
    assert entry["dm_ts"] == "post_ts_1"


def test_channel_option(monkeypatch):
    s = copy.deepcopy(nudge_settings.DEFAULTS)
    s["confirmed"].update(dm=False, channel=True)
    nudge_settings.save(s)
    client, req_id = _setup(monkeypatch)
    assert run_nudges(client, date(2026, 10, 12)) == [req_id]
    posts = _posts(client)
    assert len(posts) == 1
    assert posts[0]["reply_broadcast"] is True
    assert posts[0]["channel"] == "C_PURCHASING"
    assert posts[0]["thread_ts"] == "111.100"
    assert "<@U_A>" in posts[0]["text"]
    assert "isn't marked Confirmed yet" in posts[0]["text"]


def test_stops_when_confirmed(monkeypatch):
    client, _ = _setup(monkeypatch, confirmed="46301")
    assert run_nudges(client, date(2026, 10, 12)) == []
    assert client.chat_postMessage.call_count == 0


def test_stops_when_delivered(monkeypatch):
    client, _ = _setup(monkeypatch, delivered="46310")
    assert run_nudges(client, date(2026, 10, 12)) == []
    assert client.chat_postMessage.call_count == 0


def test_disabled_nothing(monkeypatch):
    s = copy.deepcopy(nudge_settings.DEFAULTS)
    s["confirmed"]["enabled"] = False
    nudge_settings.save(s)
    client, _ = _setup(monkeypatch)
    assert run_nudges(client, date(2026, 10, 12)) == []
    assert client.chat_postMessage.call_count == 0


def test_unparseable_date_skips_without_error(monkeypatch):
    client, _ = _setup(monkeypatch, processed="soon")
    assert run_nudges(client, date(2026, 10, 12)) == []
    assert client.chat_postMessage.call_count == 0


def test_only_when_card_is_processed(monkeypatch):
    client, _ = _setup(monkeypatch, state="approved")
    assert run_nudges(client, date(2026, 10, 12)) == []
    assert client.chat_postMessage.call_count == 0
