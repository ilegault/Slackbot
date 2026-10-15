"""Tests for Ticket 125: Change date on the buyer's DM card (Filled EPIF).

Acceptance criteria:
- [ ] test_change_date_button_only_for_epif_path_before_processed
- [ ] test_change_date_refills_and_resends: re-fills the archived EPIF under the same name, uploads it
      to the buyer's DM, posts the history line, never touches the workbook.
- [ ] test_change_date_denied_for_non_assignee: the listener denies and opens nothing; the handler
      changes and uploads nothing.
- [ ] test_change_date_refused_after_processed
"""
import datetime
import json
import os
from unittest.mock import MagicMock

import pytest

from src import app, blocks, config, epif_parser, interview, lifecycle, queue_worker, roster
from tests.test_45_epif_approval_archives import create_test_workbook

FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")
TEMPLATE = os.path.join(FIXTURES, "EPIF_TEMPLATE_HIRST.pdf")
CHANNEL = "C_PURCHASING"
THREAD = "100.00"
DM_CHANNEL = "D_BUYER"


@pytest.fixture(autouse=True)
def isolated_roster(tmp_path, monkeypatch):
    roster_file = str(tmp_path / "roster.json")
    monkeypatch.setattr(roster, "ROSTER_PATH", roster_file)
    roster._DATA = None
    with open(roster_file, "w", encoding="utf-8") as f:
        json.dump({"admins": ["U_ADMIN"], "approvers": ["U_CHARLIE"], "buyers": ["U_BUYER", "U_OTHER"],
                   "requesters": {"U_REQ": "Alex", "U_BUYER": "Dylan", "U_OTHER": "Sam"}, "vendors": []}, f)
    yield
    roster._DATA = None


class FakeClient:
    """Keeps the thread card as Slack would (blocks and metadata), and records uploads."""

    def __init__(self):
        self.messages: dict[tuple[str, str], dict] = {}
        self.uploads: list[dict] = []
        self.posts: list[dict] = []
        self.views: list[dict] = []
        self._n = 0

    def _next_ts(self):
        self._n += 1
        return f"{500 + self._n}.00"

    def chat_postMessage(self, **kw):
        self.posts.append(kw)
        ts = self._next_ts()
        # Posting to a user id opens their DM, as Slack does: the reply names the real DM channel.
        channel = DM_CHANNEL if kw["channel"].startswith("U_") else kw["channel"]
        self.messages[(channel, ts)] = dict(kw, channel=channel, ts=ts)
        return {"ok": True, "ts": ts, "channel": channel}

    def chat_update(self, **kw):
        key = (kw["channel"], kw["ts"])
        self.messages[key] = dict(self.messages.get(key, {}), **kw)
        return {"ok": True}

    def conversations_replies(self, **kw):
        msgs = [m for (ch, _ts), m in self.messages.items() if ch == kw["channel"]]
        return {"messages": [{"ts": m["ts"], "blocks": m.get("blocks", []), "metadata": m.get("metadata", {})}
                             for m in msgs]}

    def conversations_open(self, **kw):
        return {"channel": {"id": DM_CHANNEL}}

    def files_upload_v2(self, **kw):
        self.uploads.append(kw)
        return {"ok": True}

    def chat_getPermalink(self, **kw):
        return {"permalink": "https://example.test/p"}

    def views_open(self, **kw):
        self.views.append(kw)
        return {"ok": True}

    def users_info(self, **kw):
        return {"user": {"profile": {"display_name": "x"}}}


def _request():
    return {
        "item_description": "Shaft Couplings",
        "purpose": "Motor test stand alignment",
        "total_price": 150.0,
        "vendor": "Ruland",
        "vendor_contact_name": "Sales",
        "vendor_contact_email": "sales@ruland.com",
        "date_of_purchase": datetime.date(2026, 9, 22),
        "project_id": "PG000025831",
        "fund": "133",
        "category": "Research/Lab Supplies (3105)",
        "delivery_room": "ERB 212",
        "payment_method": "P-card",
        "link": "https://ruland.com",
        "name_of_system": "",
        "asset_id": "",
    }


@pytest.fixture
def approved(tmp_path, monkeypatch):
    """An EPIF-path request approved through the real lifecycle into temp dirs; returns (client, card_ts, epif_path, writes)."""
    wb = str(tmp_path / "Purchasing-Log.xlsx")
    create_test_workbook(wb)
    epifs = str(tmp_path / "EPIFs")
    os.makedirs(epifs)
    monkeypatch.setattr(config, "WORKBOOK_PATH", wb)
    monkeypatch.setattr(config, "EPIFS_DIR", epifs)
    monkeypatch.setattr(config, "EPIF_TEMPLATE_PATH", TEMPLATE)
    writes: list = []

    def _sync(action_fn, channel="", thread_ts="", user_id="", task_type="append",
              description="", success_callback=None, failure_callback=None, client=None):
        writes.append(description)
        try:
            res = action_fn()
            if success_callback:
                success_callback(res)
        except Exception as exc:
            if failure_callback:
                failure_callback(exc)

    monkeypatch.setattr(queue_worker, "submit_write_task", _sync)
    monkeypatch.setattr(interview, "today", lambda: datetime.date(2026, 10, 6))

    client = FakeClient()
    lifecycle.finalize_purchase_request(
        client=client, say=MagicMock(), channel=CHANNEL, thread_ts=THREAD, event_ts="101.00",
        parsed=_request(), requester="Alex", notify_target="U_REQ", pdf_bytes=None, file_name=None,
        assignee_id="U_BUYER", assignee_name="Dylan",
    )
    (card_ts,) = [ts for (ch, ts), m in client.messages.items()
                  if ch == CHANNEL and "metadata" in m]
    (epif_name,) = os.listdir(epifs)
    # Setup is over: only what the change-date handler does from here is under test.
    client.uploads.clear()
    client.posts.clear()
    writes.clear()
    return client, card_ts, os.path.join(epifs, epif_name), writes


