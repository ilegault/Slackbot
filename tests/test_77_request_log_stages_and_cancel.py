"""Tests for Ticket 77: Stages and cancel are written to the request log.

Covers ADR 0011 decision 3:
- Processed, Confirmed, Delivered and Cancel each add a history line to requests.json.
- A cancelled request remains in the log with cancelled=True and is never deleted.
- The log never holds a stage or state key.
- DM card stage clicks append the exact same history line, exactly once.
- Log failures never block stage progression or cancel and alert the admin channel.
"""
import json
from unittest.mock import MagicMock

import pytest

from src import app, config, log_writer, queue_worker, roster, slack_io, store


@pytest.fixture
def clean_roster(tmp_path, monkeypatch):
    roster_file = str(tmp_path / "roster.json")
    monkeypatch.setattr(roster, "ROSTER_PATH", roster_file)
    roster._DATA = None
    data = {
        "admins": ["U_ADMIN"],
        "approvers": ["U_CHARLIE"],
        "buyers": ["U_BUYER", "U_OTHER_BUYER"],
        "requesters": {
            "U_ADMIN": "Isaac",
            "U_CHARLIE": "Charlie H.",
            "U_BUYER": "Dylan",
            "U_OTHER_BUYER": "Bob",
            "U_REQ": "Alex",
        },
        "vendors": [],
    }
    with open(roster_file, "w", encoding="utf-8") as f:
        json.dump(data, f)
    yield


@pytest.fixture
def temp_store(tmp_path, monkeypatch):
    store_file = str(tmp_path / "requests.json")
    monkeypatch.setattr(store, "STORE_PATH", store_file)
    return store_file


@pytest.fixture
def sync_queue(monkeypatch):
    def fake_submit(action_fn, *args, **kwargs):
        result = action_fn()
        if "success_callback" in kwargs and kwargs["success_callback"]:
            kwargs["success_callback"](result)
        return result

    monkeypatch.setattr(queue_worker, "submit_write_task", fake_submit)


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


def _extract_button_val(blocks_list):
    for b in blocks_list:
        if b.get("type") == "actions":
            for elem in b.get("elements", []):
                if elem.get("type") == "button" and "value" in elem:
                    return json.loads(elem["value"])
    return None


