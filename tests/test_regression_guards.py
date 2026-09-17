"""Regression guards for the whole lifecycle surface and architectural invariants.

WHY THIS EXISTS:
----------------
T1–T4 shipped before strict test-first enforcement existed. The /roster-list
channel_not_found failure is the shape of what untested code costs: the handler ran,
built its text correctly, and failed at the last step because it called
chat_postEphemeral where it had no channel membership.

These regression guards enforce cross-cutting invariants across the bot:
1: All slash commands are registered in Bolt's real listener registry, ack first,
   and never call chat_postEphemeral.
2. chat_postEphemeral appears nowhere in src/ (Ticket 19 removes the final view-submission call site).
3. The log_request middleware logs start and completion records, handles exceptions
   without swallowing them, and emits a WARNING for requests taking > 2000 ms.
4. build_request_blocks returns exactly one primary next-step button per non-final
   state and none for terminal delivered.
5. Every lifecycle button's permission denial leaves the message unchanged and writes
   nothing — tested independently per button.
6. /roster-set-name modal returns a field error and emits no alert when submitting a name already held by another member.
8. Only log_writer opens WORKBOOK_PATH (via zipfile.ZipFile).
9. Downward layering is maintained (no module in src/ imports app).
10. os.environ is read nowhere in src/ outside config.py (Ticket 15).
"""
import ast
import json
import logging
import os
import sys
from unittest.mock import MagicMock, call, patch

import pytest

# Determine project root and src directory
_CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(_CURRENT_DIR) if os.path.basename(_CURRENT_DIR) == "tests" else _CURRENT_DIR
SRC_DIR = os.path.join(PROJECT_ROOT, "src")
for p in (PROJECT_ROOT, SRC_DIR):
    if p not in sys.path:
        sys.path.insert(0, p)

from src import admin, app, blocks, config, log_writer, roster


@pytest.fixture(autouse=True)
def setup_test_roster(tmp_path, monkeypatch):
    """Ensure tests run against an isolated roster and dummy env."""
    test_roster_file = str(tmp_path / "roster.json")
    monkeypatch.setattr(roster, "ROSTER_PATH", test_roster_file)
    roster.load_roster()
    return test_roster_file


# ---------------------------------------------------------------------------
# 1. Slash command registration in Bolt's real listener registry
# ---------------------------------------------------------------------------

def test_all_five_slash_commands_registered_in_bolt_registry():
    """Verify all 5 slash commands are registered in Bolt's real listener registry.

    Does not monkeypatch or use stand-in registries; inspects app.app._listeners directly.
    """
    expected_commands = {
        "/new-purchase",
        "/purchasing-help",
        "/blank-template",
        "/roster-list",
        "/roster-set-name",
    }
    registered_commands = set()
    for listener in app.app._listeners:
        for matcher in getattr(listener, "matchers", []):
            func = getattr(matcher, "func", None)
            if func and getattr(func, "__closure__", None):
                for cell in func.__closure__:
                    val = cell.cell_contents
                    if isinstance(val, str) and val.startswith("/"):
                        registered_commands.add(val)

    assert expected_commands.issubset(
        registered_commands
    ), f"Missing registered slash commands: {expected_commands - registered_commands}"


# ---------------------------------------------------------------------------
# 2. Slash commands never call chat_postEphemeral & ack before client calls
# ---------------------------------------------------------------------------

