"""Tests for Ticket 66: One permission rule for Mark Processed, Confirmed and Delivered — assignee, admin or approver.

Covers:
- admin.can_update_request predicate truth table.
- Approver succeeds on all three stage buttons (processed, confirmed, delivered).
- Different buyer is refused privately on all three buttons.
- Unassigned request is refused privately on all three buttons.
- Real write (log_writer.update_row) follows an approver's Mark Processed click.
"""
import json
from unittest.mock import MagicMock

import pytest

from src import admin, app, config, lifecycle, log_writer, queue_worker, roster, slack_io, text_rules


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
def sync_queue(monkeypatch):
    def fake_submit(action_fn, *args, **kwargs):
        result = action_fn()
        if "success_callback" in kwargs and kwargs["success_callback"]:
            kwargs["success_callback"](result)
        return result
    monkeypatch.setattr(queue_worker, "submit_write_task", fake_submit)


def _make_stage_body(action_id: str, user_id: str, state: str, assignee_id: str | None = "U_BUYER", row: int = 15):
    req_dict = {"item_description": "Widget", "row": row, "total_price": 42.0}
    if assignee_id is not None:
        req_dict["assignee_id"] = assignee_id

    return {
        "user": {"id": user_id},
        "channel": {"id": "C_PURCHASING"},
        "message": {"ts": "1000.2000"},
        "container": {"message_ts": "1000.2000", "thread_ts": "1000.2000"},
        "actions": [
            {
                "action_id": action_id,
                "value": json.dumps({
                    "state": state,
                    "row": row,
                    "request": req_dict,
                    "history": [],
                }),
            }
        ],
    }


# ---------------------------------------------------------------------------
# Acceptance Criterion 1: Predicate truth table
# ---------------------------------------------------------------------------

def test_can_update_request_truth_table(clean_roster):
    """The assignee, an admin and an approver -> True;

    a different buyer, a requester with no role, and None -> False;
    any user with assignee_id=None (or empty) -> False.
    """
    assignee = "U_BUYER"

    # Authorized roles -> True
    assert admin.can_update_request(assignee, assignee) is True
    assert admin.can_update_request("U_ADMIN", assignee) is True
    assert admin.can_update_request("U_CHARLIE", assignee) is True

    # Unauthorized -> False
    assert admin.can_update_request("U_OTHER_BUYER", assignee) is False
    assert admin.can_update_request("U_REQ", assignee) is False
    assert admin.can_update_request(None, assignee) is False
    assert admin.can_update_request("", assignee) is False

    # Unassigned (assignee_id is None or empty) -> False for all
    for uid in (assignee, "U_ADMIN", "U_CHARLIE", "U_OTHER_BUYER", "U_REQ", None):
        assert admin.can_update_request(uid, None) is False
        assert admin.can_update_request(uid, "") is False


# ---------------------------------------------------------------------------
# Acceptance Criterion 2: Approver succeeds on all three stage buttons
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "action_id,handler_func,lifecycle_func_name,current_state",
    [
        ("req_processed", app.handle_req_processed_action, "handle_processed", "approved"),
        ("req_confirmed", app.handle_req_confirmed_action, "handle_confirmation", "processed"),
        ("req_delivered", app.handle_req_delivered_action, "handle_delivery", "confirmed"),
    ],
)
def test_approver_succeeds_on_all_three_buttons(clean_roster, monkeypatch, action_id, handler_func, lifecycle_func_name, current_state):
    """For each of the three listeners, a click by the approver on an assigned request

    calls the matching lifecycle handler once and does not call respond.
    """
    ack = MagicMock()
    respond = MagicMock()
    client = MagicMock()
    body = _make_stage_body(action_id, user_id="U_CHARLIE", state=current_state, assignee_id="U_BUYER")

    lifecycle_mock = MagicMock()
    monkeypatch.setattr(lifecycle, lifecycle_func_name, lifecycle_mock)

    handler_func(ack, body, respond, client)

    ack.assert_called_once()
    lifecycle_mock.assert_called_once()
    respond.assert_not_called()