def test_each_stage_appends_one_line(clean_roster, temp_store, sync_queue, monkeypatch):
    """AC 1: Starting from a logged approved request, click Mark Processed, Mark Confirmed,

    Mark Delivered through app handlers (feeding each chat_update back):
    - after each, entry's last history line starts with Processed by, Confirmed by, Delivered to
    - the entry never has a state or stage key.
    """
    updated_rows = []
    monkeypatch.setattr(log_writer, "update_row", lambda row, vals: updated_rows.append((row, vals)))
    monkeypatch.setattr(log_writer, "get_row_info", lambda row: {"item_description": "Widgets"})

    channel = "C_PURCHASING"
    thread_ts = "1000.0"
    card_ts = "1000.1"

    req_data = {
        "item_description": "Widgets",
        "vendor": "Acme",
        "total_price": 50.0,
        "assignee_id": "U_BUYER",
        "dm_channel": "D_BUYER",
        "dm_ts": "9.9",
        "row": 17,
    }
    initial_history = ["Approved by Charlie H. on 09/30/26 12:00"]

    # Pre-create entry in request log (as approval would have done)
    req_id = store.create(
        channel=channel,
        thread_ts=thread_ts,
        card_ts=card_ts,
        requester="Alex",
        requester_id="U_REQ",
        buyer="Dylan",
        buyer_id="U_BUYER",
        rows=[17],
        history=list(initial_history),
        approved_at="2026-09-30T12:00:00",
        buyer_set_at="2026-09-30T12:00:00",
        cancelled=False,
    )

    thread_card_msg = _make_thread_card_message(card_ts, "approved", req_data, initial_history)

    client = MagicMock()

    def fake_replies(ch, ts=None, **kwargs):
        return {"ok": True, "messages": [{"ts": thread_ts, "text": "Parent"}, thread_card_msg]}

    client.conversations_replies.side_effect = fake_replies

    def record_chat_update(**kwargs):
        if kwargs.get("channel") == channel and kwargs.get("ts") == card_ts:
            thread_card_msg["blocks"] = kwargs.get("blocks", [])
            thread_card_msg["text"] = kwargs.get("text", "")
            if "metadata" in kwargs:
                thread_card_msg["metadata"] = kwargs["metadata"]
        return {"ok": True}

    client.chat_update.side_effect = record_chat_update

    # --- 1. Click Mark Processed ---
    btn_val = _extract_button_val(thread_card_msg["blocks"])
    body_processed = {
        "user": {"id": "U_BUYER"},
        "channel": {"id": channel},
        "message": {"ts": card_ts},
        "container": {"thread_ts": thread_ts},
        "actions": [{"action_id": "req_processed", "value": json.dumps(btn_val)}],
    }
    app.handle_req_processed_action(
        ack=MagicMock(),
        body=body_processed,
        respond=MagicMock(),
        client=client,
    )

    entry = store.get(req_id)
    assert entry is not None
    assert len(entry["history"]) == 2
    assert entry["history"][-1].startswith("Processed by")
    assert "state" not in entry
    assert "stage" not in entry

    # --- 2. Click Mark Confirmed ---
    btn_val = _extract_button_val(thread_card_msg["blocks"])
    body_confirmed = {
        "user": {"id": "U_BUYER"},
        "channel": {"id": channel},
        "message": {"ts": card_ts},
        "container": {"thread_ts": thread_ts},
        "actions": [{"action_id": "req_confirmed", "value": json.dumps(btn_val)}],
    }
    app.handle_req_confirmed_action(
        ack=MagicMock(),
        body=body_confirmed,
        respond=MagicMock(),
        client=client,
    )

    entry = store.get(req_id)
    assert len(entry["history"]) == 3
    assert entry["history"][-1].startswith("Confirmed by")
    assert "state" not in entry
    assert "stage" not in entry

    # --- 3. Click Mark Delivered ---
    btn_val = _extract_button_val(thread_card_msg["blocks"])
    body_delivered = {
        "user": {"id": "U_BUYER"},
        "channel": {"id": channel},
        "message": {"ts": card_ts},
        "container": {"thread_ts": thread_ts},
        "actions": [{"action_id": "req_delivered", "value": json.dumps(btn_val)}],
    }
    app.handle_req_delivered_action(
        ack=MagicMock(),
        body=body_delivered,
        respond=MagicMock(),
        client=client,
    )

    entry = store.get(req_id)
    assert len(entry["history"]) == 4
    assert entry["history"][-1].startswith("Delivered to")
    assert "state" not in entry
    assert "stage" not in entry