def test_slash_commands_ack_before_client_and_never_call_post_ephemeral():
    """Verify each slash command handler calls ack() before any client call and never calls chat_postEphemeral.

    This is the T1 guard: chat_postEphemeral requires channel membership and fails with
    channel_not_found in DMs. Slash commands must respond with respond() or modal opens.
    """
    commands_to_test = [
        (
            "/new-purchase",
            app.handle_new_purchase_command,
            {"trigger_id": "trig_123", "user_id": "U123"},
            True,   # uses client
            False,  # does not use respond
        ),
        (
            "/purchasing-help",
            app.handle_purchasing_help_command,
            {"user_id": "U123"},
            False,  # does not use client
            True,   # uses respond
        ),
        (
            "/blank-template",
            app.handle_blank_template_command,
            {"channel_id": "C123", "user_id": "U123"},
            True,
            False,
        ),
        (
            "/roster-list",
            app.handle_roster_list_command,
            {"user_id": "U123"},
            False,
            True,
        ),
        (
            "/roster-set-name",
            app.handle_roster_set_name_command,
            {"trigger_id": "trig_456", "user_id": "U123", "channel_id": "C123"},
            True,
            False,
        ),
    ]

    for cmd_name, handler, body, uses_client, uses_respond in commands_to_test:
        manager = MagicMock()
        ack = MagicMock()
        client = MagicMock()
        respond = MagicMock()
        manager.attach_mock(ack, "ack")
        manager.attach_mock(client, "client")
        manager.attach_mock(respond, "respond")

        if uses_client and not uses_respond:
            handler(ack, body, client)
        elif uses_respond and not uses_client:
            handler(ack, respond) if handler.__code__.co_argcount == 2 else handler(ack, body, respond)
        else:
            handler(ack, body, respond, client)

        # Assert ack() was invoked first
        assert ack.call_count == 1, f"{cmd_name} must call ack() exactly once"
        assert manager.mock_calls[0] == call.ack(), f"{cmd_name} did not call ack() before other operations"

        # Assert client.chat_postEphemeral was never called
        client.chat_postEphemeral.assert_not_called()


# ---------------------------------------------------------------------------
# 3. Pin exactly one chat_postEphemeral call site in src/
# ---------------------------------------------------------------------------

def test_zero_chat_post_ephemeral_call_sites_in_src():
    """Pin that zero chat_postEphemeral call sites remain in src/.

    Per AGENTS.md Invariant 5 and Ticket 19:
    chat_postEphemeral requires channel membership and fails with channel_not_found
    otherwise — including in a DM with the bot.
    With Ticket 19 removing the roster-set-name view submission site, zero
    chat_postEphemeral calls remain in src/. All slash commands, block actions,
    and views use respond(...) or slack_io helpers.
    """
    call_sites = []
    for root, _, files in os.walk(SRC_DIR):
        for fname in files:
            if not fname.endswith(".py"):
                continue
            fpath = os.path.join(root, fname)
            rel_path = os.path.relpath(fpath, PROJECT_ROOT).replace("\\", "/")
            with open(fpath, "r", encoding="utf-8") as f:
                tree = ast.parse(f.read(), filename=fpath)
            for node in ast.walk(tree):
                if isinstance(node, ast.Call):
                    func = node.func
                    if isinstance(func, ast.Attribute) and func.attr == "chat_postEphemeral":
                        call_sites.append((rel_path, node.lineno))

    assert len(call_sites) == 0, (
        f"Expected exactly 0 chat_postEphemeral call sites in src/, found {len(call_sites)}: {call_sites}"
    )


# ---------------------------------------------------------------------------
# 4. log_request middleware: start, completion, exceptions, and >2000ms warning
# ---------------------------------------------------------------------------

def test_log_request_middleware_start_and_completion_records(caplog):
    """Verify log_request produces start record and completion record on normal return."""
    body = {"command": "/purchasing-help", "user_id": "U123"}
    next_fn = MagicMock(return_value="ok")

    with caplog.at_level(logging.INFO, logger="p-bot"):
        result = app.log_request(body, next_fn)

    assert result == "ok"
    next_fn.assert_called_once()

    messages = [r.message for r in caplog.records if r.name == "p-bot"]
    assert any("Incoming" in m and "/purchasing-help" in m for m in messages), "Missing incoming log record"
    assert any("Completed" in m and "/purchasing-help" in m for m in messages), "Missing completion log record"


