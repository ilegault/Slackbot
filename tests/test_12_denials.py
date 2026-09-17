"""Tests for Ticket 12: Ephemeral denials that never replace original messages.

WHY THIS EXISTS:
----------------
A block action's response via response_url replaces the message it was clicked on
unless told otherwise (replace_original=False). In production, an unauthorized user
clicking Approve caused the purchase request card to disappear completely, replaced
by a padlock message only that user could see.

These tests enforce that:
1. slack_io.deny wraps respond() with response_type="ephemeral" and replace_original=False.
2. Every button listener permission check calls slack_io.deny, producing ephemeral text,
   leaving the original message intact (replace_original=False), never updating the card
   (chat_update not called), and never calling the lifecycle or storage handler.
3. An AST source scan ensures no bare respond(text=...) calls exist in src/app.py.
"""
import ast
import inspect
import json
import os
from unittest.mock import MagicMock, patch

import pytest

from src import admin, app, lifecycle, log_writer, roster, slack_io

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(TESTS_DIR)
SRC_APP_PATH = os.path.join(PROJECT_ROOT, "src", "app.py")


def _make_button_body(action_id: str, user_id: str = "U_UNAUTHORIZED", state: str = "posted", row: int | None = 15, assignee_id: str | None = None):
    req_dict = {"item_description": "Widget", "row": row}
    if assignee_id is not None:
        req_dict["assignee_id"] = assignee_id
    elif state != "posted":
        req_dict["assignee_id"] = user_id

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


def _make_admin_action_body(action_id: str, user_id: str = "U_NON_ADMIN", payload: dict | None = None):
    return {
        "user": {"id": user_id},
        "channel": {"id": "C_ALERTS"},
        "message": {"ts": "2000.3000"},
        "actions": [
            {
                "action_id": action_id,
                "value": json.dumps(payload or {"slack_id": "U_NEW", "name": "New Person", "vendor": "New Vendor"}),
            }
        ],
    }


# ---------------------------------------------------------------------------
# 1. slack_io.deny helper tests
# ---------------------------------------------------------------------------

def test_slack_io_deny_signature_and_behavior():
    """slack_io.deny must accept (respond, text) and invoke respond with ephemeral and replace_original=False."""
    assert hasattr(slack_io, "deny"), "slack_io.deny must exist"
    sig = inspect.signature(slack_io.deny)
    params = list(sig.parameters.keys())
    assert params == ["respond", "text"], f"Expected parameters ['respond', 'text'], got {params}"

    respond = MagicMock()
    slack_io.deny(respond, "🔒 Access denied.")

    respond.assert_called_once_with(
        text="🔒 Access denied.",
        response_type="ephemeral",
        replace_original=False,
    )


# ---------------------------------------------------------------------------
# 2. Source scan: no bare respond() calls in src/app.py
# ---------------------------------------------------------------------------

def check_no_bare_respond_in_tree(tree: ast.AST, filename: str = "app.py"):
    """Check AST for any bare respond() call missing replace_original."""
    bare_calls = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            is_respond = False
            if isinstance(func, ast.Name) and func.id == "respond":
                is_respond = True
            elif isinstance(func, ast.Attribute) and func.attr == "respond":
                is_respond = True

            if is_respond:
                kw_names = [kw.arg for kw in node.keywords]
                if "replace_original" not in kw_names:
                    bare_calls.append(f"{filename}:{node.lineno} calls bare respond() without replace_original")
    return bare_calls


def test_source_scan_no_bare_respond_in_app():
    """Ensure every respond call in src/app.py passes replace_original or uses slack_io.deny."""
    with open(SRC_APP_PATH, "r", encoding="utf-8") as f:
        tree = ast.parse(f.read(), filename=SRC_APP_PATH)

    bare_calls = check_no_bare_respond_in_tree(tree, "src/app.py")
    assert not bare_calls, "\n".join(bare_calls)


def test_source_scan_detects_bare_respond():
    """Verify check_no_bare_respond_in_tree detects bare respond calls."""
    snippet = "def handler(respond):\n    respond(text='error')\n"
    tree = ast.parse(snippet)
    bare = check_no_bare_respond_in_tree(tree, "snippet.py")
    assert len(bare) == 1
    assert "calls bare respond() without replace_original" in bare[0]

    # Explicit replace_original=False is accepted
    valid_snippet = "def handler(respond):\n    respond(text='error', replace_original=False)\n"
    valid_tree = ast.parse(valid_snippet)
    assert len(check_no_bare_respond_in_tree(valid_tree, "valid.py")) == 0