def test_dm_card_click_logs_same_line_once(clean_roster, temp_store, sync_queue, monkeypatch):
    """AC 2: dm_req_processed through app.handle_dm_stage_action appends exactly one Processed by line."""
    monkeypatch.setattr(log_writer, "update_row", lambda row, vals: None)
    monkeypatch.setattr(log_writer, "get_row_info", lambda row: {"item_description": "Widgets"})

    channel = "C_PURCHASING"
    thread_ts = "1000.0"
    card_ts = "1000.1"

    req_data = {
        "item_description": "Widgets",
        "vendor": "Acme",
        "total_price": 50.0,
        "assignee_id": "U_BUYER",
        "dm_channel": "D_BUYER",
        "dm_ts": "9.9",
        "row": 17,
    }
    initial_history = ["Approved by Charlie H. on 09/30/26 12:00"]

    req_id = store.create(
        channel=channel,
        thread_ts=thread_ts,
        card_ts=card_ts,
        requester="Alex",
        requester_id="U_REQ",
        buyer="Dylan",
        buyer_id="U_BUYER",
        rows=[17],
        history=list(initial_history),
        approved_at="2026-09-30T12:00:00",
        buyer_set_at="2026-09-30T12:00:00",
        cancelled=False,
    )

    thread_card_msg = _make_thread_card_message(card_ts, "approved", req_data, initial_history)

    client = MagicMock()
    client.conversations_replies.return_value = {
        "ok": True,
        "messages": [{"ts": thread_ts, "text": "Parent"}, thread_card_msg],
    }

    body = {
        "user": {"id": "U_BUYER"},
        "channel": {"id": "D_BUYER"},
        "message": {"ts": "2000.1"},
        "container": {"message_ts": "2000.1"},
        "actions": [
            {
                "action_id": config.ACTION_DM_REQ_PROCESSED,
                "value": json.dumps({
                    "thread_channel": channel,
                    "thread_ts": thread_ts,
                    "card_ts": card_ts,
                }),
            }
        ],
    }

    app.handle_dm_stage_action(
        ack=MagicMock(),
        body=body,
        respond=MagicMock(),
        client=client,
    )

    entry = store.get(req_id)
    assert entry is not None
    # Exactly one new history line (2 total)
    assert len(entry["history"]) == 2
    assert entry["history"][-1].startswith("Processed by")
    assert "state" not in entry
    assert "stage" not in entry


def test_cancel_keeps_entry(clean_roster, temp_store, sync_queue, monkeypatch):
    """AC 3: handle_cancel on a logged approved request:

    entry still exists, cancelled is True, last history line starts Cancelled by.
    """
    blanked_rows = []
    monkeypatch.setattr(log_writer, "blank_row", lambda row: blanked_rows.append(row))
    monkeypatch.setattr(slack_io, "find_all_rows_in_thread", lambda client, channel, thread_ts: [17])

    channel = "C_PURCHASING"
    thread_ts = "1000.0"
    card_ts = "1000.1"

    req_data = {
        "item_description": "Widgets",
        "vendor": "Acme",
        "total_price": 50.0,
        "assignee_id": "U_BUYER",
        "row": 17,
    }
    initial_history = ["Approved by Charlie H. on 09/30/26 12:00"]

    req_id = store.create(
        channel=channel,
        thread_ts=thread_ts,
        card_ts=card_ts,
        requester="Alex",
        requester_id="U_REQ",
        buyer="Dylan",
        buyer_id="U_BUYER",
        rows=[17],
        history=list(initial_history),
        approved_at="2026-09-30T12:00:00",
        buyer_set_at="2026-09-30T12:00:00",
        cancelled=False,
    )

    thread_card_msg = _make_thread_card_message(card_ts, "approved", req_data, initial_history)
    btn_val = _extract_button_val(thread_card_msg["blocks"])

    client = MagicMock()

    body = {
        "user": {"id": "U_ADMIN"},
        "channel": {"id": channel},
        "message": {"ts": card_ts},
        "container": {"thread_ts": thread_ts},
        "actions": [{"action_id": "req_cancel", "value": json.dumps(btn_val)}],
    }

    app.handle_req_cancel_action(
        ack=MagicMock(),
        body=body,
        respond=MagicMock(),
        client=client,
    )

    entry = store.get(req_id)
    assert entry is not None
    assert entry.get("cancelled") is True
    assert len(entry["history"]) == 2
    assert entry["history"][-1].startswith("Cancelled by")
    assert "state" not in entry
    assert "stage" not in entry


