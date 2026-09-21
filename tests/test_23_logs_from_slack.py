"""Tests for ticket 23: Full logs from Slack, in the alert channel only.

WHY THIS EXISTS:
----------------
Covers all requirements from .scratch/logs-and-startup-paths/spec.md Part A:
- One channel rule for every logs form (admin check -> ADMIN_ALERT_CHANNEL configured -> message in alert channel).
- Form chosen by word after logs/log: nothing (30 lines), number n (n lines, >=1, no cap),
  'all' (whole p_bot.log), 'rejections' (whole rejections.log), anything else (unknown option).
- Tail delivery: inline when <= 2,800 chars, uploaded as file when > 2,800 chars.
- Whole file uploads via files_upload_v2 with masked text and descriptive comments.
- Token and webhook URL masking through a single masking function.
- Error handling: missing file, read errors, upload errors.
- Drives app.dispatch_command with real files in tmp_path, asserting on Slack calls.
"""
from unittest.mock import MagicMock

from src import app, config


def _setup_env(tmp_path, monkeypatch, admin_id="U_ADMIN", alert_channel="C_ALERT"):
    """Helper to configure config with test admin, channel, and temp log files."""
    log_file = tmp_path / "p_bot.log"
    rejections_file = tmp_path / "rejections.log"
    monkeypatch.setattr(config, "ADMIN_SLACK_USER_IDS", [admin_id])
    monkeypatch.setattr(config, "ADMIN_ALERT_CHANNEL", alert_channel)
    monkeypatch.setattr(config, "LOG_FILE", str(log_file))
    monkeypatch.setattr(config, "REJECTIONS_LOG_FILE", str(rejections_file))
    return log_file, rejections_file


def test_logs_tail_over_2800_chars_uploads_file(tmp_path, monkeypatch):
    log_file, _ = _setup_env(tmp_path, monkeypatch)
    lines = [f"2026-09-21 12:00:{i:02d} [INFO] Routine log line {i} with lots of context details\n" for i in range(500)]
    log_file.write_text("".join(lines), encoding="utf-8")

    mock_client = MagicMock()
    mock_say = MagicMock()

    app.dispatch_command(
        client=mock_client,
        say=mock_say,
        channel="C_ALERT",
        thread_ts="123.456",
        user="U_ADMIN",
        event_ts="123.456",
        text="@Purchasing logs 500",
    )

    # Must NOT post inline
    mock_say.assert_not_called()

    # Must upload as file in thread
    mock_client.files_upload_v2.assert_called_once()
    upload_kwargs = mock_client.files_upload_v2.call_args[1]
    assert upload_kwargs["channel"] == "C_ALERT"
    assert upload_kwargs["thread_ts"] == "123.456"
    assert upload_kwargs["filename"] == "p_bot_last_500_lines.log"
    assert upload_kwargs["title"] == "p_bot_last_500_lines.log"
    assert upload_kwargs["initial_comment"] == "📋 Last 500 lines of p_bot.log (too long to post inline)."

    content_lines = upload_kwargs["content"].splitlines()
    assert len(content_lines) == 500
    assert content_lines[-1] == lines[-1].strip()


def test_logs_tail_short_posts_inline(tmp_path, monkeypatch):
    log_file, _ = _setup_env(tmp_path, monkeypatch)
    lines = [f"Line {i}\n" for i in range(1, 6)]
    log_file.write_text("".join(lines), encoding="utf-8")

    mock_client = MagicMock()
    mock_say = MagicMock()

    app.dispatch_command(
        client=mock_client,
        say=mock_say,
        channel="C_ALERT",
        thread_ts="123.456",
        user="U_ADMIN",
        event_ts="123.456",
        text="@Purchasing logs 3",
    )

    mock_client.files_upload_v2.assert_not_called()
    mock_say.assert_called_once()
    reply = mock_say.call_args[1]["text"]
    assert "📋 *Recent Bot Logs (Last 3 lines):*" in reply
    assert "Line 3\nLine 4\nLine 5" in reply
    assert "Line 1" not in reply
    assert "Line 2" not in reply


def test_logs_tail_fewer_lines_than_requested(tmp_path, monkeypatch):
    log_file, _ = _setup_env(tmp_path, monkeypatch)
    lines = [f"Line {i}\n" for i in range(1, 11)]
    log_file.write_text("".join(lines), encoding="utf-8")

    mock_client = MagicMock()
    mock_say = MagicMock()

    app.dispatch_command(
        client=mock_client,
        say=mock_say,
        channel="C_ALERT",
        thread_ts="123.456",
        user="U_ADMIN",
        event_ts="123.456",
        text="@Purchasing logs 50",
    )

    mock_client.files_upload_v2.assert_not_called()
    mock_say.assert_called_once()
    reply = mock_say.call_args[1]["text"]
    assert "📋 *Recent Bot Logs (Last 10 lines):*" in reply


