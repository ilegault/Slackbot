"""Tests for Ticket 91: set an expected delivery date from a Confirmed card.

Covers ADR 0013 decision 5 and ADR 0010 decision 3:
- the optional 'Set expected delivery' button on both Confirmed cards (a pointer, never the request);
- who may open the form, and the default date;
- past dates refused;
- a valid date reaches the thread card, the DM card, the request log and the thread;
- changing the date again overwrites it and posts a second thread line.
"""
import json
from datetime import date
from unittest.mock import MagicMock

import pytest

from src import app, blocks, config, roster, slack_io, store, text_rules

CHANNEL = "C_PURCHASING"
THREAD = "1000.0001"
CARD = "1000.0002"
DM_CHANNEL = "D_BUYER"
DM_TS = "2000.0001"


@pytest.fixture(autouse=True)
def env(tmp_path, monkeypatch):
    roster_file = str(tmp_path / "roster.json")
    monkeypatch.setattr(roster, "ROSTER_PATH", roster_file)
    roster._DATA = None
    with open(roster_file, "w", encoding="utf-8") as f:
        json.dump({
            "admins": [], "approvers": [], "buyers": ["U_B"],
            "requesters": {"U_B": "Dylan", "U_R": "Alex", "U_X": "Stranger"},
            "vendors": [],
        }, f)
    monkeypatch.setattr(config, "ADMIN_ALERT_CHANNEL", "C_ADMIN")
    monkeypatch.setattr(app, "_today", lambda: date(2026, 10, 5))
    yield
    roster._DATA = None


REQ = {
    "item_description": "Widget", "total_price": 42.0, "vendor": "DigiKey",
    "assignee_id": "U_B", "assignee": "Dylan", "user_id": "U_R",
    "dm_channel": DM_CHANNEL, "dm_ts": DM_TS, "row": 15,
}


class FakeClient:
    """Keeps the thread card as Slack would, so a second submit reads what the first wrote."""

    def __init__(self):
        self.card_blocks = blocks.build_request_blocks(
            "confirmed", dict(REQ), history=["Confirmed by Dylan"], thread_channel=CHANNEL, card_ts=CARD
        )
        self.update_calls = []
        self.posts = []
        self.views = []
        self.permalinks = 0

    def conversations_replies(self, **kw):
        return {"messages": [{"ts": CARD, "blocks": self.card_blocks}]}

    def chat_update(self, **kw):
        self.update_calls.append(kw)
        if kw["channel"] == CHANNEL:
            self.card_blocks = kw["blocks"]
        return {"ok": True}

    def chat_postMessage(self, **kw):
        self.posts.append(kw)
        return {"ts": "3000.1", "ok": True}

    def chat_getPermalink(self, **kw):
        return {"permalink": "https://example.test/p"}

    def views_open(self, **kw):
        self.views.append(kw)
        return {"ok": True}

    def users_info(self, **kw):
        return {"user": {"profile": {"display_name": "x"}}}


def _button(blks, action_id):
    for b in blks:
        for e in b.get("elements", []) if b.get("type") == "actions" else []:
            if e.get("action_id") == action_id:
                return e
    return None


def _text(blks):
    return "\n".join(b["text"]["text"] for b in blks if b.get("type") == "section")


def _click(client, user_id):
    ack, respond = MagicMock(), MagicMock()
    btn = _button(client.card_blocks, config.ACTION_SET_EXPECTED_DELIVERY)
    body = {
        "user": {"id": user_id}, "channel": {"id": CHANNEL}, "trigger_id": "TRIG",
        "message": {"ts": CARD}, "container": {"thread_ts": THREAD},
        "actions": [{"action_id": config.ACTION_SET_EXPECTED_DELIVERY, "value": btn["value"]}],
    }
    app.handle_set_expected_delivery_action(ack, body, respond, client)
    return respond


def _submit(client, user_id, iso):
    ack = MagicMock()
    view = {
        "private_metadata": json.dumps({"thread_channel": CHANNEL, "thread_ts": THREAD, "card_ts": CARD}),
        "state": {"values": {"block_expected_delivery": {"expected_delivery": {"selected_date": iso}}}},
    }
    app.handle_expected_delivery_submission(ack, {"user": {"id": user_id}}, client, view)
    return ack