# ---------------------------------------------------------------------------
# Acceptance Criterion 3: Different buyer is refused privately on all three
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "action_id,handler_func,lifecycle_func_name,current_state",
    [
        ("req_processed", app.handle_req_processed_action, "handle_processed", "approved"),
        ("req_confirmed", app.handle_req_confirmed_action, "handle_confirmation", "processed"),
        ("req_delivered", app.handle_req_delivered_action, "handle_delivery", "confirmed"),
    ],
)
def test_different_buyer_refused_privately_on_all_three(clean_roster, monkeypatch, action_id, handler_func, lifecycle_func_name, current_state):
    """A different buyer clicking any of the three stage buttons is refused privately

    naming the assignee, lifecycle handler is not called, chat_update not called.
    """
    ack = MagicMock()
    respond = MagicMock()
    client = MagicMock()
    body = _make_stage_body(action_id, user_id="U_OTHER_BUYER", state=current_state, assignee_id="U_BUYER")

    lifecycle_mock = MagicMock()
    monkeypatch.setattr(lifecycle, lifecycle_func_name, lifecycle_mock)

    handler_func(ack, body, respond, client)

    ack.assert_called_once()
    lifecycle_mock.assert_not_called()
    client.chat_update.assert_not_called()

    respond.assert_called_once_with(
        text=text_rules.format_stage_denial("U_BUYER"),
        response_type="ephemeral",
        replace_original=False,
    )


# ---------------------------------------------------------------------------
# Acceptance Criterion 4: Unassigned request refused on all three
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "action_id,handler_func,lifecycle_func_name,current_state",
    [
        ("req_processed", app.handle_req_processed_action, "handle_processed", "approved"),
        ("req_confirmed", app.handle_req_confirmed_action, "handle_confirmation", "processed"),
        ("req_delivered", app.handle_req_delivered_action, "handle_delivery", "confirmed"),
    ],
)
def test_unassigned_request_refused_on_all_three(clean_roster, monkeypatch, action_id, handler_func, lifecycle_func_name, current_state):
    """An unassigned request is refused on all three stage buttons with format_stage_unassigned(),

    lifecycle handler not called.
    """
    ack = MagicMock()
    respond = MagicMock()
    client = MagicMock()
    # Clicked by any user (even an admin or approver or buyer) when unassigned
    body = _make_stage_body(action_id, user_id="U_CHARLIE", state=current_state, assignee_id=None)

    lifecycle_mock = MagicMock()
    monkeypatch.setattr(lifecycle, lifecycle_func_name, lifecycle_mock)

    handler_func(ack, body, respond, client)

    ack.assert_called_once()
    lifecycle_mock.assert_not_called()
    client.chat_update.assert_not_called()

    respond.assert_called_once_with(
        text=text_rules.format_stage_unassigned(),
        response_type="ephemeral",
        replace_original=False,
    )


# ---------------------------------------------------------------------------
# Acceptance Criterion 5: Real write follows an approver's click
# ---------------------------------------------------------------------------

def test_real_write_follows_approver_click(clean_roster, sync_queue, monkeypatch):
    """With workbook functions replaced by recorders and sync_queue,

    the approver clicking Mark Processed causes log_writer.update_row to be called
    once with a dict containing config.COLUMN_DATE_PROCESSED.
    """
    ack = MagicMock()
    respond = MagicMock()
    client = MagicMock()
    client.chat_postMessage.return_value = {"ts": "2000.3000"}

    update_row_mock = MagicMock()
    monkeypatch.setattr(log_writer, "update_row", update_row_mock)
    monkeypatch.setattr(slack_io, "find_row_in_thread", lambda *a, **k: 15)

    body = _make_stage_body("req_processed", user_id="U_CHARLIE", state="approved", assignee_id="U_BUYER", row=15)

    app.handle_req_processed_action(ack, body, respond, client)

    ack.assert_called_once()
    respond.assert_not_called()
    update_row_mock.assert_called_once()
    call_args, call_kwargs = update_row_mock.call_args
    assert call_args[0] == 15
    fields_dict = call_args[1]
    assert config.COLUMN_DATE_PROCESSED in fields_dict
