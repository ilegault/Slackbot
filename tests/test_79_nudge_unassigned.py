"""Tests for Ticket 79: Nudge unassigned requests.

Covers:
- Day 3: exactly one chat_postMessage to thread, no reply_broadcast, mentioning all 3 buyers,
  containing nobody's assigned, no 'yourself', no DM.
- Day 6: same text with reply_broadcast=True.
- Nothing after: Day 9 (2026-10-16) and Day 12 (2026-10-21) send no chat_postMessage.
- Stops on processed, cancel, same day (second run adds none).
- Roster must be real on temp file; store on temp file; Slack client and log_writer.get_row_info faked.
"""
import json
from datetime import date
from unittest.mock import MagicMock

import pytest

from src import log_writer, roster, store
from src.nudge import run_nudges


@pytest.fixture
def clean_roster(tmp_path, monkeypatch):
    """Set up real roster on a temporary file with three buyers."""
    roster_file = tmp_path / "roster.json"
    roster_data = {
        "requesters": {},
        "admins": ["U_ADMIN"],
        "approvers": ["U_APPROVER"],
        "buyers": ["U_BUYER1", "U_BUYER2", "U_BUYER3"],
        "vendors": [],
    }
    roster_file.write_text(json.dumps(roster_data))
    monkeypatch.setattr(roster, "ROSTER_PATH", str(roster_file))
    return roster_file


def _make_fake_client():
    client = MagicMock()
    post_counter = 0

    def fake_post_message(**kwargs):
        nonlocal post_counter
        post_counter += 1
        return {
            "ok": True,
            "ts": f"post_ts_{post_counter}",
            "channel": kwargs.get("channel"),
        }

    client.chat_postMessage.side_effect = fake_post_message
    client.chat_update.return_value = {"ok": True}
    return client


def test_day_3_unassigned_nudge(clean_roster, monkeypatch):
    """AC: Day 3. run_nudges(client, date(2026,10,8)):
    - exactly one chat_postMessage with thread_ts = the thread
    - no reply_broadcast
    - text containing 'nobody\'s assigned' and '<@...>' for all three buyers
    - not containing 'yourself'
    - no message to any user ID (no DM)
    - last_nudged updated in store
    """
    monkeypatch.setattr(log_writer, "get_row_info", lambda row: {"date_processed": ""})
    client = _make_fake_client()

    req_id = store.create(
        channel="C_PURCHASING",
        thread_ts="111.100",
        card_ts="111.200",
        requester="Alex",
        buyer=None,
        buyer_id=None,
        rows=[17],
        approved_at="2026-10-05T09:00:00",
        cancelled=False,
        last_nudged=None,
    )

    res = run_nudges(client, date(2026, 10, 8))
    assert res == [req_id]

    assert client.chat_postMessage.call_count == 1
    call_kwargs = client.chat_postMessage.call_args[1]

    assert call_kwargs.get("channel") == "C_PURCHASING"
    assert call_kwargs.get("thread_ts") == "111.100"
    assert not call_kwargs.get("reply_broadcast")

    msg_text = call_kwargs.get("text", "")
    assert "nobody's assigned" in msg_text
    assert "<@U_BUYER1>" in msg_text
    assert "<@U_BUYER2>" in msg_text
    assert "<@U_BUYER3>" in msg_text
    assert "yourself" not in msg_text.lower()

    # No message sent to user IDs (DMs)
    for c in client.chat_postMessage.call_args_list:
        ch = c[1].get("channel", "")
        assert not ch.startswith("U_"), f"Unexpected DM to user {ch}"

    entry = store.get(req_id)
    assert entry.get("last_nudged") == "2026-10-08"


def test_day_6_broadcast(clean_roster, monkeypatch):
    """AC: Day 6. date(2026,10,13): the same text with reply_broadcast=True."""
    monkeypatch.setattr(log_writer, "get_row_info", lambda row: {"date_processed": ""})
    client = _make_fake_client()

    req_id = store.create(
        channel="C_PURCHASING",
        thread_ts="111.100",
        card_ts="111.200",
        requester="Alex",
        buyer=None,
        buyer_id=None,
        rows=[17],
        approved_at="2026-10-05T09:00:00",
        cancelled=False,
        last_nudged="2026-10-08",
    )

    res = run_nudges(client, date(2026, 10, 13))
    assert res == [req_id]

    assert client.chat_postMessage.call_count == 1
    call_kwargs = client.chat_postMessage.call_args[1]

    assert call_kwargs.get("channel") == "C_PURCHASING"
    assert call_kwargs.get("thread_ts") == "111.100"
    assert call_kwargs.get("reply_broadcast") is True

    msg_text = call_kwargs.get("text", "")
    assert "nobody's assigned" in msg_text
    assert "<@U_BUYER1>" in msg_text
    assert "<@U_BUYER2>" in msg_text
    assert "<@U_BUYER3>" in msg_text
    assert "yourself" not in msg_text.lower()

    entry = store.get(req_id)
    assert entry.get("last_nudged") == "2026-10-13"