def test_log_request_middleware_handler_exception_logs_and_reraises(caplog):
    """Verify log_request logs exception AND produces completion record even when handler raises."""
    body = {"command": "/new-purchase", "user_id": "U123"}

    def failing_handler():
        raise ValueError("Simulated handler crash")

    with caplog.at_level(logging.INFO, logger="p-bot"):
        with pytest.raises(ValueError, match="Simulated handler crash"):
            app.log_request(body, failing_handler)

    messages = [r.message for r in caplog.records if r.name == "p-bot"]
    assert any("Incoming" in m for m in messages), "Missing incoming log record"
    assert any("Handler raised exception" in m and "Simulated handler crash" in m for m in messages), (
        "Missing exception log record"
    )
    assert any("Completed" in m for m in messages), "Missing completion record in finally block"


def test_log_request_middleware_duration_over_2000ms_logged_at_warning(caplog):
    """Verify a request taking over 2 000 ms emits a completion log at WARNING level."""
    body = {"command": "/blank-template", "user_id": "U123"}
    next_fn = MagicMock(return_value="done")

    # Mock time.monotonic to simulate 2500 ms elapsed time
    with patch("time.monotonic", side_effect=[100.0, 102.5]):
        with caplog.at_level(logging.DEBUG, logger="p-bot"):
            app.log_request(body, next_fn)

    warning_records = [
        r for r in caplog.records
        if r.name == "p-bot" and r.levelno == logging.WARNING and "> 2000 ms threshold" in r.message
    ]
    assert len(warning_records) >= 1, "Expected WARNING log record for duration > 2000 ms"


# ---------------------------------------------------------------------------
# 5. build_request_blocks returns 1 next-step button per non-final state, 0 for delivered
# ---------------------------------------------------------------------------

def test_build_request_blocks_next_step_buttons():
    """Verify build_request_blocks returns exactly one primary next-step button per non-final state,

    and none for delivered.
    """
    sample_req = {
        "item_description": "Oscilloscope Probe",
        "total_price": 120.00,
        "vendor": "DigiKey",
        "payment_method": "P-card",
        "category": "Research/Lab Supplies (3105)",
        "project_id": "PG000025831",
        "fund": "133",
        "delivery_room": "ERB 212",
        "purpose": "Sensor testing",
        "requester": "Isaac",
        "user_id": "U123",
    }

    expected_primary_action = {
        "posted": "req_approve",
        "approved": "req_processed",
        "processed": "req_confirmed",
        "confirmed": "req_delivered",
    }

    for state, expected_action_id in expected_primary_action.items():
        blks = blocks.build_request_blocks(state, sample_req)
        action_blocks = [b for b in blks if b.get("type") == "actions"]
        assert len(action_blocks) == 1, f"State '{state}' must have exactly 1 action block"
        primary_btns = [
            elem for elem in action_blocks[0].get("elements", [])
            if elem.get("style") == "primary"
        ]
        assert len(primary_btns) == 1, f"State '{state}' must have exactly 1 primary next-step button"
        assert primary_btns[0].get("action_id") == expected_action_id, (
            f"State '{state}' expected action_id '{expected_action_id}', got '{primary_btns[0].get('action_id')}'"
        )

    # Terminal state: delivered -> 0 action blocks
    blks_delivered = blocks.build_request_blocks("delivered", sample_req)
    action_blocks_deliv = [b for b in blks_delivered if b.get("type") == "actions"]
    assert len(action_blocks_deliv) == 0, "Terminal state 'delivered' must have no action buttons"


# ---------------------------------------------------------------------------
# 6. Lifecycle button permission denials (one test per button)
# ---------------------------------------------------------------------------

def _make_button_body(action_id: str, user_id: str, state: str = "posted", row: int | None = 15, assignee_id: str | None = None):
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