def test_logs_all_uploads_whole_file(tmp_path, monkeypatch):
    log_file, _ = _setup_env(tmp_path, monkeypatch)
    lines = [f"Log entry {i}\n" for i in range(25)]
    log_file.write_text("".join(lines), encoding="utf-8")

    mock_client = MagicMock()
    mock_say = MagicMock()

    app.dispatch_command(
        client=mock_client,
        say=mock_say,
        channel="C_ALERT",
        thread_ts="123.456",
        user="U_ADMIN",
        event_ts="123.456",
        text="@Purchasing logs all",
    )

    mock_say.assert_not_called()
    mock_client.files_upload_v2.assert_called_once()
    upload_kwargs = mock_client.files_upload_v2.call_args[1]
    assert upload_kwargs["channel"] == "C_ALERT"
    assert upload_kwargs["thread_ts"] == "123.456"
    assert upload_kwargs["filename"] == "p_bot.log"
    assert upload_kwargs["title"] == "p_bot.log"
    assert upload_kwargs["initial_comment"] == "📋 Full p_bot.log (25 lines)."
    assert upload_kwargs["content"] == "".join(lines)


def test_logs_rejections_uploads_rejections_file(tmp_path, monkeypatch):
    _, rejections_file = _setup_env(tmp_path, monkeypatch)
    lines = [f"Rejection record {i}\n" for i in range(12)]
    rejections_file.write_text("".join(lines), encoding="utf-8")

    mock_client = MagicMock()
    mock_say = MagicMock()

    app.dispatch_command(
        client=mock_client,
        say=mock_say,
        channel="C_ALERT",
        thread_ts="123.456",
        user="U_ADMIN",
        event_ts="123.456",
        text="@Purchasing logs rejections",
    )

    mock_say.assert_not_called()
    mock_client.files_upload_v2.assert_called_once()
    upload_kwargs = mock_client.files_upload_v2.call_args[1]
    assert upload_kwargs["channel"] == "C_ALERT"
    assert upload_kwargs["thread_ts"] == "123.456"
    assert upload_kwargs["filename"] == "rejections.log"
    assert upload_kwargs["title"] == "rejections.log"
    assert upload_kwargs["initial_comment"] == "📋 Full rejections.log (12 lines)."
    assert upload_kwargs["content"] == "".join(lines)


def test_logs_masking_tokens_and_urls(tmp_path, monkeypatch):
    log_file, _ = _setup_env(tmp_path, monkeypatch)
    content = (
        "Starting with xoxb-secret-token-12345678 and xapp-app-secret-98765432\n"
        "Sending webhook to https://hooks.slack.com/services/T00/B00/X00123\n"
    )
    # Add enough lines so it triggers file upload
    padding = [f"Line {i} padding to exceed inline character limit for logs upload test\n" for i in range(100)]
    log_file.write_text(content + "".join(padding), encoding="utf-8")

    mock_client = MagicMock()
    mock_say = MagicMock()

    app.dispatch_command(
        client=mock_client,
        say=mock_say,
        channel="C_ALERT",
        thread_ts="123.456",
        user="U_ADMIN",
        event_ts="123.456",
        text="@Purchasing logs all",
    )

    mock_client.files_upload_v2.assert_called_once()
    uploaded_text = mock_client.files_upload_v2.call_args[1]["content"]

    assert "xoxb-***MASKED***" in uploaded_text
    assert "xapp-***MASKED***" in uploaded_text
    assert "https://hooks.slack.com/services/***MASKED***" in uploaded_text
    assert "xoxb-secret-token-12345678" not in uploaded_text
    assert "xapp-app-secret-98765432" not in uploaded_text
    assert "https://hooks.slack.com/services/T00/B00/X00123" not in uploaded_text


def test_logs_in_wrong_channel_refused(tmp_path, monkeypatch):
    log_file, _ = _setup_env(tmp_path, monkeypatch)
    log_file.write_text("secret log info\n", encoding="utf-8")

    mock_client = MagicMock()
    mock_say = MagicMock()

    app.dispatch_command(
        client=mock_client,
        say=mock_say,
        channel="C_GENERAL",  # not C_ALERT
        thread_ts="123.456",
        user="U_ADMIN",
        event_ts="123.456",
        text="@Purchasing logs 20",
    )

    mock_client.files_upload_v2.assert_not_called()
    mock_say.assert_called_once_with(
        text="🔒 Logs are only available in <#C_ALERT>.",
        thread_ts="123.456",
    )


