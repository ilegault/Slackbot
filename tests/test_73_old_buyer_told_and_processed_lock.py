"""Tests for Ticket 73: The old buyer is told, and the buyer locks at Processed.

Covers ADR 0011 decision 1 & spec:
- On reassignment, the old buyer receives a DM saying who has it now and who moved it.
- A first assignment sends no "moved" DM.
- Once a request is Processed, confirmed or delivered, assignment (via picker or typed keyword)
  is refused in-thread with "Already Processed by ...".
- A failure sending the old buyer DM does not block the assignment.
"""
import json
from unittest.mock import MagicMock

import pytest

from src import app, config, queue_worker, roster, slack_io


@pytest.fixture
def clean_roster(tmp_path, monkeypatch):
    roster_file = str(tmp_path / "roster.json")
    monkeypatch.setattr(roster, "ROSTER_PATH", roster_file)
    roster._DATA = None
    data = {
        "admins": ["U_ADMIN"],
        "approvers": ["U_CHARLIE"],
        "buyers": ["U_BUYER_A", "U_BUYER_B", "U_BUYER_C"],
        "requesters": {
            "U_ADMIN": "Isaac",
            "U_CHARLIE": "Charlie H.",
            "U_BUYER_A": "Alice",
            "U_BUYER_B": "Bob",
            "U_BUYER_C": "Carol",
            "U_REQ": "Alex",
        },
        "vendors": [],
    }
    with open(roster_file, "w", encoding="utf-8") as f:
        json.dump(data, f)
    yield


@pytest.fixture
def sync_queue(monkeypatch):
    def fake_submit(action_fn, *args, **kwargs):
        result = action_fn()
        if "success_callback" in kwargs and kwargs["success_callback"]:
            kwargs["success_callback"](result)
        return result

    monkeypatch.setattr(queue_worker, "submit_write_task", fake_submit)


def _make_picker_body(user_id: str, selected_user: str, req_data: dict, history: list, state: str = "approved"):
    """Build the body for a req_assign_select action click."""
    btn_val = json.dumps({
        "state": state,
        "request": req_data,
        "history": history,
    })
    return {
        "user": {"id": user_id},
        "channel": {"id": "C123"},
        "message": {
            "ts": "1000.1",
            "blocks": [
                {"type": "section", "text": {"type": "mrkdwn", "text": "Card"}},
                {
                    "type": "actions",
                    "elements": [
                        {
                            "type": "button",
                            "action_id": f"req_{state}",
                            "value": btn_val,
                        },
                        {
                            "type": "button",
                            "action_id": "req_cancel",
                            "value": btn_val,
                        },
                        {
                            "type": "users_select",
                            "action_id": config.ACTION_REQ_ASSIGN_SELECT,
                        },
                    ],
                },
            ],
        },
        "container": {"thread_ts": "1000.0"},
        "actions": [
            {
                "action_id": config.ACTION_REQ_ASSIGN_SELECT,
                "selected_user": selected_user,
            }
        ],
    }


def test_old_buyer_gets_dm_on_reassignment(clean_roster, monkeypatch):
    """AC 1: Approver moves an approved request from buyer A to buyer B via
    app.handle_req_assign_select_action: exactly one chat_postMessage whose channel
    is U_BUYER_A and whose text contains 'was moved to' and buyer B's roster name (Bob)
    and the approver's roster name (Charlie H.).
    """
    monkeypatch.setattr(slack_io, "find_row_in_thread", lambda *a, **kw: None)

    req_data = {
        "item_description": "Laser diode",
        "vendor": "Thorlabs",
        "total_price": 120.0,
        "assignee_id": "U_BUYER_A",
        "assignee": "Alice",
        "dm_channel": "D_BUYER_A",
        "dm_ts": "5.5",
        "row": 17,
    }
    history = ["Assigned to Alice on 01/01/26 10:00"]
    body = _make_picker_body("U_CHARLIE", "U_BUYER_B", req_data, history)

    client = MagicMock()
    client.chat_postMessage.return_value = {"channel": "D_BUYER_B", "ts": "99.1", "ok": True}
    client.conversations_open.return_value = {"channel": {"id": "D_BUYER_B"}, "ok": True}
    respond = MagicMock()

    app.handle_req_assign_select_action(ack=lambda: None, body=body, respond=respond, client=client)

    # Check chat_postMessage calls to U_BUYER_A
    old_buyer_posts = [
        c for c in client.chat_postMessage.call_args_list
        if c.kwargs.get("channel") == "U_BUYER_A"
    ]
    assert len(old_buyer_posts) == 1
    post_text = old_buyer_posts[0].kwargs.get("text", "")
    assert "was moved to" in post_text
    assert "Bob" in post_text
    assert "Charlie H." in post_text
    assert "Laser diode" in post_text


def test_first_assignment_sends_no_moved_dm(clean_roster, monkeypatch):
    """AC 2: Assigning an unassigned approved request sends no 'was moved to' DM."""
    monkeypatch.setattr(slack_io, "find_row_in_thread", lambda *a, **kw: None)

    req_data = {
        "item_description": "Laser diode",
        "vendor": "Thorlabs",
        "total_price": 120.0,
        "row": 17,
    }
    history = ["Approved by Charlie on 01/01/26 10:00"]
    body = _make_picker_body("U_CHARLIE", "U_BUYER_B", req_data, history)

    client = MagicMock()
    client.chat_postMessage.return_value = {"channel": "D_BUYER_B", "ts": "99.1", "ok": True}
    client.conversations_open.return_value = {"channel": {"id": "D_BUYER_B"}, "ok": True}
    respond = MagicMock()

    app.handle_req_assign_select_action(ack=lambda: None, body=body, respond=respond, client=client)

    for c in client.chat_postMessage.call_args_list:
        post_text = c.kwargs.get("text", "")
        assert "was moved to" not in post_text