def test_permission_denial_req_approve():
    """req_approve clicked by non-approver leaves message unchanged and writes nothing."""
    ack = MagicMock()
    respond = MagicMock()
    client = MagicMock()
    body = _make_button_body("req_approve", user_id="U_NON_APPROVER", state="posted")

    with patch.object(admin, "is_approved_reviewer", return_value=False), \
         patch("src.lifecycle.handle_epif_processing") as mock_handle_epif, \
         patch.object(log_writer, "append_row") as mock_append:
        app.handle_req_approve_action(ack, body, respond, client)

    ack.assert_called_once()
    respond.assert_called_once()
    assert "Only authorized approvers" in respond.call_args[1]["text"]
    assert respond.call_args[1].get("replace_original") is False
    assert respond.call_args[1].get("response_type") == "ephemeral"
    client.chat_update.assert_not_called()
    client.chat_postMessage.assert_not_called()
    mock_handle_epif.assert_not_called()
    mock_append.assert_not_called()


def test_permission_denial_req_processed_unassigned():
    """req_processed clicked on unassigned request is refused."""
    ack = MagicMock()
    respond = MagicMock()
    client = MagicMock()
    body = {
        "user": {"id": "U_BUYER"},
        "channel": {"id": "C_PURCHASING"},
        "message": {"ts": "1000.2000"},
        "container": {"message_ts": "1000.2000", "thread_ts": "1000.2000"},
        "actions": [
            {
                "action_id": "req_processed",
                "value": json.dumps({
                    "state": "approved",
                    "row": 15,
                    "request": {"item_description": "Widget", "row": 15},  # no assignee_id
                    "history": [],
                }),
            }
        ],
    }

    app.handle_req_processed_action(ack, body, respond, client)

    ack.assert_called_once()
    respond.assert_called_once()
    assert "must be assigned to a buyer" in respond.call_args[1]["text"]
    assert respond.call_args[1].get("replace_original") is False
    assert respond.call_args[1].get("response_type") == "ephemeral"
    client.chat_update.assert_not_called()
    client.chat_postMessage.assert_not_called()


def test_permission_denial_req_processed_non_assignee():
    """req_processed clicked by user who is not assignee or admin is refused."""
    ack = MagicMock()
    respond = MagicMock()
    client = MagicMock()
    body = {
        "user": {"id": "U_OTHER_BUYER"},
        "channel": {"id": "C_PURCHASING"},
        "message": {"ts": "1000.2000"},
        "container": {"message_ts": "1000.2000", "thread_ts": "1000.2000"},
        "actions": [
            {
                "action_id": "req_processed",
                "value": json.dumps({
                    "state": "approved",
                    "row": 15,
                    "request": {"item_description": "Widget", "row": 15, "assignee_id": "U_ASSIGNED_BUYER"},
                    "history": [],
                }),
            }
        ],
    }

    with patch.object(admin, "is_admin_user", return_value=False):
        app.handle_req_processed_action(ack, body, respond, client)

    ack.assert_called_once()
    respond.assert_called_once()
    assert "Only the assigned buyer" in respond.call_args[1]["text"]
    assert respond.call_args[1].get("replace_original") is False
    assert respond.call_args[1].get("response_type") == "ephemeral"
    client.chat_update.assert_not_called()
    client.chat_postMessage.assert_not_called()


def test_permission_denial_req_processed():
    """req_processed clicked by unregistered user leaves message unchanged and writes nothing."""
    ack = MagicMock()
    respond = MagicMock()
    client = MagicMock()
    body = _make_button_body("req_processed", user_id="U_UNREGISTERED", state="claimed")

    with patch("src.slack_io.resolve_requester", return_value=None), \
         patch("src.lifecycle.handle_processed") as mock_processed:
        app.handle_req_processed_action(ack, body, respond, client)

    ack.assert_called_once()
    respond.assert_called_once()
    assert "You must be registered in the lab roster" in respond.call_args[1]["text"]
    assert respond.call_args[1].get("replace_original") is False
    assert respond.call_args[1].get("response_type") == "ephemeral"
    client.chat_update.assert_not_called()
    client.chat_postMessage.assert_not_called()
    mock_processed.assert_not_called()


