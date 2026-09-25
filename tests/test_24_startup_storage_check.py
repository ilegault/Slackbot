"""Tests for Ticket 24: Startup alert names bad storage paths.

Covers:
- Pure check in path_validator (check_storage_paths)
- send_startup_alert reporting bad paths with orange header and problem details
- Fallback text and block structure
- ERROR logging before early return when alert channel or client is missing
"""
import logging
from unittest.mock import MagicMock

import pytest

from src import config, heartbeat, path_validator


@pytest.fixture
def valid_storage(tmp_path):
    """Create real files and directories for a clean storage setup."""
    wb = tmp_path / "Purchasing-Log.xlsx"
    wb.write_text("dummy workbook", encoding="utf-8")

    epifs = tmp_path / "EPIFs"
    epifs.mkdir()

    confirmations = tmp_path / "Order-Confirmations"
    confirmations.mkdir()

    quotes = tmp_path / "Quotes"
    quotes.mkdir()

    boms = tmp_path / "BOMs"
    boms.mkdir()

    epif_template = tmp_path / "EPIF_TEMPLATE.pdf"
    epif_template.write_text("PDF", encoding="utf-8")

    return {
        "WORKBOOK_PATH": str(wb),
        "EPIFS_DIR": str(epifs),
        "CONFIRMATIONS_DIR": str(confirmations),
        "QUOTES_DIR": str(quotes),
        "BOMS_DIR": str(boms),
        "EPIF_TEMPLATE_PATH": str(epif_template),
    }


def test_check_storage_paths_all_valid(monkeypatch, valid_storage):
    """When all storage paths exist and are the right kind, no problems are returned."""
    for attr, val in valid_storage.items():
        monkeypatch.setattr(config, attr, val)

    problems = path_validator.check_storage_paths()
    assert problems == []


def test_check_storage_paths_order_and_reasons(monkeypatch, tmp_path, valid_storage):
    """Check that settings are evaluated in the specified order and reasons follow precedence."""
    for attr, val in valid_storage.items():
        monkeypatch.setattr(config, attr, val)

    # 1. PURCHASING_LOG_PATH: not set
    # 2. EPIFS_DIR: placeholder
    # 3. CONFIRMATIONS_DIR: exists but is not a folder (it is a file)
    # 4. QUOTES_DIR: does not exist
    bad_conf_file = tmp_path / "conf_file.txt"
    bad_conf_file.write_text("not a dir", encoding="utf-8")

    monkeypatch.setattr(config, "WORKBOOK_PATH", "")
    monkeypatch.setattr(config, "EPIFS_DIR", r"C:\Users\USERNAME\OneDrive\EPIFs")
    monkeypatch.setattr(config, "CONFIRMATIONS_DIR", str(bad_conf_file))
    monkeypatch.setattr(config, "QUOTES_DIR", str(tmp_path / "missing_quotes_dir"))

    problems = path_validator.check_storage_paths()
    assert len(problems) == 4

    assert problems[0][0] == "PURCHASING_LOG_PATH"
    assert problems[0][2] == "not set"

    assert problems[1][0] == "EPIFS_DIR"
    assert problems[1][2] == "still contains a template placeholder"

    assert problems[2][0] == "CONFIRMATIONS_DIR"
    assert problems[2][2] == "exists but is not a folder"

    assert problems[3][0] == "QUOTES_DIR"
    assert problems[3][2] == "does not exist"


def test_check_storage_paths_placeholder_variations(monkeypatch, valid_storage):
    """Placeholder checks catch USERNAME component or < / > characters."""
    for attr, val in valid_storage.items():
        monkeypatch.setattr(config, attr, val)

    # USERNAME in component
    monkeypatch.setattr(config, "WORKBOOK_PATH", "/home/USERNAME/Purchasing-Log.xlsx")
    problems = path_validator.check_storage_paths()
    assert len(problems) == 1
    assert problems[0][0] == "PURCHASING_LOG_PATH"
    assert problems[0][2] == "still contains a template placeholder"

    # <your-windows-account> in component
    monkeypatch.setattr(config, "WORKBOOK_PATH", r"C:\Users\<your-windows-account>\Purchasing-Log.xlsx")
    problems = path_validator.check_storage_paths()
    assert len(problems) == 1
    assert problems[0][0] == "PURCHASING_LOG_PATH"
    assert problems[0][2] == "still contains a template placeholder"


