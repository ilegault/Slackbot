"""Tests for Ticket 78: Nudge assigned requests.

Covers:
- working_days_between pure function calculation.
- Day 2 nothing, day 3 DM only with replaced old card and thread card update pointing to new DM ts.
- Day 6 DM plus thread reply with reply_broadcast=True mentioning buyer; day 9 DM only; day 7 nothing.
- Stops when it should: row has date_processed, cancelled=True, last_nudged == today, Saturday/Sunday, or buyer_set_at recently changed.
- Failure tolerance: one buyer's DM failure does not block the other; only successful entry's last_nudged updated.
"""
import json
from datetime import date
from unittest.mock import MagicMock

from src import log_writer, store
from src.nudge import run_nudges, working_days_between


def _make_thread_card_message(ts: str, state: str, req_data: dict, history: list | None = None):
    btn_val = json.dumps({
        "state": state,
        "row": req_data.get("row", 17),
        "request": req_data,
        "history": history or [],
    })
    return {
        "ts": ts,
        "text": f"🛒 Purchase Request ({state.capitalize()})",
        "blocks": [
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"Card for {req_data.get('item_description', 'Item')}"},
            },
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "Next Stage"},
                        "action_id": f"req_{state}",
                        "value": btn_val,
                    }
                ],
            },
        ],
        "metadata": {
            "event_type": "purchase_request",
            "event_payload": req_data,
        },
    }


def _make_fake_client(thread_cards_by_ts: dict):
    client = MagicMock()

    def fake_conversations_replies(channel, ts=None, **kwargs):
        msgs = list(thread_cards_by_ts.values())
        return {"ok": True, "messages": msgs}

    client.conversations_replies.side_effect = fake_conversations_replies

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
    client.chat_getPermalink.return_value = {"ok": True, "permalink": "https://slack.com/archives/C123/p111"}
    return client


def test_working_days_between():
    """AC 1: working_days_between counts Mon-Fri dates d with start < d <= end."""
    assert working_days_between(date(2026, 10, 5), date(2026, 10, 8)) == 3
    assert working_days_between(date(2026, 10, 9), date(2026, 10, 12)) == 1
    assert working_days_between(date(2026, 10, 5), date(2026, 10, 5)) == 0
    assert working_days_between(date(2026, 10, 8), date(2026, 10, 5)) == 0


def test_day_2_nothing_day_3_dm_only(monkeypatch):
    """AC 2: Day 2 nothing, day 3 DM only.
    - date(2026, 10, 7) -> no chat_postMessage.
    - date(2026, 10, 8) -> exactly one chat_postMessage to buyer ID with 3 working days and Mark Processed.
    - Old DM card updated with 'Replaced by the reminder below' and no actions block.
    - Thread card chat_update carries new DM ts.
    - No message has reply_broadcast.
    - Entry last_nudged is '2026-10-08'.
    """
    monkeypatch.setattr(log_writer, "get_row_info", lambda row: {"date_processed": ""})

    req_data = {
        "item_description": "Shaft Couplings",
        "vendor": "Ruland",
        "total_price": 50.0,
        "row": 17,
        "dm_channel": "D_BUYER_A",
        "dm_ts": "old_dm_ts_111",
        "assignee_id": "U_A",
    }
    thread_card = _make_thread_card_message(ts="111.200", state="approved", req_data=req_data)
    client = _make_fake_client({"111.200": thread_card})

    req_id = store.create(
        channel="C_PURCHASING",
        thread_ts="111.100",
        card_ts="111.200",
        requester="Alex",
        buyer="Alice",
        buyer_id="U_A",
        rows=[17],
        buyer_set_at="2026-10-05T09:00:00",
        approved_at="2026-10-05T09:00:00",
        cancelled=False,
        last_nudged=None,
        dm_channel="D_BUYER_A",
        dm_ts="old_dm_ts_111",
    )

    # Day 2: 2026-10-07
    res_day2 = run_nudges(client, date(2026, 10, 7))
    assert res_day2 == []
    assert client.chat_postMessage.call_count == 0
    assert client.chat_update.call_count == 0

    # Day 3: 2026-10-08
    res_day3 = run_nudges(client, date(2026, 10, 8))
    assert res_day3 == [req_id]

    # Exactly one chat_postMessage to buyer ID
    assert client.chat_postMessage.call_count == 1
    post_call = client.chat_postMessage.call_args_list[0]
    assert post_call[1].get("channel") == "U_A"
    post_blocks = post_call[1].get("blocks", [])

    # Blocks contain "3 working days"
    blocks_text = json.dumps(post_blocks)
    assert "3 working days" in blocks_text

    # Contains Mark Processed button
    has_mark_processed = False
    for b in post_blocks:
        if b.get("type") == "actions":
            for elem in b.get("elements", []):
                if elem.get("text", {}).get("text") == "Mark Processed":
                    has_mark_processed = True
    assert has_mark_processed, "Expected Mark Processed button in DM card blocks"

    # No message has reply_broadcast
    assert not post_call[1].get("reply_broadcast")

    # Old DM card updated with 'Replaced by the reminder below' and no actions block
    old_dm_updates = [
        c[1] for c in client.chat_update.call_args_list
        if c[1].get("channel") == "D_BUYER_A" and c[1].get("ts") == "old_dm_ts_111"
    ]
    assert len(old_dm_updates) == 1
    old_dm_blks = old_dm_updates[0].get("blocks", [])
    assert not any(b.get("type") == "actions" for b in old_dm_blks)
    old_dm_text = json.dumps(old_dm_blks)
    assert "Replaced by the reminder below" in old_dm_text

    # Thread card chat_update carries new DM ts
    thread_updates = [
        c[1] for c in client.chat_update.call_args_list
        if c[1].get("channel") == "C_PURCHASING" and c[1].get("ts") == "111.200"
    ]
    assert len(thread_updates) == 1
    thread_blks_str = json.dumps(thread_updates[0].get("blocks", []))
    assert "post_ts_1" in thread_blks_str

    # Entry's last_nudged is '2026-10-08'
    entry = store.get(req_id)
    assert entry.get("last_nudged") == "2026-10-08"