def test_permission_denial_req_confirmed():
    """req_confirmed clicked by unregistered user leaves message unchanged and writes nothing."""
    ack = MagicMock()
    respond = MagicMock()
    client = MagicMock()
    body = _make_button_body("req_confirmed", user_id="U_UNREGISTERED", state="processed")

    with patch("src.slack_io.resolve_requester", return_value=None), \
         patch("src.lifecycle.handle_confirmation") as mock_confirmation:
        app.handle_req_confirmed_action(ack, body, respond, client)

    ack.assert_called_once()
    respond.assert_called_once()
    assert "You must be registered in the lab roster" in respond.call_args[1]["text"]
    assert respond.call_args[1].get("replace_original") is False
    assert respond.call_args[1].get("response_type") == "ephemeral"
    client.chat_update.assert_not_called()
    client.chat_postMessage.assert_not_called()
    mock_confirmation.assert_not_called()


def test_permission_denial_req_delivered():
    """req_delivered clicked by unregistered user leaves message unchanged and writes nothing."""
    ack = MagicMock()
    respond = MagicMock()
    client = MagicMock()
    body = _make_button_body("req_delivered", user_id="U_UNREGISTERED", state="confirmed")

    with patch("src.slack_io.resolve_requester", return_value=None), \
         patch("src.lifecycle.handle_delivery") as mock_delivery:
        app.handle_req_delivered_action(ack, body, respond, client)

    ack.assert_called_once()
    respond.assert_called_once()
    assert "You must be registered in the lab roster" in respond.call_args[1]["text"]
    assert respond.call_args[1].get("replace_original") is False
    assert respond.call_args[1].get("response_type") == "ephemeral"
    client.chat_update.assert_not_called()
    client.chat_postMessage.assert_not_called()
    mock_delivery.assert_not_called()


def test_permission_denial_req_decline():
    """req_decline clicked by non-approver leaves message unchanged and writes nothing."""
    ack = MagicMock()
    respond = MagicMock()
    client = MagicMock()
    body = _make_button_body("req_decline", user_id="U_NON_APPROVER", state="posted")

    with patch.object(admin, "is_approved_reviewer", return_value=False), \
         patch("src.lifecycle.handle_decline") as mock_decline:
        app.handle_req_decline_action(ack, body, respond, client)

    ack.assert_called_once()
    respond.assert_called_once()
    assert "Only authorized approvers can decline purchase requests" in respond.call_args[1]["text"]
    assert respond.call_args[1].get("replace_original") is False
    assert respond.call_args[1].get("response_type") == "ephemeral"
    client.chat_update.assert_not_called()
    client.chat_postMessage.assert_not_called()
    mock_decline.assert_not_called()


def test_permission_denial_req_cancel():
    """req_cancel clicked by a buyer (who is not approver or admin) is refused, message unchanged, row untouched."""
    ack = MagicMock()
    respond = MagicMock()
    client = MagicMock()
    body = _make_button_body("req_cancel", user_id="U_BUYER_ONLY", state="approved", row=18)

    with patch.object(admin, "is_approved_reviewer", return_value=False), \
         patch.object(admin, "is_admin_user", return_value=False), \
         patch.object(log_writer, "blank_row") as mock_blank:
        app.handle_req_cancel_action(ack, body, respond, client)

    ack.assert_called_once()
    respond.assert_called_once()
    assert "Only approvers and admins can cancel purchase requests" in respond.call_args[1]["text"]
    assert respond.call_args[1].get("replace_original") is False
    assert respond.call_args[1].get("response_type") == "ephemeral"
    client.chat_update.assert_not_called()
    client.chat_postMessage.assert_not_called()
    mock_blank.assert_not_called()


# ---------------------------------------------------------------------------
# 7. /roster-set-name invalid name returns modal error and posts NO alert
# ---------------------------------------------------------------------------