def test_logs_non_admin_refused(tmp_path, monkeypatch):
    log_file, _ = _setup_env(tmp_path, monkeypatch)
    log_file.write_text("secret log info\n", encoding="utf-8")

    mock_client = MagicMock()
    mock_say = MagicMock()

    app.dispatch_command(
        client=mock_client,
        say=mock_say,
        channel="C_ALERT",
        thread_ts="123.456",
        user="U_NON_ADMIN",
        event_ts="123.456",
        text="@Purchasing logs",
    )

    mock_client.files_upload_v2.assert_not_called()
    mock_say.assert_called_once_with(
        text="🔒 This command is restricted to bot administrators.",
        thread_ts="123.456",
    )


def test_logs_alert_channel_not_set(tmp_path, monkeypatch):
    log_file, _ = _setup_env(tmp_path, monkeypatch, alert_channel="")
    log_file.write_text("secret log info\n", encoding="utf-8")

    mock_client = MagicMock()
    mock_say = MagicMock()

    app.dispatch_command(
        client=mock_client,
        say=mock_say,
        channel="C_ALERT",
        thread_ts="123.456",
        user="U_ADMIN",
        event_ts="123.456",
        text="@Purchasing logs",
    )

    mock_client.files_upload_v2.assert_not_called()
    mock_say.assert_called_once_with(
        text="⚠️ Logs are unavailable: ADMIN_ALERT_CHANNEL is not set in the bot's .env.",
        thread_ts="123.456",
    )


def test_logs_unknown_option(tmp_path, monkeypatch):
    _setup_env(tmp_path, monkeypatch)

    mock_client = MagicMock()
    mock_say = MagicMock()

    app.dispatch_command(
        client=mock_client,
        say=mock_say,
        channel="C_ALERT",
        thread_ts="123.456",
        user="U_ADMIN",
        event_ts="123.456",
        text="@Purchasing logs banana",
    )

    mock_client.files_upload_v2.assert_not_called()
    mock_say.assert_called_once_with(
        text="Unknown logs option. Use `logs [n]`, `logs all`, or `logs rejections`.",
        thread_ts="123.456",
    )


def test_logs_missing_file(tmp_path, monkeypatch):
    log_file = tmp_path / "nonexistent.log"
    monkeypatch.setattr(config, "ADMIN_SLACK_USER_IDS", ["U_ADMIN"])
    monkeypatch.setattr(config, "ADMIN_ALERT_CHANNEL", "C_ALERT")
    monkeypatch.setattr(config, "LOG_FILE", str(log_file))
    monkeypatch.setattr(config, "REJECTIONS_LOG_FILE", str(tmp_path / "missing_rejections.log"))

    mock_client = MagicMock()
    mock_say = MagicMock()

    # Form 1: tail
    app.dispatch_command(
        client=mock_client,
        say=mock_say,
        channel="C_ALERT",
        thread_ts="123.456",
        user="U_ADMIN",
        event_ts="123.456",
        text="@Purchasing logs 30",
    )
    mock_client.files_upload_v2.assert_not_called()
    mock_say.assert_called_once_with(
        text=f"Log file not found at `{log_file}`.",
        thread_ts="123.456",
    )

    # Form 2: all
    mock_say.reset_mock()
    app.dispatch_command(
        client=mock_client,
        say=mock_say,
        channel="C_ALERT",
        thread_ts="123.456",
        user="U_ADMIN",
        event_ts="123.456",
        text="@Purchasing logs all",
    )
    mock_client.files_upload_v2.assert_not_called()
    mock_say.assert_called_once_with(
        text=f"Log file not found at `{log_file}`.",
        thread_ts="123.456",
    )

    # Form 3: rejections
    mock_say.reset_mock()
    app.dispatch_command(
        client=mock_client,
        say=mock_say,
        channel="C_ALERT",
        thread_ts="123.456",
        user="U_ADMIN",
        event_ts="123.456",
        text="@Purchasing logs rejections",
    )
    mock_client.files_upload_v2.assert_not_called()
    mock_say.assert_called_once_with(
        text=f"Log file not found at `{tmp_path / 'missing_rejections.log'}`.",
        thread_ts="123.456",
    )