def test_day_6_broadcast_day_9_dm_only(monkeypatch):
    """AC 3: Day 6 adds one channel post; day 9 is DM only.
    - 2026-10-13 (Day 6) -> DM plus exactly one post with reply_broadcast=True, thread_ts=thread, text containing <@U_A>.
    - 2026-10-14 (Day 7) -> nothing.
    - 2026-10-16 (Day 9) -> DM, no reply_broadcast.
    """
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
    thread_card = _make_thread_card_message(ts="111.200", state="approved", req_data=req_data)
    client = _make_fake_client({"111.200": thread_card})

    req_id = store.create(
        channel="C_PURCHASING",
        thread_ts="111.100",
        card_ts="111.200",
        requester="Alex",
        buyer="Alice",
        buyer_id="U_A",
        rows=[18],
        buyer_set_at="2026-10-05T09:00:00",
        approved_at="2026-10-05T09:00:00",
        cancelled=False,
        last_nudged="2026-10-08",
        dm_channel="D_BUYER_A",
        dm_ts="dm_ts_1",
    )

    # 2026-10-13 (Day 6)
    res_day6 = run_nudges(client, date(2026, 10, 13))
    assert res_day6 == [req_id]

    # Two posts: DM + channel broadcast
    posts = client.chat_postMessage.call_args_list
    assert len(posts) == 2

    # DM post
    dm_posts = [p[1] for p in posts if p[1].get("channel") == "U_A"]
    assert len(dm_posts) == 1
    assert not dm_posts[0].get("reply_broadcast")

    # Broadcast post to thread channel
    broadcast_posts = [p[1] for p in posts if p[1].get("reply_broadcast") is True]
    assert len(broadcast_posts) == 1
    b_post = broadcast_posts[0]
    assert b_post.get("channel") == "C_PURCHASING"
    assert b_post.get("thread_ts") == "111.100"
    assert "<@U_A>" in b_post.get("text", "")
    assert "approved 6 working days ago" in b_post.get("text", "")

    # 2026-10-14 (Day 7) -> nothing
    client.chat_postMessage.reset_mock()
    res_day7 = run_nudges(client, date(2026, 10, 14))
    assert res_day7 == []
    assert client.chat_postMessage.call_count == 0

    # 2026-10-16 (Day 9) -> DM, no reply_broadcast
    client.chat_postMessage.reset_mock()
    res_day9 = run_nudges(client, date(2026, 10, 16))
    assert res_day9 == [req_id]
    posts_day9 = client.chat_postMessage.call_args_list
    assert len(posts_day9) == 1
    assert posts_day9[0][1].get("channel") == "U_A"
    assert not posts_day9[0][1].get("reply_broadcast")


