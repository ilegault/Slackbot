"""Tests for Monitoring, Health Diagnostics, Remote Management, and Excel Lock Queue.

Validates the complete specification in docs/MONITORING_AND_QUEUE_SPEC.md:
1. Excel Lock Queue: serial execution, lock retries, thread notifications, and FIFO order.
2. Health & Diagnostics: system status, disk, memory, paths, and Block Kit builder.
3. Remote Log Viewer: line limits, token masking, and admin permission guarding.
4. Heartbeat & Proactive Alerts: startup/crash dispatcher and heartbeat monitor.
5. Lifecycle Management: update and restart safety checks.
"""
from datetime import date, datetime
import os
import platform
import shutil
import sys
import time
from unittest.mock import MagicMock, patch

import pytest

# Dynamic paths setup
_CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(_CURRENT_DIR) if os.path.basename(_CURRENT_DIR) == "tests" else _CURRENT_DIR
SRC_DIR = os.path.join(PROJECT_ROOT, "src")
for p in (PROJECT_ROOT, SRC_DIR):
    if p not in sys.path:
        sys.path.insert(0, p)

try:
    from src import admin, app, config, epif_parser, heartbeat, log_writer, queue_worker
except ImportError:
    import admin
    import app
    import config
    import epif_parser
    import heartbeat
    import log_writer
    import queue_worker

SAMPLES = os.path.join(PROJECT_ROOT, "samples")
FILLED = os.path.join(SAMPLES, "Prusa_EPIF__2799_PG000025831.pdf")
WORKBOOK = os.path.join(SAMPLES, "Purchasing-Log.xlsx")


@pytest.fixture
def workbook_copy(tmp_path):
    copy = tmp_path / "Purchasing-Log.xlsx"
    shutil.copy(WORKBOOK, copy)
    return str(copy)


@pytest.fixture
def filled_data():
    with open(FILLED, "rb") as f:
        return epif_parser.parse_epif(f.read())


# ==============================================================================
# 1. EXCEL LOCK QUEUE TESTS
# ==============================================================================

def test_queue_worker_executes_task_immediately_when_unlocked(workbook_copy, filled_data):
    mock_client = MagicMock()
    worker = queue_worker.LockQueueWorker(client=mock_client)
    worker.start()

    success_results = []
    task = queue_worker.WriteTask(
        task_type="append",
        channel="C123",
        thread_ts="12345.678",
        user_id="U123",
        action_fn=lambda: log_writer.append_row(log_writer.build_row(filled_data, "Isaac"), workbook_path=workbook_copy),
        success_callback=lambda res: success_results.append(res),
        description="Test Append",
    )

    worker.submit(task)

    # Wait for completion
    timeout = time.time() + 5.0
    while time.time() < timeout and not success_results:
        time.sleep(0.05)

    worker.stop(timeout=2.0)

    assert len(success_results) == 1
    assert success_results[0] == 17
    # Since it was unlocked, no lock warning message was sent
    mock_client.chat_postMessage.assert_not_called()


def test_queue_worker_retries_when_locked_and_completes_when_released(workbook_copy, filled_data):
    mock_client = MagicMock()
    worker = queue_worker.LockQueueWorker(client=mock_client)

    # Create lock file ~$Purchasing-Log.xlsx
    lock_file = os.path.join(os.path.dirname(workbook_copy), "~$Purchasing-Log.xlsx")
    open(lock_file, "w").close()

    success_results = []
    task = queue_worker.WriteTask(
        task_type="append",
        channel="C123",
        thread_ts="12345.678",
        user_id="U123",
        action_fn=lambda: log_writer.append_row(log_writer.build_row(filled_data, "Isaac"), workbook_path=workbook_copy),
        success_callback=lambda res: success_results.append(res),
        description="Locked Append Test",
    )

    # Speed up poll interval for testing
    orig_interval = config.EXCEL_QUEUE_POLL_INTERVAL
    config.EXCEL_QUEUE_POLL_INTERVAL = 0.1

    try:
        worker.start()
        worker.submit(task)

        # Allow worker to attempt write and detect lock
        time.sleep(0.3)

        # Worker should have notified thread that file is locked
        mock_client.chat_postMessage.assert_called()
        first_call = mock_client.chat_postMessage.call_args_list[0]
        assert "currently open in Excel" in first_call[1]["text"]
        assert first_call[1]["channel"] == "C123"

        # Check queue status reports locked
        status = worker.get_status()
        assert status["pending_count"] == 1
        assert status["is_locked"] is True

        # Now remove lock file to simulate user closing Excel
        os.remove(lock_file)

        # Wait for task to succeed
        timeout = time.time() + 5.0
        while time.time() < timeout and not success_results:
            time.sleep(0.05)

        worker.stop(timeout=2.0)

        assert len(success_results) == 1
        assert success_results[0] == 17

        # Worker should also have notified thread that update was applied
        release_calls = [
            c for c in mock_client.chat_postMessage.call_args_list
            if "released and your request has been logged" in c[1]["text"]
        ]
        assert len(release_calls) >= 1
        assert "Row `#17`" in release_calls[0][1]["text"]

    finally:
        config.EXCEL_QUEUE_POLL_INTERVAL = orig_interval
        if os.path.exists(lock_file):
            os.remove(lock_file)