def test_logs_upload_exception(tmp_path, monkeypatch):
    log_file, _ = _setup_env(tmp_path, monkeypatch)
    lines = [f"Line {i} padding to exceed character limit for inline upload\n" for i in range(200)]
    log_file.write_text("".join(lines), encoding="utf-8")

    mock_client = MagicMock()
    mock_client.files_upload_v2.side_effect = Exception("network timeout")
    mock_say = MagicMock()

    app.dispatch_command(
        client=mock_client,
        say=mock_say,
        channel="C_ALERT",
        thread_ts="123.456",
        user="U_ADMIN",
        event_ts="123.456",
        text="@Purchasing logs 200",
    )

    mock_client.files_upload_v2.assert_called_once()
    mock_say.assert_called_once_with(
        text="⚠️ Could not upload p_bot_last_200_lines.log: network timeout",
        thread_ts="123.456",
    )


def test_logs_upload_missing_scope_names_the_fix(tmp_path, monkeypatch):
    """A missing files:write scope tells the admin exactly which Slack setting to fix."""
    log_file, _ = _setup_env(tmp_path, monkeypatch)
    log_file.write_text("one line\n", encoding="utf-8")

    mock_client = MagicMock()
    mock_client.files_upload_v2.side_effect = Exception(
        "The request to the Slack API failed. (url: https://slack.com/api/files.getUploadURLExternal)\n"
        "The server responded with: {'ok': False, 'error': 'missing_scope', 'needed': 'files:write'}"
    )
    mock_say = MagicMock()

    app.dispatch_command(
        client=mock_client,
        say=mock_say,
        channel="C_ALERT",
        thread_ts="123.456",
        user="U_ADMIN",
        event_ts="123.456",
        text="@Purchasing logs all",
    )

    mock_say.assert_called_once()
    text = mock_say.call_args.kwargs["text"]
    assert "p_bot.log" in text
    assert "`files:write`" in text
    assert "reinstall" in text
    assert "OAuth & Permissions" in text
    assert "getUploadURLExternal" not in text, "raw API dump should be replaced by the plain fix"


def test_logs_default_30_and_boundary_numbers(tmp_path, monkeypatch):
    log_file, _ = _setup_env(tmp_path, monkeypatch)
    lines = [f"Entry {i}\n" for i in range(1, 50)]
    log_file.write_text("".join(lines), encoding="utf-8")

    mock_client = MagicMock()
    mock_say = MagicMock()

    # Default without number -> 30 lines
    app.dispatch_command(
        client=mock_client,
        say=mock_say,
        channel="C_ALERT",
        thread_ts="123.456",
        user="U_ADMIN",
        event_ts="123.456",
        text="@Purchasing logs",
    )
    assert "Last 30 lines" in mock_say.call_args[1]["text"]

    # Number 0 -> becomes 1
    mock_say.reset_mock()
    app.dispatch_command(
        client=mock_client,
        say=mock_say,
        channel="C_ALERT",
        thread_ts="123.456",
        user="U_ADMIN",
        event_ts="123.456",
        text="@Purchasing logs 0",
    )
    assert "Last 1 lines" in mock_say.call_args[1]["text"]

    # Negative number -> becomes 1
    mock_say.reset_mock()
    app.dispatch_command(
        client=mock_client,
        say=mock_say,
        channel="C_ALERT",
        thread_ts="123.456",
        user="U_ADMIN",
        event_ts="123.456",
        text="@Purchasing logs -10",
    )
    assert "Last 1 lines" in mock_say.call_args[1]["text"]


def test_logs_case_insensitive_forms_and_log_alias(tmp_path, monkeypatch):
    log_file, rejections_file = _setup_env(tmp_path, monkeypatch)
    log_file.write_text("main log entry\n", encoding="utf-8")
    rejections_file.write_text("rejection entry\n", encoding="utf-8")

    mock_client = MagicMock()
    mock_say = MagicMock()

    # 'log' singular alias
    app.dispatch_command(
        client=mock_client,
        say=mock_say,
        channel="C_ALERT",
        thread_ts="123.456",
        user="U_ADMIN",
        event_ts="123.456",
        text="@Purchasing log 1",
    )
    assert "Last 1 lines" in mock_say.call_args[1]["text"]

    # Case insensitive ALL
    app.dispatch_command(
        client=mock_client,
        say=mock_say,
        channel="C_ALERT",
        thread_ts="123.456",
        user="U_ADMIN",
        event_ts="123.456",
        text="@Purchasing logs ALL",
    )
    assert mock_client.files_upload_v2.call_args[1]["filename"] == "p_bot.log"

    # Case insensitive Rejections
    app.dispatch_command(
        client=mock_client,
        say=mock_say,
        channel="C_ALERT",
        thread_ts="123.456",
        user="U_ADMIN",
        event_ts="123.456",
        text="@Purchasing logs Rejections",
    )
    assert mock_client.files_upload_v2.call_args[1]["filename"] == "rejections.log"
