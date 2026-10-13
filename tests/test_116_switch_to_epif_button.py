"""Tests for Ticket 116: the Switch to EPIF button opens the EPIF form.

Acceptance criteria:
- [ ] The button shows only on an approved Workday-path card.
- [ ] Pressed by the assignee it opens the Screen 2 form on the EPIF path, pre-filled, with a
      `switch` object (card_ts, row) in private metadata.
- [ ] A stranger is refused privately and no form opens.
- [ ] admin.can_fill_or_switch allows the four roles and refuses a stranger.
"""
import json
from unittest.mock import MagicMock

import pytest

from src import admin, app, blocks, config, roster, slack_io

CHANNEL = "C123"
THREAD = "T123"
CARD_TS = "1000.2000"

REQUEST = {
    "requester": "Alex",
    "user_id": "U_REQ",
    "approver": "U_CHARLIE",
    "assignee_id": "U_BUYER",
    "assignee": "Dylan",
    "parsed": {
        "item_description": "Optical post",
        "purpose": "Alignment",
        "vendor": "Winford",
        "payment_method": "Workday",
        "total_price": 17.10,
        "category": "Research/Lab Supplies (3105)",
        "project_id": "PG000025831",
        "fund": "133",
        "delivery_room": "ERB 212",
    },
}


@pytest.fixture(autouse=True)
def clean_roster(tmp_path, monkeypatch):
    roster_file = str(tmp_path / "roster.json")
    monkeypatch.setattr(roster, "ROSTER_PATH", roster_file)
    roster._DATA = None
    data = {
        "admins": ["U_ADMIN"],
        "approvers": ["U_CHARLIE"],
        "buyers": ["U_BUYER", "U_BUYER2"],
        "requesters": {"U_ADMIN": "Isaac", "U_BUYER": "Dylan", "U_REQ": "Alex"},
        "vendors": [],
    }
    with open(roster_file, "w", encoding="utf-8") as f:
        json.dump(data, f)
    roster.load_roster()


def _request(payment_method):
    req = json.loads(json.dumps(REQUEST))
    req["parsed"]["payment_method"] = payment_method
    return req


def _button(blks, action_id):
    for b in blks:
        if b.get("type") == "actions":
            for el in b["elements"]:
                if el.get("action_id") == action_id:
                    return el
    return None


def test_switch_button_shows_only_on_an_approved_workday_card():
    table = [
        ("approved", "Workday", True),
        ("approved", "P-card", False),
        ("approved", "Req/PO", False),
        ("posted", "Workday", False),
        ("processed", "Workday", False),
        ("confirmed", "Workday", False),
        ("delivered", "Workday", False),
    ]
    for state, method, expected in table:
        btn = _button(blocks.build_request_blocks(state, _request(method), requester="Alex"), "req_switch_epif")
        assert (btn is not None) == expected, (state, method)
    # Placement and shape: after Mark Processed, before Cancel, no style.
    ids = [
        el["action_id"]
        for b in blocks.build_request_blocks("approved", _request("Workday"), requester="Alex")
        if b.get("type") == "actions"
        for el in b["elements"]
        if "action_id" in el
    ]
    assert ids.index("req_processed") < ids.index("req_switch_epif") < ids.index("req_cancel")
    approved = blocks.build_request_blocks("approved", _request("Workday"), requester="Alex")
    assert "style" not in _button(approved, "req_switch_epif")


def _press(user_id, client, payment_method="Workday", assignee_id="U_BUYER"):
    req = _request(payment_method)
    req["assignee_id"] = assignee_id
    card = blocks.build_request_blocks("approved", req, requester="Alex")
    btn = _button(card, "req_switch_epif")
    assert btn is not None
    body = {
        "user": {"id": user_id},
        "channel": {"id": CHANNEL},
        "message": {"ts": CARD_TS, "thread_ts": THREAD},
        "container": {"message_ts": CARD_TS, "thread_ts": THREAD},
        "trigger_id": "TRIG",
        "actions": [{"action_id": "req_switch_epif", "value": btn["value"]}],
    }
    ack, respond = MagicMock(), MagicMock()
    app.handle_req_switch_epif(ack, body, respond, client)
    return ack, respond


def _client():
    client = MagicMock()
    client.conversations_replies.return_value = {
        "messages": [{"ts": THREAD, "text": "Logged to row 42"}]
    }
    return client


def _input_initial(view, block_id):
    for b in view["blocks"]:
        if b.get("block_id") == block_id:
            return b["element"].get("initial_value")
    raise AssertionError(f"no block {block_id}")


def test_switch_button_opens_the_epif_form_prefilled(monkeypatch):
    monkeypatch.setattr(slack_io, "resolve_requester", MagicMock(return_value="Dylan"))
    client = _client()
    ack, respond = _press("U_BUYER", client)
    ack.assert_called_once()
    client.views_open.assert_called_once()
    view = client.views_open.call_args[1]["view"]
    assert view["callback_id"] == config.STAGE2_CALLBACK_ID
    meta = json.loads(view["private_metadata"])
    assert meta["route"] == "epif"
    assert meta["switch"]["card_ts"] == CARD_TS
    assert meta["switch"]["row"] == 42
    assert meta["switch"]["assignee_id"] == "U_BUYER"
    assert _input_initial(view, "block_item_description") == "Optical post"
    respond.assert_not_called()


def test_switch_button_refuses_a_stranger_privately(monkeypatch):
    monkeypatch.setattr(slack_io, "resolve_requester", MagicMock(return_value="Someone Else"))
    client = _client()
    # Request is assigned, so a different buyer is a stranger too.
    ack, respond = _press("U_STRANGER", client)
    ack.assert_called_once()
    respond.assert_called_once()
    assert "🔒" in str(respond.call_args)
    client.views_open.assert_not_called()


def test_can_fill_or_switch_allows_four_roles_and_refuses_a_stranger():
    assigned = {"user_id": "U_REQ", "assignee_id": "U_BUYER"}
    unassigned = {"user_id": "U_REQ"}
    assert admin.can_fill_or_switch("U_X", assigned, "Alex", "Alex") is True  # requester by name
    assert admin.can_fill_or_switch("U_REQ", assigned, "Zed", "Nobody") is True  # requester by id
    assert admin.can_fill_or_switch("U_BUYER", assigned, "Zed", "Dylan") is True  # assignee
    assert admin.can_fill_or_switch("U_BUYER2", unassigned, "Zed", "Nobody") is True  # buyer, unassigned
    assert admin.can_fill_or_switch("U_ADMIN", assigned, "Zed", "Isaac") is True  # admin
    assert admin.can_fill_or_switch("U_STRANGER", assigned, "Alex", "Nobody") is False
    assert admin.can_fill_or_switch("U_BUYER2", assigned, "Alex", "Nobody") is False  # buyer, but assigned