def test_picker_on_processed_card_is_refused(clean_roster, monkeypatch):
    """AC 3: A card in state processed with history
    ['Approved by ...', 'Processed by Dylan on 09/24/26 14:02']:
    a picker click posts one thread message containing
    'Already Processed by Dylan on 09/24/26 14:02' and there is no chat_update and no DM.
    """
    req_data = {
        "item_description": "Optical breadboard",
        "vendor": "Thorlabs",
        "total_price": 500.0,
        "assignee_id": "U_BUYER_A",
        "assignee": "Alice",
        "row": 42,
    }
    history = [
        "Approved by Charlie H. on 09/24/26 10:00",
        "Processed by Dylan on 09/24/26 14:02",
    ]
    body = _make_picker_body("U_BUYER_B", "U_BUYER_C", req_data, history, state="processed")

    client = MagicMock()
    respond = MagicMock()

    app.handle_req_assign_select_action(ack=lambda: None, body=body, respond=respond, client=client)

    # One thread message containing refusal
    thread_msgs = [
        c for c in client.chat_postMessage.call_args_list
        if c.kwargs.get("channel") == "C123" and c.kwargs.get("thread_ts") == "1000.0"
    ]
    assert len(thread_msgs) == 1
    assert "Already Processed by Dylan on 09/24/26 14:02 — the buyer can't change after this point." in thread_msgs[0].kwargs.get("text", "")

    # No chat_update
    assert client.chat_update.call_count == 0

    # No DM messages
    dm_msgs = [
        c for c in client.chat_postMessage.call_args_list
        if c.kwargs.get("channel") != "C123"
    ]
    assert len(dm_msgs) == 0


def test_typed_keyword_on_processed_stages_is_refused(clean_roster, monkeypatch):
    """AC 4: The typed keyword on a Processed request is refused the same way
    (through app.dispatch_command with assign @B), for each of processed, confirmed, delivered.
    """
    for stage in ("processed", "confirmed", "delivered"):
        client = MagicMock()
        client.auth_test.return_value = {"user_id": "U_BOT"}

        req_data = {
            "item_description": "Test item",
            "vendor": "Thorlabs",
            "total_price": 200.0,
            "assignee_id": "U_BUYER_A",
            "assignee": "Alice",
            "row": 15,
        }
        history = [
            "Approved by Charlie on 09/24/26 10:00",
            "Processed by Dylan on 09/24/26 14:02",
        ]

        monkeypatch.setattr(
            slack_io,
            "find_card_in_thread",
            lambda *a, **kw: (req_data, "1000.1", history, stage),
        )

        posted_texts = []

        def fake_say(text, thread_ts=None, **kw):
            posted_texts.append(text)

        app.dispatch_command(
            client=client,
            say=fake_say,
            channel="C123",
            thread_ts="1000.0",
            user="U_BUYER_B",
            event_ts="1000.2",
            text="<@U_BOT> assign <@U_BUYER_C>",
        )

        assert len(posted_texts) == 1, f"Failed for stage={stage}: {posted_texts}"
        assert "Already Processed by Dylan on 09/24/26 14:02 — the buyer can't change after this point." in posted_texts[0]
        assert client.chat_update.call_count == 0
        assert client.chat_postMessage.call_count == 0


def test_failed_old_buyer_dm_never_blocks(clean_roster, monkeypatch):
    """AC 5: With chat_postMessage raising only for channel == 'U_BUYER_A',
    the thread card is still updated to buyer B and buyer B's DM card is posted.
    """
    monkeypatch.setattr(slack_io, "find_row_in_thread", lambda *a, **kw: None)

    req_data = {
        "item_description": "Laser diode",
        "vendor": "Thorlabs",
        "total_price": 120.0,
        "assignee_id": "U_BUYER_A",
        "assignee": "Alice",
        "dm_channel": "D_BUYER_A",
        "dm_ts": "5.5",
        "row": 17,
    }
    history = ["Assigned to Alice on 01/01/26 10:00"]
    body = _make_picker_body("U_CHARLIE", "U_BUYER_B", req_data, history)

    client = MagicMock()

    def fake_post_message(**kwargs):
        if kwargs.get("channel") == "U_BUYER_A":
            raise Exception("Slack DM failed for user U_BUYER_A")
        return {"channel": kwargs.get("channel", "D_BUYER_B"), "ts": "99.1", "ok": True}

    client.chat_postMessage.side_effect = fake_post_message
    client.conversations_open.return_value = {"channel": {"id": "D_BUYER_B"}, "ok": True}
    respond = MagicMock()

    app.handle_req_assign_select_action(ack=lambda: None, body=body, respond=respond, client=client)

    # Thread card was updated to Buyer B
    thread_updates = [c[1] for c in client.chat_update.call_args_list if c[1].get("channel") == "C123"]
    assert len(thread_updates) >= 1
    found_b = False
    for c in client.chat_update.call_args_list:
        for blk in c[1].get("blocks", []):
            if blk.get("type") == "actions":
                for el in blk.get("elements", []):
                    try:
                        val = json.loads(el.get("value", "{}"))
                        if val.get("request", {}).get("assignee_id") == "U_BUYER_B":
                            found_b = True
                    except Exception:
                        pass
    assert found_b, "Thread card was not updated to Buyer B"

    # Buyer B's DM card was posted
    buyer_b_posts = [
        c for c in client.chat_postMessage.call_args_list
        if c.kwargs.get("channel") == "U_BUYER_B"
    ]
    assert len(buyer_b_posts) >= 1, "Buyer B's DM card was not posted"