def test_roster_set_name_already_held_name_returns_error_and_posts_no_alert(monkeypatch):
    """/roster-set-name with a name another member holds returns a modal error and posts no alert."""
    ack = MagicMock()
    client = MagicMock()
    monkeypatch.setattr(config, "ADMIN_ALERT_CHANNEL", "C_ADMIN_ALERTS")

    # Register Isaac under a lab member Slack ID
    roster.add_requester("U_MEMBER", "Isaac")
    view_invalid = {
        "state": {
            "values": {
                "block_proposed_name": {
                    "proposed_name": {"value": "Isaac"}
                }
            }
        },
        "private_metadata": json.dumps({"user_id": "U_UNKNOWN", "channel_id": "C_MAIN"}),
    }


    app.handle_roster_set_name_submit(ack, {"user": {"id": "U_UNKNOWN"}}, client, view_invalid)

    ack.assert_called_once()
    assert ack.call_args[1]["response_action"] == "errors"
    assert "block_proposed_name" in ack.call_args[1]["errors"]
    assert "already held" in ack.call_args[1]["errors"]["block_proposed_name"]

    # Assert no alert was posted anywhere
    client.chat_postMessage.assert_not_called()



# ---------------------------------------------------------------------------
# 8. Layering invariant: no module under src/ imports app
# ---------------------------------------------------------------------------

def test_no_module_in_src_imports_app():
    """Assert no module under src/ other than root app.py imports app or src.app."""
    for root, _, files in os.walk(SRC_DIR):
        for fname in files:
            if not fname.endswith(".py"):
                continue
            fpath = os.path.join(root, fname)
            rel_path = os.path.relpath(fpath, PROJECT_ROOT).replace("\\", "/")

            with open(fpath, "r", encoding="utf-8") as f:
                tree = ast.parse(f.read(), filename=fpath)

            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        assert alias.name not in ("app", "src.app"), (
                            f"{rel_path}:{node.lineno} imports '{alias.name}'. No module in src/ may import app."
                        )
                elif isinstance(node, ast.ImportFrom):
                    module = node.module or ""
                    imported_names = [alias.name for alias in node.names]
                    assert module not in ("app", "src.app", ".app"), (
                        f"{rel_path}:{node.lineno} imports from '{module}'. No module in src/ may import from app."
                    )
                    if node.level > 0 and module in ("", "app"):
                        assert "app" not in imported_names, (
                            f"{rel_path}:{node.lineno} imports 'app' relatively. No module in src/ may import app."
                        )


# ---------------------------------------------------------------------------
# 9. Invariant: only log_writer opens WORKBOOK_PATH
# ---------------------------------------------------------------------------

def test_only_log_writer_opens_workbook_path():
    """Verify that log_writer is the only module under src/ that opens WORKBOOK_PATH (via ZipFile or open).

    Per AGENTS.md Invariant 2:
    'One writer for the workbook. Every write to Purchasing-Log.xlsx goes through
    log_writer via the lock-retry queue in queue_worker. Nothing else opens that file.'
    """
    for root, _, files in os.walk(SRC_DIR):
        for fname in files:
            if not fname.endswith(".py") or fname == "log_writer.py":
                continue
            fpath = os.path.join(root, fname)
            rel_path = os.path.relpath(fpath, PROJECT_ROOT).replace("\\", "/")

            with open(fpath, "r", encoding="utf-8") as f:
                tree = ast.parse(f.read(), filename=fpath)

            for node in ast.walk(tree):
                # Check for zipfile.ZipFile or ZipFile calls
                if isinstance(node, ast.Call):
                    func = node.func
                    if isinstance(func, ast.Attribute) and func.attr == "ZipFile":
                        pytest.fail(f"{rel_path}:{node.lineno} calls ZipFile. Only log_writer may open workbook.")
                    if isinstance(func, ast.Name) and func.id in ("ZipFile", "load_workbook"):
                        pytest.fail(f"{rel_path}:{node.lineno} calls {func.id}. Only log_writer may open workbook.")
                    if isinstance(func, ast.Attribute) and func.attr == "load_workbook":
                        pytest.fail(f"{rel_path}:{node.lineno} calls load_workbook. Only log_writer may open workbook.")

                    # Check open() calls: ensure WORKBOOK_PATH is not passed
                    if isinstance(func, ast.Name) and func.id == "open" and node.args:
                        first_arg = node.args[0]
                        if isinstance(first_arg, ast.Attribute) and first_arg.attr == "WORKBOOK_PATH":
                            pytest.fail(f"{rel_path}:{node.lineno} calls open(WORKBOOK_PATH). Only log_writer may open workbook.")
                        if isinstance(first_arg, ast.Name) and first_arg.id == "WORKBOOK_PATH":
                            pytest.fail(f"{rel_path}:{node.lineno} calls open(WORKBOOK_PATH). Only log_writer may open workbook.")