def test_queue_worker_maintains_fifo_order(workbook_copy, filled_data):
    mock_client = MagicMock()
    worker = queue_worker.LockQueueWorker(client=mock_client)
    worker.start()

    results = []

    def make_task(name, idx):
        return queue_worker.WriteTask(
            task_type="append",
            channel="C123",
            user_id="U123",
            action_fn=lambda: log_writer.append_row(log_writer.build_row(filled_data, name), workbook_path=workbook_copy),
            success_callback=lambda res: results.append((idx, name, res)),
            description=f"Task {idx}",
        )

    worker.submit(make_task("Isaac", 1))
    worker.submit(make_task("Dylan", 2))
    worker.submit(make_task("Smeet", 3))

    timeout = time.time() + 5.0
    while time.time() < timeout and len(results) < 3:
        time.sleep(0.05)

    worker.stop(timeout=2.0)

    assert len(results) == 3
    assert [r[0] for r in results] == [1, 2, 3]
    assert [r[1] for r in results] == ["Isaac", "Dylan", "Smeet"]
    assert results[0][2] == 17
    assert results[1][2] == 18
    assert results[2][2] == 19


def test_queue_worker_calls_failure_callback_on_non_lock_error():
    mock_client = MagicMock()
    worker = queue_worker.LockQueueWorker(client=mock_client)
    worker.start()

    errors = []

    def bad_action():
        raise ValueError("Invalid spreadsheet structure")

    task = queue_worker.WriteTask(
        action_fn=bad_action,
        failure_callback=lambda exc: errors.append(exc),
        description="Bad Task",
    )

    worker.submit(task)

    timeout = time.time() + 5.0
    while time.time() < timeout and not errors:
        time.sleep(0.05)

    worker.stop(timeout=2.0)

    assert len(errors) == 1
    assert isinstance(errors[0], ValueError)
    assert "Invalid spreadsheet" in str(errors[0])


# ==============================================================================
# 2. ADMIN, HEALTH & DIAGNOSTICS TESTS
# ==============================================================================

def test_admin_user_authorization():
    config.ADMIN_SLACK_USER_IDS = ["UADMIN1", "UADMIN2"]
    assert admin.is_admin_user("UADMIN1") is True
    assert admin.is_admin_user("UADMIN2") is True
    assert admin.is_admin_user("UUSER99") is False
    assert admin.is_admin_user(None) is False
    assert admin.is_admin_user("") is False


def test_format_uptime():
    past = datetime.now().replace(hour=max(0, datetime.now().hour - 2), minute=max(0, datetime.now().minute - 15))
    uptime = admin.format_uptime(past)
    assert "minute" in uptime


def test_get_system_health_and_build_blocks(tmp_path):
    health = admin.get_system_health()
    assert "host" in health
    assert "os" in health
    assert "uptime" in health
    assert "disk" in health
    assert "memory" in health
    assert "workbook" in health
    assert "queue" in health

    blocks = admin.build_health_blocks(health)
    assert isinstance(blocks, list)
    assert len(blocks) >= 4
    # Check that header block is present
    assert blocks[0]["text"]["text"] == "🩺 P-Bot System Health & Status"


def test_get_tail_logs_and_token_masking(tmp_path):
    log_file = tmp_path / "test_p_bot.log"
    content = (
        "[2026-09-08 10:00:00] [INFO] Starting bot with token xoxb-1234567890-abcdef\n"
        "[2026-09-08 10:00:01] [INFO] App token xapp-987654321-ghijkl\n"
        "[2026-09-08 10:00:02] [INFO] Webhook https://hooks.slack.com/services/T00/B00/X00\n"
        "[2026-09-08 10:00:03] [INFO] Normal log line 1\n"
        "[2026-09-08 10:00:04] [INFO] Normal log line 2\n"
    )
    log_file.write_text(content, encoding="utf-8")

    # Read last 2 lines
    tail2 = admin.get_tail_logs(n=2, log_path=str(log_file))
    assert "Normal log line 1" in tail2
    assert "Normal log line 2" in tail2
    assert "Starting bot" not in tail2

    # Read all lines and verify masking
    tail_all = admin.get_tail_logs(n=10, log_path=str(log_file))
    assert "xoxb-***MASKED***" in tail_all
    assert "xapp-***MASKED***" in tail_all
    assert "https://hooks.slack.com/services/***MASKED***" in tail_all
    assert "xoxb-1234567890-abcdef" not in tail_all
    assert "xapp-987654321-ghijkl" not in tail_all