def test_check_storage_paths_wrong_type_file_where_folder_expected(monkeypatch, tmp_path, valid_storage):
    """A directory pointing to a file reports 'exists but is not a folder'."""
    for attr, val in valid_storage.items():
        monkeypatch.setattr(config, attr, val)

    file_not_dir = tmp_path / "a_file.txt"
    file_not_dir.write_text("file", encoding="utf-8")
    monkeypatch.setattr(config, "EPIFS_DIR", str(file_not_dir))

    problems = path_validator.check_storage_paths()
    assert len(problems) == 1
    assert problems[0][0] == "EPIFS_DIR"
    assert problems[0][2] == "exists but is not a folder"


def test_check_storage_paths_wrong_type_folder_where_file_expected(monkeypatch, tmp_path, valid_storage):
    """A workbook path pointing to a directory reports 'exists but is not a file'."""
    for attr, val in valid_storage.items():
        monkeypatch.setattr(config, attr, val)

    dir_not_file = tmp_path / "a_dir"
    dir_not_file.mkdir()
    monkeypatch.setattr(config, "WORKBOOK_PATH", str(dir_not_file))

    problems = path_validator.check_storage_paths()
    assert len(problems) == 1
    assert problems[0][0] == "PURCHASING_LOG_PATH"
    assert problems[0][2] == "exists but is not a file"


def test_startup_alert_all_clean(monkeypatch, valid_storage):
    """When all paths are valid, the alert is unchanged with green header."""
    for attr, val in valid_storage.items():
        monkeypatch.setattr(config, attr, val)
    monkeypatch.setattr(config, "ADMIN_ALERT_CHANNEL", "C_ADMIN_ALERT")

    mock_client = MagicMock()
    result = heartbeat.send_startup_alert(mock_client)
    assert result is True

    mock_client.chat_postMessage.assert_called_once()
    call_kwargs = mock_client.chat_postMessage.call_args[1]

    assert call_kwargs["channel"] == "C_ADMIN_ALERT"
    blocks = call_kwargs["blocks"]
    assert blocks[0]["text"]["text"] == "🟢 P-Bot Online & Ready"
    assert not any("Storage path problems" in str(b) for b in blocks)
    assert "🟢 *P-Bot Online*" in call_kwargs["text"]
    assert "Storage path problems" not in call_kwargs["text"]


def test_startup_alert_with_placeholder(monkeypatch, valid_storage):
    """When a path has a placeholder, header is orange and problem section is added."""
    for attr, val in valid_storage.items():
        monkeypatch.setattr(config, attr, val)
    bad_path = r"C:\Users\USERNAME\Purchasing\Purchasing-Log.xlsx"
    monkeypatch.setattr(config, "WORKBOOK_PATH", bad_path)
    monkeypatch.setattr(config, "ADMIN_ALERT_CHANNEL", "C_ADMIN_ALERT")

    mock_client = MagicMock()
    result = heartbeat.send_startup_alert(mock_client)
    assert result is True

    call_kwargs = mock_client.chat_postMessage.call_args[1]
    blocks = call_kwargs["blocks"]

    # Header is orange
    assert blocks[0]["text"]["text"] == "🟠 P-Bot Online — storage paths need attention"

    # Problems section is directly after header-and-fields section (index 2)
    problems_block = blocks[2]
    assert problems_block["type"] == "section"
    assert "*Storage path problems:*" in problems_block["text"]["text"]
    assert f"• `PURCHASING_LOG_PATH` = `{bad_path}` — still contains a template placeholder" in problems_block["text"]["text"]
    assert "_Workbook writes and EPIF saves will fail until these are fixed in the server's .env and the bot is restarted._" in problems_block["text"]["text"]

    # Fallback text has orange header and the problems lines
    fallback_text = call_kwargs["text"]
    assert "🟠 *P-Bot Online — storage paths need attention*" in fallback_text
    assert "*Storage path problems:*" in fallback_text
    assert f"• `PURCHASING_LOG_PATH` = `{bad_path}` — still contains a template placeholder" in fallback_text
    assert "_Workbook writes and EPIF saves will fail until these are fixed in the server's .env and the bot is restarted._" in fallback_text