def test_all_15_respond_sites_in_app_use_slack_io_deny():
    """Assert refusal/informational respond sites in src/app.py route through slack_io.deny.

    Ticket 12 introduced 15 sites; Ticket 16 added the unknown-word reply site in dispatch_command.
    """
    with open(SRC_APP_PATH, "r", encoding="utf-8") as f:
        tree = ast.parse(f.read(), filename=SRC_APP_PATH)

    deny_call_count = 0
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Attribute) and func.attr == "deny":
                deny_call_count += 1

    assert deny_call_count >= 15, f"Expected at least 15 calls to slack_io.deny in src/app.py, found {deny_call_count}"


# ---------------------------------------------------------------------------
# 3. Parametrized button listener denials: all listeners assert all 4 guarantees
# ---------------------------------------------------------------------------

BUTTON_DENIAL_SCENARIOS = [
    # (action_name, handler_func, body_factory, patches, expected_role_keyword, mock_target_to_assert_not_called)
    (
        "approve_new_requester",
        app.handle_approve_new_requester_action,
        lambda: _make_admin_action_body("approve_new_requester"),
        [(admin, "is_admin_user", False)],
        "bot administrators",
        (roster, "add_requester"),
    ),
    (
        "approve_new_admin",
        app.handle_approve_new_admin_action,
        lambda: _make_admin_action_body("approve_new_admin"),
        [(admin, "is_admin_user", False)],
        "bot administrators",
        (roster, "add_admin"),
    ),
    (
        "approve_new_vendor",
        app.handle_approve_new_vendor_action,
        lambda: _make_admin_action_body("approve_new_vendor"),
        [(admin, "is_admin_user", False)],
        "bot administrators",
        (roster, "add_vendor"),
    ),
    (
        "req_approve",
        app.handle_req_approve_action,
        lambda: _make_button_body("req_approve", state="posted"),
        [(admin, "is_approved_reviewer", False)],
        "authorized approvers",
        (lifecycle, "handle_epif_processing"),
    ),
    (
        "req_processed_unassigned",
        app.handle_req_processed_action,
        lambda: {
            "user": {"id": "U_BUYER"},
            "channel": {"id": "C_PURCHASING"},
            "message": {"ts": "1000.2000"},
            "container": {"message_ts": "1000.2000", "thread_ts": "1000.2000"},
            "actions": [{
                "action_id": "req_processed",
                "value": json.dumps({"state": "approved", "row": 15, "request": {"item_description": "W", "row": 15}, "history": []}),
            }],
        },
        [],
        "assigned to a buyer",
        (lifecycle, "handle_processed"),
    ),
    (
        "req_processed_non_assignee",
        app.handle_req_processed_action,
        lambda: _make_button_body("req_processed", user_id="U_OTHER", state="approved", assignee_id="U_ASSIGNED"),
        [(admin, "is_admin_user", False)],
        "assigned buyer",
        (lifecycle, "handle_processed"),
    ),
    (
        "req_processed_unregistered",
        app.handle_req_processed_action,
        lambda: _make_button_body("req_processed", user_id="U_UNREGISTERED", state="approved", assignee_id="U_UNREGISTERED"),
        [(admin, "is_admin_user", False), (slack_io, "resolve_requester", MagicMock(return_value=None))],
        "registered in the lab roster",
        (lifecycle, "handle_processed"),
    ),
    (
        "req_decline",
        app.handle_req_decline_action,
        lambda: _make_button_body("req_decline", state="posted"),
        [(admin, "is_approved_reviewer", False)],
        "authorized approvers",
        (lifecycle, "handle_decline"),
    ),
    (
        "req_cancel",
        app.handle_req_cancel_action,
        lambda: _make_button_body("req_cancel", state="approved", row=15),
        [(admin, "is_approved_reviewer", False), (admin, "is_admin_user", False)],
        "approvers and admins",
        (lifecycle, "handle_cancel"),
    ),
    (
        "req_confirmed_non_assignee",
        app.handle_req_confirmed_action,
        lambda: _make_button_body("req_confirmed", user_id="U_OTHER", state="processed", assignee_id="U_ASSIGNED"),
        [(admin, "is_admin_user", False)],
        "assigned buyer or an admin",
        (lifecycle, "handle_confirmation"),
    ),
    (
        "req_confirmed_unregistered",
        app.handle_req_confirmed_action,
        lambda: _make_button_body("req_confirmed", user_id="U_UNREGISTERED", state="processed", assignee_id="U_UNREGISTERED"),
        [(admin, "is_admin_user", False), (slack_io, "resolve_requester", MagicMock(return_value=None))],
        "registered in the lab roster",
        (lifecycle, "handle_confirmation"),
    ),
    (
        "req_delivered_non_assignee",
        app.handle_req_delivered_action,
        lambda: _make_button_body("req_delivered", user_id="U_OTHER", state="confirmed", assignee_id="U_ASSIGNED"),
        [(admin, "is_admin_user", False)],
        "assigned buyer or an admin",
        (lifecycle, "handle_delivery"),
    ),
    (
        "req_delivered_unregistered",
        app.handle_req_delivered_action,
        lambda: _make_button_body("req_delivered", user_id="U_UNREGISTERED", state="confirmed", assignee_id="U_UNREGISTERED"),
        [(admin, "is_admin_user", False), (slack_io, "resolve_requester", MagicMock(return_value=None))],
        "registered in the lab roster",
        (lifecycle, "handle_delivery"),
    ),
]