def test_button_on_both_confirmed_cards_only():
    thread = blocks.build_request_blocks("confirmed", dict(REQ), thread_channel=CHANNEL, card_ts=CARD)
    dm = blocks.build_dm_card_blocks("confirmed", dict(REQ), CHANNEL, THREAD, CARD)
    for blks in (thread, dm):
        btn = _button(blks, "set_expected_delivery")
        assert btn is not None
        assert btn["text"]["text"] == "Set expected delivery"
        assert "style" not in btn
        assert set(json.loads(btn["value"])) == {"thread_channel", "thread_ts", "card_ts"}
    assert _button(blocks.build_request_blocks("processed", dict(REQ)), "set_expected_delivery") is None
    assert _button(blocks.build_dm_card_blocks("processed", dict(REQ), CHANNEL, THREAD, CARD), "set_expected_delivery") is None
    # The Mark Delivered button is still there beside it.
    assert _button(thread, "req_delivered") is not None
    assert _button(dm, config.ACTION_DM_REQ_DELIVERED) is not None


def test_opening_the_form_defaults_to_two_weeks_and_refuses_strangers():
    client = FakeClient()
    respond = _click(client, "U_B")
    respond.assert_not_called()
    assert len(client.views) == 1
    view = client.views[0]["view"]
    assert view["callback_id"] == "expected_delivery_submit"
    assert view["blocks"][0]["block_id"] == "block_expected_delivery"
    assert view["blocks"][0]["element"]["initial_date"] == "2026-10-19"
    assert json.loads(view["private_metadata"]) == {
        "thread_channel": CHANNEL, "thread_ts": THREAD, "card_ts": CARD,
    }

    client2 = FakeClient()
    respond = _click(client2, "U_X")
    respond.assert_called_once_with(
        text=text_rules.format_stage_denial("U_B"), response_type="ephemeral", replace_original=False,
    )
    assert client2.views == []


def test_past_date_refused():
    client = FakeClient()
    ack = _submit(client, "U_R", "2026-10-04")
    ack.assert_called_once_with(
        response_action="errors", errors={"block_expected_delivery": "Pick today or a later date."}
    )
    assert client.update_calls == []
    assert client.posts == []


def test_today_is_accepted():
    client = FakeClient()
    ack = _submit(client, "U_R", "2026-10-05")
    ack.assert_called_once_with()
    assert "Expected delivery:* Oct 5" in _text(client.card_blocks)


def test_valid_date_lands_everywhere_and_can_be_changed():
    req_id = store.create(CHANNEL, THREAD, "Alex", requester_id="U_R", card_ts=CARD, history=["Posted"])
    client = FakeClient()

    ack = _submit(client, "U_R", "2026-11-16")
    ack.assert_called_once_with()

    assert "Expected delivery:* Nov 16" in _text(client.card_blocks)
    value = json.loads(_button(client.card_blocks, "req_delivered")["value"])
    assert value["request"]["expected_delivery"] == "2026-11-16"
    assert any("Expected delivery set to Nov 16 by Alex" in h for h in value["history"])
    # The button survives the rebuild with its pointer.
    assert json.loads(_button(client.card_blocks, "set_expected_delivery")["value"])["card_ts"] == CARD

    dm_updates = [c for c in client.update_calls if c["channel"] == DM_CHANNEL]
    assert len(dm_updates) == 1
    assert dm_updates[0]["ts"] == DM_TS
    assert "Expected delivery:* Nov 16" in _text(dm_updates[0]["blocks"])

    entry = store.get(req_id)
    assert entry["expected_delivery"] == "2026-11-16"
    assert any("Expected delivery set to Nov 16" in h for h in entry["history"])
    assert len(entry["history"]) == 2

    assert [p["text"] for p in client.posts] == ["📦 Expected delivery Nov 16 — I'll check back then."]
    assert client.posts[0]["thread_ts"] == THREAD

    # Change it: the form now opens on the stored date, the cards, log and thread all move.
    _click(client, "U_B")
    assert client.views[-1]["view"]["blocks"][0]["element"]["initial_date"] == "2026-11-16"
    _submit(client, "U_B", "2026-11-30")
    text = _text(client.card_blocks)
    assert "Nov 30" in text and "Nov 16" not in text
    assert store.get(req_id)["expected_delivery"] == "2026-11-30"
    assert len(client.posts) == 2
    assert client.posts[1]["text"] == "📦 Expected delivery Nov 30 — I'll check back then."
    last_dm = [c for c in client.update_calls if c["channel"] == DM_CHANNEL][-1]
    assert "Nov 30" in _text(last_dm["blocks"])


def test_log_failure_does_not_block_the_card(monkeypatch):
    def boom(*a, **k):
        raise OSError("disk full")

    monkeypatch.setattr(store, "find_id_by_card", boom)
    client = FakeClient()
    _submit(client, "U_R", "2026-11-16")
    assert "Nov 16" in _text(client.card_blocks)
    assert len(client.posts) >= 1
    assert any(p["channel"] == "C_ADMIN" for p in client.posts)


def test_short_date_helper():
    assert blocks.format_short_date("2026-11-16") == "Nov 16"
    assert blocks.format_short_date("2026-01-05") == "Jan 5"
    assert slack_io  # imported for parity with sibling tests