def _buttons(blks):
    return [e for b in blks if b.get("type") == "actions" for e in b.get("elements", [])]


def _has(blks, action_id):
    return any(e.get("action_id") == action_id for e in _buttons(blks))


def test_change_date_button_only_for_epif_path_before_processed():
    req = {"parsed": _request(), "assignee_id": "U_BUYER"}
    dm = lambda state, route: blocks.build_dm_card_blocks(  # noqa: E731
        state, req, CHANNEL, THREAD, "1.0", route=route)
    assert _has(dm("approved", "epif"), "change_epif_date")
    assert not _has(dm("approved", "workday"), "change_epif_date")
    assert not _has(dm("processed", "epif"), "change_epif_date")
    # Mark Processed is still beside it.
    assert _has(dm("approved", "epif"), config.ACTION_DM_REQ_PROCESSED)


def test_change_date_refills_and_resends(approved):
    client, card_ts, epif_path, writes = approved
    with open(epif_path, "rb") as f:
        assert epif_parser.parse_epif(f.read())["date_of_purchase"] == datetime.date(2026, 10, 6)

    ok = lifecycle.handle_change_epif_date(
        client, CHANNEL, THREAD, card_ts, "U_BUYER", datetime.date(2026, 10, 20))

    assert ok is True
    with open(epif_path, "rb") as f:
        assert epif_parser.parse_epif(f.read())["date_of_purchase"] == datetime.date(2026, 10, 20)
    assert [u["filename"] for u in client.uploads] == [os.path.basename(epif_path)]
    assert client.uploads[0]["channel"] == DM_CHANNEL
    assert any("EPIF date changed to 10/20/2026" in p["text"] and p.get("thread_ts") == THREAD
               for p in client.posts)
    assert writes == []
    # The card remembers the date, and still carries a Change date button for the next change.
    thread_card = client.messages[(CHANNEL, card_ts)]
    value = next(e["value"] for e in _buttons(thread_card["blocks"]) if e.get("value", "").startswith("{\"state\""))
    assert json.loads(value)["request"]["epif_date"] == "2026-10-20"
    assert any("EPIF date changed to 10/20/2026 by Dylan" in h for h in json.loads(value)["history"])


def test_change_date_denied_for_non_assignee(approved):
    client, card_ts, epif_path, writes = approved
    with open(epif_path, "rb") as f:
        before = f.read()

    # The listener: a different buyer clicks the button.
    dm_blocks = blocks.build_dm_card_blocks(
        "approved", {"parsed": _request(), "assignee_id": "U_BUYER"}, CHANNEL, THREAD, card_ts, route="epif")
    btn = next(e for e in _buttons(dm_blocks) if e["action_id"] == "change_epif_date")
    ack, respond = MagicMock(), MagicMock()
    body = {"user": {"id": "U_OTHER"}, "trigger_id": "T", "channel": {"id": DM_CHANNEL},
            "message": {"ts": "9.9"}, "actions": [{"action_id": "change_epif_date", "value": btn["value"]}]}
    app.handle_change_epif_date_action(ack, body, respond, client)
    ack.assert_called_once()
    respond.assert_called_once()
    assert respond.call_args.kwargs["response_type"] == "ephemeral"
    assert client.views == []

    # The handler: a stale form submitted by a non-assignee.
    assert lifecycle.handle_change_epif_date(
        client, CHANNEL, THREAD, card_ts, "U_OTHER", datetime.date(2026, 10, 20)) is False
    with open(epif_path, "rb") as f:
        assert f.read() == before
    assert client.uploads == []
    assert client.posts == []


def test_change_date_refused_after_processed(approved):
    client, card_ts, epif_path, writes = approved
    with open(epif_path, "rb") as f:
        before = f.read()
    # Move the thread card to processed the way the lifecycle stores it.
    card = client.messages[(CHANNEL, card_ts)]
    value = next(json.loads(e["value"]) for e in _buttons(card["blocks"]) if e.get("value", "").startswith("{\"state\""))
    processed = blocks.build_request_blocks("processed", value["request"], history=value["history"])
    client.chat_update(channel=CHANNEL, ts=card_ts, blocks=processed)

    assert lifecycle.handle_change_epif_date(
        client, CHANNEL, THREAD, card_ts, "U_BUYER", datetime.date(2026, 10, 20)) is False
    with open(epif_path, "rb") as f:
        assert f.read() == before
    assert client.uploads == []
    assert not any("EPIF date changed" in p["text"] for p in client.posts)


def test_change_date_modal_defaults_to_today_and_submit_delegates(monkeypatch):
    view = blocks.build_change_epif_date_view(CHANNEL, THREAD, "1.0", "2026-10-06")
    assert view["callback_id"] == config.CHANGE_EPIF_DATE_CALLBACK_ID
    assert view["blocks"][0]["element"]["initial_date"] == "2026-10-06"
    calls = []
    monkeypatch.setattr(lifecycle, "handle_change_epif_date", lambda *a, **k: calls.append((a, k)))
    ack = MagicMock()
    submitted = {
        "private_metadata": view["private_metadata"],
        "state": {"values": {"block_change_epif_date": {"change_epif_date": {"selected_date": "2026-10-20"}}}},
    }
    app.handle_change_epif_date_submission(ack, {"user": {"id": "U_BUYER"}}, MagicMock(), submitted)
    ack.assert_called_once_with()
    assert calls and calls[0][1]["chosen_date"] == datetime.date(2026, 10, 20)