def test_startup_alert_missing_folder(monkeypatch, tmp_path, valid_storage):
    """One missing folder reports only that setting with 'does not exist'."""
    for attr, val in valid_storage.items():
        monkeypatch.setattr(config, attr, val)
    missing = str(tmp_path / "does_not_exist_epifs")
    monkeypatch.setattr(config, "EPIFS_DIR", missing)
    monkeypatch.setattr(config, "ADMIN_ALERT_CHANNEL", "C_ADMIN_ALERT")

    mock_client = MagicMock()
    heartbeat.send_startup_alert(mock_client)

    call_kwargs = mock_client.chat_postMessage.call_args[1]
    blocks = call_kwargs["blocks"]
    assert blocks[0]["text"]["text"] == "🟠 P-Bot Online — storage paths need attention"
    problems_block = blocks[2]
    assert f"• `EPIFS_DIR` = `{missing}` — does not exist" in problems_block["text"]["text"]
    assert "PURCHASING_LOG_PATH" not in problems_block["text"]["text"]


def test_startup_alert_workbook_is_folder(monkeypatch, tmp_path, valid_storage):
    """Workbook pointing at a folder reports 'exists but is not a file'."""
    for attr, val in valid_storage.items():
        monkeypatch.setattr(config, attr, val)
    folder_path = tmp_path / "workbook_as_dir"
    folder_path.mkdir()
    monkeypatch.setattr(config, "WORKBOOK_PATH", str(folder_path))
    monkeypatch.setattr(config, "ADMIN_ALERT_CHANNEL", "C_ADMIN_ALERT")

    mock_client = MagicMock()
    heartbeat.send_startup_alert(mock_client)

    call_kwargs = mock_client.chat_postMessage.call_args[1]
    blocks = call_kwargs["blocks"]
    problems_block = blocks[2]
    assert f"• `PURCHASING_LOG_PATH` = `{folder_path}` — exists but is not a file" in problems_block["text"]["text"]


def test_startup_alert_empty_setting(monkeypatch, valid_storage):
    """An empty setting reports 'not set'."""
    for attr, val in valid_storage.items():
        monkeypatch.setattr(config, attr, val)
    monkeypatch.setattr(config, "CONFIRMATIONS_DIR", "")
    monkeypatch.setattr(config, "ADMIN_ALERT_CHANNEL", "C_ADMIN_ALERT")

    mock_client = MagicMock()
    heartbeat.send_startup_alert(mock_client)

    call_kwargs = mock_client.chat_postMessage.call_args[1]
    blocks = call_kwargs["blocks"]
    problems_block = blocks[2]
    assert "• `CONFIRMATIONS_DIR` = `` — not set" in problems_block["text"]["text"]


def test_startup_alert_no_channel_logs_error_before_return(monkeypatch, valid_storage, caplog):
    """When ADMIN_ALERT_CHANNEL is empty and paths are bad, returns False, posts nothing, and logs ERROR."""
    for attr, val in valid_storage.items():
        monkeypatch.setattr(config, attr, val)
    monkeypatch.setattr(config, "ADMIN_ALERT_CHANNEL", "")
    bad_path = r"C:\Users\USERNAME\Purchasing\Purchasing-Log.xlsx"
    monkeypatch.setattr(config, "WORKBOOK_PATH", bad_path)

    mock_client = MagicMock()
    with caplog.at_level(logging.ERROR, logger="p-bot.heartbeat"):
        result = heartbeat.send_startup_alert(mock_client)

    assert result is False
    mock_client.chat_postMessage.assert_not_called()

    # Check error was logged with exact format
    expected_log = f"Storage path problem: PURCHASING_LOG_PATH = {bad_path!r} — still contains a template placeholder"
    assert any(expected_log in record.message for record in caplog.records)
