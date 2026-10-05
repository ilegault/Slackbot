"""Tests for Ticket 92: "Not yet" on the nudge card; delivered nudges pause until the expected date.

nudge.delivered_due, run_nudges, store, nudge_settings and blocks.build_nudge_card_blocks are
real on temp files; the Slack client and log_writer.get_row_info are faked. 46300 is the Excel
serial for Monday 2026-10-05; the delivered schedule is every 10 working days.
"""
import json
from datetime import date

import pytest

from src import app, blocks, config, log_writer, roster, store
from src.nudge import delivered_due, run_nudges
from tests.test_78_nudge_assigned import _make_fake_client, _make_thread_card_message

CONFIRMED = date(2026, 10, 5)


@pytest.fixture
def clean_roster(tmp_path, monkeypatch):
    roster_file = str(tmp_path / "roster.json")
    monkeypatch.setattr(roster, "ROSTER_PATH", roster_file)
    roster._DATA = None
    with open(roster_file, "w", encoding="utf-8") as f:
        json.dump({"admins": [], "approvers": [], "buyers": ["U_B"],
                   "requesters": {"U_B": "Dylan", "U_R": "Alex"}, "vendors": []}, f)
    yield
    roster._DATA = None


def test_delivered_due_table():
    d = date
    assert delivered_due(d(2026, 10, 19), CONFIRMED, None, 10) is True
    assert delivered_due(d(2026, 10, 16), CONFIRMED, None, 10) is False
    mon = d(2026, 11, 16)
    assert delivered_due(d(2026, 10, 19), CONFIRMED, mon, 10) is False
    assert delivered_due(d(2026, 11, 13), CONFIRMED, mon, 10) is False
    assert delivered_due(mon, CONFIRMED, mon, 10) is True
    assert delivered_due(d(2026, 11, 17), CONFIRMED, mon, 10) is False
    assert delivered_due(d(2026, 11, 30), CONFIRMED, mon, 10) is True
    sat = d(2026, 11, 14)
    assert delivered_due(d(2026, 11, 16), CONFIRMED, sat, 10) is True
    assert delivered_due(sat, CONFIRMED, sat, 10) is False


def _buttons(bl):
    return [e for b in bl if b.get("type") == "actions" for e in b.get("elements", [])]


def test_card_has_not_yet_button_and_expected_text():
    bl = blocks.build_nudge_card_blocks("active", "<@U_B>", "Widget", 10, "C", "1.1", "1.2")
    btns = _buttons(bl)
    assert [b["action_id"] for b in btns] == ["nudge_delivered", "nudge_not_yet"]
    assert btns[0]["value"] == btns[1]["value"]
    assert "Not yet" in btns[1]["text"]["text"]
    bl = blocks.build_nudge_card_blocks("active", "<@U_B>", "Widget", 10, "C", "1.1", "1.2", expected="2026-11-16")
    assert "was expected Nov 16. Has this been delivered?" in bl[0]["text"]["text"]
    assert "confirmed" not in bl[0]["text"]["text"]
    retired = blocks.build_nudge_card_blocks("replaced", "<@U_B>", "Widget", 10, "C", "1.1", "1.2", note="x")
    assert not _buttons(retired)


def test_pressing_not_yet_opens_the_form(clean_roster, monkeypatch):
    monkeypatch.setattr(app, "_today", lambda: date(2026, 10, 19))
    req = {"item_description": "Widget", "row": 18, "assignee_id": "U_B", "user_id": "U_R"}
    card = _make_thread_card_message(ts="111.200", state="confirmed", req_data=req)
    client = _make_fake_client({"111.200": card})
    opened = []
    client.views_open = lambda **kw: opened.append(kw)
    value = json.dumps({"thread_channel": "C_PURCHASING", "thread_ts": "111.100", "card_ts": "111.200"})
    body = {"user": {"id": "U_R"}, "trigger_id": "T1", "channel": {"id": "U_R"},
            "message": {"ts": "9.9"},
            "actions": [{"action_id": config.ACTION_NUDGE_NOT_YET, "value": value}]}
    replies = []
    app.handle_set_expected_delivery_action(lambda *a, **k: None, body, lambda *a, **k: replies.append(a), client)
    assert len(opened) == 1
    assert opened[0]["view"]["callback_id"] == "expected_delivery_submit"
    # a stranger is refused, same predicate as Mark Delivered
    opened.clear()
    body["user"]["id"] = "U_Z"
    app.handle_set_expected_delivery_action(lambda *a, **k: None, body, lambda *a, **k: None, client)
    assert opened == []


def test_not_yet_is_registered_on_the_opener():
    registered = [
        lst for lst in app.app._listeners if lst.ack_function is app.handle_set_expected_delivery_action
    ]
    # two registrations of the one opener: set_expected_delivery and nudge_not_yet
    assert len(registered) == 2


def _setup(monkeypatch, expected):
    monkeypatch.setattr(log_writer, "get_row_info", lambda row: {
        "date_processed": "46300", "date_confirmed": "46300", "date_delivered": ""})
    req = {"item_description": "Laser Diode", "vendor": "Thorlabs", "total_price": 120.0,
           "row": 18, "assignee_id": "U_B", "user_id": "U_R"}
    card = _make_thread_card_message(ts="111.200", state="confirmed", req_data=req)
    client = _make_fake_client({"111.200": card})
    req_id = store.create(
        channel="C_PURCHASING", thread_ts="111.100", card_ts="111.200",
        requester="Alex", buyer="Dylan", buyer_id="U_B", rows=[18],
        buyer_set_at="2026-09-01T09:00:00", approved_at="2026-09-01T09:00:00",
        cancelled=False, last_nudged=None, expected_delivery=expected,
    )
    return client, req_id


def _posts(client):
    return [c[1] for c in client.chat_postMessage.call_args_list]


def test_run_pauses_and_resumes(monkeypatch):
    client, req_id = _setup(monkeypatch, "2026-11-16")
    assert run_nudges(client, date(2026, 10, 19)) == []
    assert _posts(client) == []
    assert run_nudges(client, date(2026, 11, 16)) == [req_id]
    posts = _posts(client)
    assert len(posts) == 1
    assert "was expected Nov 16" in json.dumps(posts[0]["blocks"])
    assert "nudge_not_yet" in json.dumps(posts[0]["blocks"])


def test_pushing_it_back_pauses_again(monkeypatch):
    client, req_id = _setup(monkeypatch, "2026-11-16")
    assert run_nudges(client, date(2026, 11, 16)) == [req_id]
    store.update(req_id, expected_delivery="2026-12-07")
    n = client.chat_postMessage.call_count
    assert run_nudges(client, date(2026, 11, 30)) == []
    assert client.chat_postMessage.call_count == n