@pytest.mark.parametrize(
    "name,handler_func,body_factory,patch_defs,expected_role,mock_target",
    BUTTON_DENIAL_SCENARIOS,
    ids=[s[0] for s in BUTTON_DENIAL_SCENARIOS],
)
def test_button_listeners_ephemeral_denial_leaves_message_intact(
    name, handler_func, body_factory, patch_defs, expected_role, mock_target
):
    """Every button listener when permission fails:
    1. Produces denial text naming role.
    2. Passes replace_original=False and response_type='ephemeral' to respond.
    3. Does NOT call chat_update on client.
    4. Does NOT call target lifecycle or storage handler.
    """
    ack = MagicMock()
    respond = MagicMock()
    client = MagicMock()
    body = body_factory()

    target_mod, target_fn_name = mock_target

    with patch.object(target_mod, target_fn_name) as mock_action_fn:
        # Apply patch definitions
        ctxs = []
        for (m, fn, val) in patch_defs:
            if callable(val):
                ctxs.append(patch.object(m, fn, val))
            else:
                ctxs.append(patch.object(m, fn, return_value=val))
        for ctx in ctxs:
            ctx.start()
        try:
            handler_func(ack, body, respond, client)
        finally:
            for ctx in reversed(ctxs):
                ctx.stop()

    # 1. ack called
    ack.assert_called_once()

    # 2. respond called with ephemeral and replace_original=False
    respond.assert_called_once()
    call_kwargs = respond.call_args[1]
    denial_text = call_kwargs.get("text", "")
    assert expected_role in denial_text, f"Expected role '{expected_role}' in denial text: '{denial_text}'"
    assert call_kwargs.get("response_type") == "ephemeral", f"Expected response_type='ephemeral', got {call_kwargs}"
    assert call_kwargs.get("replace_original") is False, f"Expected replace_original=False, got {call_kwargs}"

    # 3. chat_update not called
    client.chat_update.assert_not_called()

    # 4. lifecycle / storage handler not called
    mock_action_fn.assert_not_called()


# ---------------------------------------------------------------------------
# 4. Approve button specific denial test (Acceptance Criterion 4)
# ---------------------------------------------------------------------------

def test_non_approver_clicking_approve_handler_not_called():
    """A non-approver clicking Approve produces an ephemeral denial and handle_epif_processing is not called."""
    ack = MagicMock()
    respond = MagicMock()
    client = MagicMock()
    body = _make_button_body("req_approve", user_id="U_NOT_APPROVER", state="posted")

    with patch.object(admin, "is_approved_reviewer", return_value=False), \
         patch.object(lifecycle, "handle_epif_processing") as mock_handle_epif, \
         patch.object(log_writer, "append_row") as mock_append:
        app.handle_req_approve_action(ack, body, respond, client)

    ack.assert_called_once()
    respond.assert_called_once()
    assert respond.call_args[1]["replace_original"] is False
    assert respond.call_args[1]["response_type"] == "ephemeral"
    assert "Only authorized approvers" in respond.call_args[1]["text"]

    client.chat_update.assert_not_called()
    mock_handle_epif.assert_not_called()
    mock_append.assert_not_called()


# ---------------------------------------------------------------------------
# 5. Slash commands purchasing-help and roster-list pass replace_original=False
# ---------------------------------------------------------------------------

def test_slash_command_purchasing_help_passes_replace_original_false():
    """/purchasing-help responds with replace_original=False."""
    ack = MagicMock()
    respond = MagicMock()
    app.handle_purchasing_help_command(ack, respond)

    ack.assert_called_once()
    respond.assert_called_once()
    assert respond.call_args[1]["replace_original"] is False
    assert respond.call_args[1]["response_type"] == "ephemeral"


def test_slash_command_roster_list_passes_replace_original_false():
    """/roster-list responds with replace_original=False."""
    ack = MagicMock()
    respond = MagicMock()
    body = {"user_id": "U_ANY"}

    with patch.object(roster, "get_requesters", return_value={"U1": "Alice"}), \
         patch.object(roster, "get_vendors", return_value=["Fisher"]):
        app.handle_roster_list_command(ack, body, respond)

    ack.assert_called_once()
    respond.assert_called_once()
    assert respond.call_args[1]["replace_original"] is False
    assert respond.call_args[1]["response_type"] == "ephemeral"