def test_stops_when_it_should(monkeypatch):
    """AC 4: It stops when it should.
    Each of these on day 3 -> no chat_postMessage:
    - a row with a date_processed
    - cancelled=True
    - last_nudged == "2026-10-08" (second call the same day)
    - a Saturday date
    - buyer_set_at moved to 2026-10-07 by a reassignment (day 1)
    """
    req_data = {
        "item_description": "Shaft Couplings",
        "vendor": "Ruland",
        "total_price": 50.0,
        "row": 17,
        "dm_channel": "D_BUYER_A",
        "dm_ts": "dm_ts_1",
        "assignee_id": "U_A",
    }
    thread_card = _make_thread_card_message(ts="111.200", state="approved", req_data=req_data)

    # 1. Row with date_processed
    monkeypatch.setattr(log_writer, "get_row_info", lambda row: {"date_processed": "2026-10-07"})
    client = _make_fake_client({"111.200": thread_card})
    store.create(
        channel="C_PURCHASING",
        thread_ts="111.100",
        card_ts="111.200",
        requester="Alex",
        buyer="Alice",
        buyer_id="U_A",
        rows=[17],
        buyer_set_at="2026-10-05T09:00:00",
        approved_at="2026-10-05T09:00:00",
        cancelled=False,
        last_nudged=None,
    )
    assert run_nudges(client, date(2026, 10, 8)) == []
    assert client.chat_postMessage.call_count == 0

    # 2. cancelled=True
    monkeypatch.setattr(log_writer, "get_row_info", lambda row: {"date_processed": ""})
    store.save_store({})  # clear
    store.create(
        channel="C_PURCHASING",
        thread_ts="111.100",
        card_ts="111.200",
        requester="Alex",
        buyer="Alice",
        buyer_id="U_A",
        rows=[17],
        buyer_set_at="2026-10-05T09:00:00",
        approved_at="2026-10-05T09:00:00",
        cancelled=True,
        last_nudged=None,
    )
    assert run_nudges(client, date(2026, 10, 8)) == []
    assert client.chat_postMessage.call_count == 0

    # 3. last_nudged == "2026-10-08"
    store.save_store({})
    store.create(
        channel="C_PURCHASING",
        thread_ts="111.100",
        card_ts="111.200",
        requester="Alex",
        buyer="Alice",
        buyer_id="U_A",
        rows=[17],
        buyer_set_at="2026-10-05T09:00:00",
        approved_at="2026-10-05T09:00:00",
        cancelled=False,
        last_nudged="2026-10-08",
    )
    assert run_nudges(client, date(2026, 10, 8)) == []
    assert client.chat_postMessage.call_count == 0

    # 4. Saturday date: 2026-10-10
    store.save_store({})
    store.create(
        channel="C_PURCHASING",
        thread_ts="111.100",
        card_ts="111.200",
        requester="Alex",
        buyer="Alice",
        buyer_id="U_A",
        rows=[17],
        buyer_set_at="2026-10-05T09:00:00",
        approved_at="2026-10-05T09:00:00",
        cancelled=False,
        last_nudged=None,
    )
    assert run_nudges(client, date(2026, 10, 10)) == []
    assert client.chat_postMessage.call_count == 0

    # 5. buyer_set_at moved to 2026-10-07 (day 1 on 2026-10-08)
    store.save_store({})
    store.create(
        channel="C_PURCHASING",
        thread_ts="111.100",
        card_ts="111.200",
        requester="Alex",
        buyer="Alice",
        buyer_id="U_A",
        rows=[17],
        buyer_set_at="2026-10-07T09:00:00",
        approved_at="2026-10-05T09:00:00",
        cancelled=False,
        last_nudged=None,
    )
    assert run_nudges(client, date(2026, 10, 8)) == []
    assert client.chat_postMessage.call_count == 0


def test_one_failure_does_not_stop_the_rest(monkeypatch):
    """AC 5: One failure doesn't stop the rest.
    Two due entries, chat_postMessage raising for the first buyer's ID:
    the second buyer still gets the DM and only the second entry's last_nudged is set.
    """
    monkeypatch.setattr(log_writer, "get_row_info", lambda row: {"date_processed": ""})

    req_data_1 = {
        "item_description": "Part 1",
        "vendor": "Acme",
        "total_price": 10.0,
        "row": 1,
        "dm_channel": "D_BUYER_A",
        "dm_ts": "dm_ts_1",
        "assignee_id": "U_A",
    }
    req_data_2 = {
        "item_description": "Part 2",
        "vendor": "Beta",
        "total_price": 20.0,
        "row": 2,
        "dm_channel": "D_BUYER_B",
        "dm_ts": "dm_ts_2",
        "assignee_id": "U_B",
    }

    card_1 = _make_thread_card_message(ts="111.201", state="approved", req_data=req_data_1)
    card_2 = _make_thread_card_message(ts="111.202", state="approved", req_data=req_data_2)

    client = _make_fake_client({"111.201": card_1, "111.202": card_2})

    def fail_for_buyer_a(**kwargs):
        if kwargs.get("channel") == "U_A":
            raise RuntimeError("Slack API failure for U_A")
        return {"ok": True, "ts": "post_ts_success", "channel": kwargs.get("channel")}

    client.chat_postMessage.side_effect = fail_for_buyer_a

    req1_id = store.create(
        channel="C_PURCHASING",
        thread_ts="111.101",
        card_ts="111.201",
        requester="Alex",
        buyer="Alice",
        buyer_id="U_A",
        rows=[1],
        buyer_set_at="2026-10-05T09:00:00",
        approved_at="2026-10-05T09:00:00",
        cancelled=False,
        last_nudged=None,
        dm_channel="D_BUYER_A",
        dm_ts="dm_ts_1",
    )

    req2_id = store.create(
        channel="C_PURCHASING",
        thread_ts="111.102",
        card_ts="111.202",
        requester="Alex",
        buyer="Bob",
        buyer_id="U_B",
        rows=[2],
        buyer_set_at="2026-10-05T09:00:00",
        approved_at="2026-10-05T09:00:00",
        cancelled=False,
        last_nudged=None,
        dm_channel="D_BUYER_B",
        dm_ts="dm_ts_2",
    )

    res = run_nudges(client, date(2026, 10, 8))
    assert res == [req2_id]

    entry1 = store.get(req1_id)
    entry2 = store.get(req2_id)

    assert entry1.get("last_nudged") is None
    assert entry2.get("last_nudged") == "2026-10-08"
