"""Tests for Ticket 89: the requester may press Mark Delivered, and only that stage button.

Covers (ADR 0013 decision 6, amending ADR 0010 decision 4):
- admin.can_update_request predicate with the new stage/requester_id keywords.
- Requester presses Mark Delivered on the thread card: the card is updated, no denial.
- Requester is still refused Mark Processed and Mark Confirmed.
- A registered stranger is still refused Mark Delivered.
- The DM card's delivered button honours the same rule.
"""
import json
from unittest.mock import MagicMock

import pytest

from src import admin, app, config, log_writer, queue_worker, roster, slack_io, text_rules


@pytest.fixture
def clean_roster(tmp_path, monkeypatch):
    roster_file = str(tmp_path / "roster.json")
    monkeypatch.setattr(roster, "ROSTER_PATH", roster_file)
    roster._DATA = None
    data = {
        "admins": [],
        "approvers": [],
        "buyers": ["U_B"],
        "requesters": {"U_B": "Dylan", "U_R": "Alex", "U_X": "Stranger"},
        "vendors": [],
    }
    with open(roster_file, "w", encoding="utf-8") as f:
        json.dump(data, f)
    yield
    roster._DATA = None


@pytest.fixture
def sync_queue(monkeypatch):
    def fake_submit(action_fn, *args, **kwargs):
        result = action_fn()
        if kwargs.get("success_callback"):
            kwargs["success_callback"](result)
        return result
    monkeypatch.setattr(queue_worker, "submit_write_task", fake_submit)
    monkeypatch.setattr(log_writer, "update_row", MagicMock())
    monkeypatch.setattr(slack_io, "find_row_in_thread", lambda *a, **k: 15)


def _body(action_id, user_id, state):
    req = {
        "item_description": "Widget",
        "row": 15,
        "total_price": 42.0,
        "assignee_id": "U_B",
        "user_id": "U_R",
    }
    return {
        "user": {"id": user_id},
        "channel": {"id": "C_PURCHASING"},
        "message": {"ts": "1000.2000"},
        "container": {"message_ts": "1000.2000", "thread_ts": "1000.2000"},
        "actions": [{
            "action_id": action_id,
            "value": json.dumps({"state": state, "row": 15, "request": req, "history": []}),
        }],
    }


def _click(handler, action_id, user_id, state):
    ack, respond, client = MagicMock(), MagicMock(), MagicMock()
    client.chat_postMessage.return_value = {"ts": "2000.3000"}
    handler(ack, _body(action_id, user_id, state), respond, client)
    return respond, client


def test_predicate(clean_roster):
    assert admin.can_update_request("U_R", "U_B", stage="delivered", requester_id="U_R") is True
    assert admin.can_update_request("U_R", "U_B", stage="confirmed", requester_id="U_R") is False
    assert admin.can_update_request("U_R", "U_B", stage="processed", requester_id="U_R") is False
    assert admin.can_update_request("U_X", "U_B", stage="delivered", requester_id="U_R") is False
    assert admin.can_update_request("U_R", None, stage="delivered", requester_id="U_R") is False
    assert admin.can_update_request("", "U_B", stage="delivered", requester_id="") is False
    assert admin.can_update_request(None, "U_B", stage="delivered", requester_id=None) is False
    # Two-argument calls behave as before.
    assert admin.can_update_request("U_B", "U_B") is True
    assert admin.can_update_request("U_R", "U_B") is False


def test_requester_marks_delivered_on_thread_card(clean_roster, sync_queue):
    respond, client = _click(app.handle_req_delivered_action, "req_delivered", "U_R", "confirmed")
    respond.assert_not_called()
    client.chat_update.assert_called()
    blocks = client.chat_update.call_args.kwargs["blocks"]
    assert not any(b.get("type") == "actions" for b in blocks)


@pytest.mark.parametrize(
    "action_id,handler,state",
    [
        ("req_processed", app.handle_req_processed_action, "approved"),
        ("req_confirmed", app.handle_req_confirmed_action, "processed"),
    ],
)
def test_requester_refused_other_stages(clean_roster, sync_queue, action_id, handler, state):
    respond, client = _click(handler, action_id, "U_R", state)
    respond.assert_called_once_with(
        text=text_rules.format_stage_denial("U_B"),
        response_type="ephemeral",
        replace_original=False,
    )
    client.chat_update.assert_not_called()


def test_stranger_refused_delivered(clean_roster, sync_queue):
    respond, client = _click(app.handle_req_delivered_action, "req_delivered", "U_X", "confirmed")
    respond.assert_called_once_with(
        text=text_rules.format_stage_denial("U_B"),
        response_type="ephemeral",
        replace_original=False,
    )
    client.chat_update.assert_not_called()


def _dm_click(monkeypatch, action_id, user_id, state):
    req = {"item_description": "Widget", "row": 15, "total_price": 42.0,
           "assignee_id": "U_B", "user_id": "U_R"}
    monkeypatch.setattr(
        slack_io, "get_card_by_ts", lambda *a, **k: (req, [], state)
    )
    body = {
        "user": {"id": user_id},
        "actions": [{
            "action_id": action_id,
            "value": json.dumps({"thread_channel": "C_PURCHASING", "thread_ts": "1000.2000", "card_ts": "1000.2000"}),
        }],
    }
    ack, respond, client = MagicMock(), MagicMock(), MagicMock()
    client.chat_postMessage.return_value = {"ts": "2000.3000"}
    app.handle_dm_stage_action(ack, body, respond, client)
    return respond, client


def test_dm_card_requester_may_deliver_only(clean_roster, sync_queue, monkeypatch):
    respond, client = _dm_click(monkeypatch, config.ACTION_DM_REQ_DELIVERED, "U_R", "confirmed")
    respond.assert_not_called()
    client.chat_update.assert_called()

    respond, client = _dm_click(monkeypatch, config.ACTION_DM_REQ_CONFIRMED, "U_R", "processed")
    respond.assert_called_once()
    assert respond.call_args.kwargs["text"] == text_rules.format_stage_denial("U_B")
    client.chat_update.assert_not_called()