def test_nothing_after(clean_roster, monkeypatch):
    """AC: Nothing after. date(2026,10,16) (day 9) and date(2026,10,21) (day 12): no chat_postMessage."""
    monkeypatch.setattr(log_writer, "get_row_info", lambda row: {"date_processed": ""})
    client = _make_fake_client()

    req_id = store.create(
        channel="C_PURCHASING",
        thread_ts="111.100",
        card_ts="111.200",
        requester="Alex",
        buyer=None,
        buyer_id=None,
        rows=[17],
        approved_at="2026-10-05T09:00:00",
        cancelled=False,
        last_nudged="2026-10-13",
    )

    # Day 9: 2026-10-16
    res_day9 = run_nudges(client, date(2026, 10, 16))
    assert res_day9 == []
    assert client.chat_postMessage.call_count == 0

    # Day 12: 2026-10-21
    res_day12 = run_nudges(client, date(2026, 10, 21))
    assert res_day12 == []
    assert client.chat_postMessage.call_count == 0

    # last_nudged unchanged
    entry = store.get(req_id)
    assert entry.get("last_nudged") == "2026-10-13"


def test_stops_on_processed_cancel_same_day(clean_roster, monkeypatch):
    """AC: Stops on processed, cancel, same day.
    Day 3 with a row date_processed, with cancelled=True, or called twice on 2026-10-08:
    no message (the second call adds none).
    """
    client = _make_fake_client()

    # 1. Row has date_processed
    monkeypatch.setattr(log_writer, "get_row_info", lambda row: {"date_processed": "2026-10-07"})
    store.create(
        channel="C_PURCHASING",
        thread_ts="111.100",
        card_ts="111.200",
        requester="Alex",
        buyer=None,
        buyer_id=None,
        rows=[17],
        approved_at="2026-10-05T09:00:00",
        cancelled=False,
        last_nudged=None,
    )
    res = run_nudges(client, date(2026, 10, 8))
    assert res == []
    assert client.chat_postMessage.call_count == 0

    # 2. Cancelled
    monkeypatch.setattr(log_writer, "get_row_info", lambda row: {"date_processed": ""})
    store.save_store({})  # clear store
    store.create(
        channel="C_PURCHASING",
        thread_ts="111.100",
        card_ts="111.200",
        requester="Alex",
        buyer=None,
        buyer_id=None,
        rows=[17],
        approved_at="2026-10-05T09:00:00",
        cancelled=True,
        last_nudged=None,
    )
    res = run_nudges(client, date(2026, 10, 8))
    assert res == []
    assert client.chat_postMessage.call_count == 0

    # 3. Called twice on 2026-10-08
    store.save_store({})  # clear store
    req_normal = store.create(
        channel="C_PURCHASING",
        thread_ts="111.100",
        card_ts="111.200",
        requester="Alex",
        buyer=None,
        buyer_id=None,
        rows=[17],
        approved_at="2026-10-05T09:00:00",
        cancelled=False,
        last_nudged=None,
    )
    # First call: sends nudge
    res1 = run_nudges(client, date(2026, 10, 8))
    assert res1 == [req_normal]
    assert client.chat_postMessage.call_count == 1

    # Second call: sends nothing, adds none
    res2 = run_nudges(client, date(2026, 10, 8))
    assert res2 == []
    assert client.chat_postMessage.call_count == 1


def test_entry_with_buyer_id_uses_assigned_path(clean_roster, monkeypatch):
    """Point 5: If the entry has gained a buyer since (buyer_id set),
    ticket 78's path handles it, not this one.
    """
    monkeypatch.setattr(log_writer, "get_row_info", lambda row: {"date_processed": ""})

    req_data = {
        "item_description": "Laser Diode",
        "vendor": "Thorlabs",
        "total_price": 120.0,
        "row": 17,
        "dm_channel": "D_BUYER_1",
        "dm_ts": "old_dm_ts_1",
        "assignee_id": "U_BUYER1",
    }
    thread_card = {
        "ts": "111.200",
        "text": "🛒 Purchase Request (Approved)",
        "blocks": [
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": "Card for Laser Diode"},
            },
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "Mark Processed"},
                        "action_id": "req_processed",
                        "value": json.dumps({"state": "approved", "row": 17, "request": req_data, "history": []}),
                    }
                ],
            },
        ],
        "metadata": {
            "event_type": "purchase_request",
            "event_payload": req_data,
        },
    }

    client = _make_fake_client()
    client.conversations_replies.return_value = {"ok": True, "messages": [thread_card]}
    client.chat_getPermalink.return_value = {"ok": True, "permalink": "https://slack.com/archives/C123/p111"}

    req_id = store.create(
        channel="C_PURCHASING",
        thread_ts="111.100",
        card_ts="111.200",
        requester="Alex",
        buyer="Buyer 1",
        buyer_id="U_BUYER1",
        rows=[17],
        approved_at="2026-10-05T09:00:00",
        buyer_set_at="2026-10-05T09:00:00",
        cancelled=False,
        last_nudged=None,
        dm_channel="D_BUYER_1",
        dm_ts="old_dm_ts_1",
    )

    res = run_nudges(client, date(2026, 10, 8))
    assert res == [req_id]

    # Exactly one DM to U_BUYER1, no unassigned thread mention
    assert client.chat_postMessage.call_count == 1
    call_kwargs = client.chat_postMessage.call_args[1]
    assert call_kwargs.get("channel") == "U_BUYER1"
    msg_text = call_kwargs.get("text", "")
    assert "nobody's assigned" not in msg_text
    assert "<@U_BUYER2>" not in msg_text
    assert "<@U_BUYER3>" not in msg_text