def test_log_failure_never_blocks(clean_roster, temp_store, sync_queue, monkeypatch):
    """AC 4: With store.append_history raising, Mark Processed still calls update_row once

    and updates the thread card, and one admin-channel message contains 'request log'.
    """
    updated_rows = []
    monkeypatch.setattr(log_writer, "update_row", lambda row, vals: updated_rows.append((row, vals)))
    monkeypatch.setattr(log_writer, "get_row_info", lambda row: {"item_description": "Widgets"})

    channel = "C_PURCHASING"
    thread_ts = "1000.0"
    card_ts = "1000.1"

    req_data = {
        "item_description": "Widgets",
        "vendor": "Acme",
        "total_price": 50.0,
        "assignee_id": "U_BUYER",
        "row": 17,
    }
    initial_history = ["Approved by Charlie H. on 09/30/26 12:00"]

    store.create(
        channel=channel,
        thread_ts=thread_ts,
        card_ts=card_ts,
        requester="Alex",
        requester_id="U_REQ",
        buyer="Dylan",
        buyer_id="U_BUYER",
        rows=[17],
        history=list(initial_history),
        approved_at="2026-09-30T12:00:00",
        buyer_set_at="2026-09-30T12:00:00",
        cancelled=False,
    )

    def buggy_append(*args, **kwargs):
        raise IOError("Disk full or permission denied")

    monkeypatch.setattr(store, "append_history", buggy_append)

    alerts = []
    monkeypatch.setattr(slack_io, "alert_admins", lambda cl, text: alerts.append(text))

    thread_card_msg = _make_thread_card_message(card_ts, "approved", req_data, initial_history)
    btn_val = _extract_button_val(thread_card_msg["blocks"])

    client = MagicMock()
    body = {
        "user": {"id": "U_BUYER"},
        "channel": {"id": channel},
        "message": {"ts": card_ts},
        "container": {"thread_ts": thread_ts},
        "actions": [{"action_id": "req_processed", "value": json.dumps(btn_val)}],
    }

    app.handle_req_processed_action(
        ack=MagicMock(),
        body=body,
        respond=MagicMock(),
        client=client,
    )

    # update_row was called once
    assert len(updated_rows) == 1
    # thread card was updated
    assert any(c[1].get("ts") == card_ts for c in client.chat_update.call_args_list)
    # Admin alert channel received a message containing 'request log'
    assert len(alerts) == 1
    assert "request log" in alerts[0].lower()


def test_no_entry_no_noise_across_stages_and_cancel(clean_roster, temp_store, sync_queue, monkeypatch):
    """When a thread has no request log entry, stages and cancel succeed without errors or alerts."""
    monkeypatch.setattr(log_writer, "update_row", lambda row, vals: None)
    monkeypatch.setattr(log_writer, "get_row_info", lambda row: {"item_description": "Widgets"})
    monkeypatch.setattr(log_writer, "blank_row", lambda row: None)
    monkeypatch.setattr(slack_io, "find_all_rows_in_thread", lambda client, channel, thread_ts: [17])

    alerts = []
    monkeypatch.setattr(slack_io, "alert_admins", lambda cl, text: alerts.append(text))

    channel = "C_PURCHASING"
    thread_ts = "9999.0"
    card_ts = "9999.1"

    req_data = {
        "item_description": "Widgets",
        "vendor": "Acme",
        "total_price": 50.0,
        "assignee_id": "U_BUYER",
        "row": 17,
    }
    history = ["Approved by Charlie H. on 09/30/26 12:00"]
    thread_card_msg = _make_thread_card_message(card_ts, "approved", req_data, history)
    btn_val = _extract_button_val(thread_card_msg["blocks"])

    client = MagicMock()

    # Processed
    app.handle_req_processed_action(
        ack=MagicMock(),
        body={
            "user": {"id": "U_BUYER"},
            "channel": {"id": channel},
            "message": {"ts": card_ts},
            "container": {"thread_ts": thread_ts},
            "actions": [{"action_id": "req_processed", "value": json.dumps(btn_val)}],
        },
        respond=MagicMock(),
        client=client,
    )

    # Cancel
    app.handle_req_cancel_action(
        ack=MagicMock(),
        body={
            "user": {"id": "U_ADMIN"},
            "channel": {"id": channel},
            "message": {"ts": card_ts},
            "container": {"thread_ts": thread_ts},
            "actions": [{"action_id": "req_cancel", "value": json.dumps(btn_val)}],
        },
        respond=MagicMock(),
        client=client,
    )

    assert len(alerts) == 0