# ==============================================================================
# 3. HEARTBEAT & ALERTING TESTS
# ==============================================================================

def test_heartbeat_monitor_ping():
    with patch("requests.get") as mock_get:
        mock_get.return_value.status_code = 200
        monitor = heartbeat.HeartbeatMonitor(url="https://hc-ping.com/fake-id", interval=60)
        assert monitor.ping() is True
        mock_get.assert_called_once_with("https://hc-ping.com/fake-id", timeout=15)


def test_send_startup_alert():
    mock_client = MagicMock()
    config.ADMIN_ALERT_CHANNEL = "C_ADMIN_ALERT"
    assert heartbeat.send_startup_alert(mock_client) is True
    mock_client.chat_postMessage.assert_called_once()
    call_args = mock_client.chat_postMessage.call_args[1]
    assert call_args["channel"] == "C_ADMIN_ALERT"
    assert "P-Bot Online" in call_args["text"]


def test_send_crash_alert():
    mock_client = MagicMock()
    config.ADMIN_ALERT_CHANNEL = "C_ADMIN_ALERT"
    assert heartbeat.send_crash_alert(mock_client, "Division by zero", "Traceback (most recent call last)...") is True
    mock_client.chat_postMessage.assert_called_once()
    call_args = mock_client.chat_postMessage.call_args[1]
    assert call_args["channel"] == "C_ADMIN_ALERT"
    assert "Critical Error / Crash Alert" in call_args["text"]
    assert "Division by zero" in call_args["text"]


# ==============================================================================
# 4. SLACK BOT COMMAND DISPATCHER & ADMIN GUARD TESTS
# ==============================================================================

def test_dispatch_health_status_command():
    mock_client = MagicMock()
    mock_say = MagicMock()
    app.dispatch_command(
        client=mock_client,
        say=mock_say,
        channel="C123",
        thread_ts="111.222",
        user="U123",
        event_ts="111.222",
        text="@p-bot health",
    )
    mock_say.assert_called_once()
    call_kwargs = mock_say.call_args[1]
    assert "Health" in call_kwargs["text"]
    assert "blocks" in call_kwargs


def test_dispatch_queue_status_command():
    mock_client = MagicMock()
    mock_say = MagicMock()
    app.dispatch_command(
        client=mock_client,
        say=mock_say,
        channel="C123",
        thread_ts="111.222",
        user="U123",
        event_ts="111.222",
        text="@p-bot queue",
    )
    mock_say.assert_called_once()
    call_kwargs = mock_say.call_args[1]
    assert "Excel Write Queue" in call_kwargs["text"]


def test_dispatch_logs_restricted_to_admins():
    mock_client = MagicMock()
    mock_say = MagicMock()
    config.ADMIN_SLACK_USER_IDS = ["U_ADMIN"]

    # Non-admin call
    app.dispatch_command(
        client=mock_client,
        say=mock_say,
        channel="C123",
        thread_ts="111.222",
        user="U_REGULAR_USER",
        event_ts="111.222",
        text="@p-bot logs 20",
    )
    mock_say.assert_called_once_with(
        text="🔒 This command is restricted to bot administrators.",
        thread_ts="111.222",
    )

    # Admin call
    mock_say.reset_mock()
    app.dispatch_command(
        client=mock_client,
        say=mock_say,
        channel="C123",
        thread_ts="111.222",
        user="U_ADMIN",
        event_ts="111.222",
        text="@p-bot logs 20",
    )
    mock_say.assert_called_once()
    assert "Recent Bot Logs" in mock_say.call_args[1]["text"]


def test_dispatch_update_restricted_to_admins():
    mock_client = MagicMock()
    mock_say = MagicMock()
    config.ADMIN_SLACK_USER_IDS = ["U_ADMIN"]

    # Non-admin call
    app.dispatch_command(
        client=mock_client,
        say=mock_say,
        channel="C123",
        thread_ts="111.222",
        user="U_REGULAR_USER",
        event_ts="111.222",
        text="@p-bot update",
    )
    mock_say.assert_called_once_with(
        text="🔒 This command is restricted to bot administrators.",
        thread_ts="111.222",
    )


def test_dispatch_restart_restricted_to_admins():
    mock_client = MagicMock()
    mock_say = MagicMock()
    config.ADMIN_SLACK_USER_IDS = ["U_ADMIN"]

    # Non-admin call
    app.dispatch_command(
        client=mock_client,
        say=mock_say,
        channel="C123",
        thread_ts="111.222",
        user="U_REGULAR_USER",
        event_ts="111.222",
        text="@p-bot restart",
    )
    mock_say.assert_called_once_with(
        text="🔒 This command is restricted to bot administrators.",
        thread_ts="111.222",
    )