# ---------------------------------------------------------------------------
# 10. Invariant: os.environ is read nowhere in src/ outside config.py (Ticket 15)
# ---------------------------------------------------------------------------

def test_os_environ_read_nowhere_outside_config():
    """Assert os.environ is read nowhere in src/ except config.py.

    Per Ticket 15 / AGENTS.md Invariant 4:
    'Every constant has one home. Tunables, column letters, callback IDs and
    role lists live in config.py or the roster, never as a literal in a handler.'

    Grandfathered reads per Ticket 15 Out-of-Scope (SLACK_BOT_TOKEN, SLACK_APP_TOKEN, USERNAME).
    Fails if any new inline read is added outside config.py.
    """
    ALLOWED_BASELINE = {
        ("src/app.py", "SLACK_BOT_TOKEN"),
        ("src/app.py", "SLACK_APP_TOKEN"),
        ("src/slack_io.py", "SLACK_BOT_TOKEN"),
        ("src/path_validator.py", "USERNAME"),
    }

    discovered_reads = []

    for root, _, files in os.walk(SRC_DIR):
        for fname in files:
            if not fname.endswith(".py") or fname == "config.py":
                continue
            fpath = os.path.join(root, fname)
            rel_path = os.path.relpath(fpath, PROJECT_ROOT).replace("\\", "/")

            with open(fpath, "r", encoding="utf-8") as f:
                tree = ast.parse(f.read(), filename=fpath)

            for node in ast.walk(tree):
                if isinstance(node, ast.Call):
                    func = node.func
                    # os.environ.get("VAR")
                    if (
                        isinstance(func, ast.Attribute)
                        and func.attr == "get"
                        and isinstance(func.value, ast.Attribute)
                        and func.value.attr == "environ"
                        and isinstance(func.value.value, ast.Name)
                        and func.value.value.id == "os"
                    ):
                        var_name = node.args[0].value if node.args and isinstance(node.args[0], ast.Constant) else "UNKNOWN"
                        if (rel_path, var_name) not in ALLOWED_BASELINE:
                            discovered_reads.append((rel_path, node.lineno, f"os.environ.get('{var_name}')"))

                    # os.getenv("VAR")
                    if (
                        isinstance(func, ast.Attribute)
                        and func.attr == "getenv"
                        and isinstance(func.value, ast.Name)
                        and func.value.id == "os"
                    ):
                        var_name = node.args[0].value if node.args and isinstance(node.args[0], ast.Constant) else "UNKNOWN"
                        if (rel_path, var_name) not in ALLOWED_BASELINE:
                            discovered_reads.append((rel_path, node.lineno, f"os.getenv('{var_name}')"))

                # Catch direct subscript read: os.environ["VAR"]
                if isinstance(node, ast.Subscript) and isinstance(node.ctx, ast.Load):
                    val = node.value
                    if (
                        isinstance(val, ast.Attribute)
                        and val.attr == "environ"
                        and isinstance(val.value, ast.Name)
                        and val.value.id == "os"
                    ):
                        slice_node = node.slice
                        var_name = slice_node.value if isinstance(slice_node, ast.Constant) else "UNKNOWN"
                        if (rel_path, var_name) not in ALLOWED_BASELINE:
                            discovered_reads.append((rel_path, node.lineno, f"os.environ['{var_name}']"))

    assert not discovered_reads, (
        "Discovered unapproved inline environment variable read(s) in src/:\n"
        + "\n".join(f"  {r[0]}:{r[1]} -> {r[2]}" for r in discovered_reads)
        + "\nPer Invariant 4, all constants must live in config.py."
    )

