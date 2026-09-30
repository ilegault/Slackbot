"""Tests for ticket 56: A missing storage location is reported, never recreated.

Binding: docs/adr/0009-keywords-storage-settings-and-the-bot-name.md decision 6, ADR 0001
Spec: .scratch/commands-paths-and-name/spec.md
"""
import os
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from src import config, lifecycle, log_writer, ops, slack_io, text_rules

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SAMPLES = os.path.join(PROJECT_ROOT, "samples")
SAMPLE_WORKBOOK = os.path.join(SAMPLES, "Purchasing-Log.xlsx")


def test_save_functions_never_recreate_missing_folder_and_save_when_existing(tmp_path, monkeypatch):
    """Save functions raise StorageLocationError on missing folders and never recreate them."""
    # 1. save_epif
    missing_epifs = tmp_path / "epifs_missing"
    monkeypatch.setattr(config, "EPIFS_DIR", str(missing_epifs))
    with pytest.raises(log_writer.StorageLocationError) as exc_info:
        log_writer.save_epif(b"%PDF-1.4 dummy epif", "test_epif.pdf")
    assert exc_info.value.setting == "EPIFS_DIR"
    assert exc_info.value.reason == "does not exist"
    assert exc_info.value.path == str(missing_epifs)
    assert not missing_epifs.exists()

    existing_epifs = tmp_path / "epifs_existing"
    existing_epifs.mkdir()
    monkeypatch.setattr(config, "EPIFS_DIR", str(existing_epifs))
    saved_epif = log_writer.save_epif(b"%PDF-1.4 dummy epif", "test_epif.pdf")
    assert Path(saved_epif).read_bytes() == b"%PDF-1.4 dummy epif"

    # 2. save_confirmation
    missing_conf = tmp_path / "conf_missing"
    monkeypatch.setattr(config, "CONFIRMATIONS_DIR", str(missing_conf))
    with pytest.raises(log_writer.StorageLocationError) as exc_info:
        log_writer.save_confirmation(b"confirmation dummy", "test_conf.pdf")
    assert exc_info.value.setting == "CONFIRMATIONS_DIR"
    assert exc_info.value.reason == "does not exist"
    assert exc_info.value.path == str(missing_conf)
    assert not missing_conf.exists()

    existing_conf = tmp_path / "conf_existing"
    existing_conf.mkdir()
    monkeypatch.setattr(config, "CONFIRMATIONS_DIR", str(existing_conf))
    saved_conf = log_writer.save_confirmation(b"confirmation dummy", "test_conf.pdf")
    assert Path(saved_conf).read_bytes() == b"confirmation dummy"

    # 3. save_quote
    missing_quotes = tmp_path / "quotes_missing"
    monkeypatch.setattr(config, "QUOTES_DIR", str(missing_quotes))
    with pytest.raises(log_writer.StorageLocationError) as exc_info:
        log_writer.save_quote(b"quote dummy", "test_quote.pdf")
    assert exc_info.value.setting == "QUOTES_DIR"
    assert exc_info.value.reason == "does not exist"
    assert exc_info.value.path == str(missing_quotes)
    assert not missing_quotes.exists()

    existing_quotes = tmp_path / "quotes_existing"
    existing_quotes.mkdir()
    monkeypatch.setattr(config, "QUOTES_DIR", str(existing_quotes))
    saved_quote = log_writer.save_quote(b"quote dummy", "test_quote.pdf")
    assert Path(saved_quote).read_bytes() == b"quote dummy"

    # 4. save_bom
    missing_boms = tmp_path / "boms_missing"
    monkeypatch.setattr(config, "BOMS_DIR", str(missing_boms))
    with pytest.raises(log_writer.StorageLocationError) as exc_info:
        log_writer.save_bom(b"bom dummy", "test_bom.xlsx")
    assert exc_info.value.setting == "BOMS_DIR"
    assert exc_info.value.reason == "does not exist"
    assert exc_info.value.path == str(missing_boms)
    assert not missing_boms.exists()

    existing_boms = tmp_path / "boms_existing"
    existing_boms.mkdir()
    monkeypatch.setattr(config, "BOMS_DIR", str(existing_boms))
    saved_bom = log_writer.save_bom(b"bom dummy", "test_bom.xlsx")
    assert Path(saved_bom).read_bytes() == b"bom dummy"


def test_save_functions_unset_setting_raises_not_set(monkeypatch):
    """Save functions raise StorageLocationError with reason 'not set' when setting is empty."""
    monkeypatch.setattr(config, "EPIFS_DIR", "")
    with pytest.raises(log_writer.StorageLocationError) as exc_info:
        log_writer.save_epif(b"content", "test.pdf")
    assert exc_info.value.setting == "EPIFS_DIR"
    assert exc_info.value.reason == "not set"

    monkeypatch.setattr(config, "CONFIRMATIONS_DIR", "")
    with pytest.raises(log_writer.StorageLocationError) as exc_info:
        log_writer.save_confirmation(b"content", "test.pdf")
    assert exc_info.value.setting == "CONFIRMATIONS_DIR"
    assert exc_info.value.reason == "not set"

    monkeypatch.setattr(config, "QUOTES_DIR", "")
    with pytest.raises(log_writer.StorageLocationError) as exc_info:
        log_writer.save_quote(b"content", "test.pdf")
    assert exc_info.value.setting == "QUOTES_DIR"
    assert exc_info.value.reason == "not set"

    monkeypatch.setattr(config, "BOMS_DIR", "")
    with pytest.raises(log_writer.StorageLocationError) as exc_info:
        log_writer.save_bom(b"content", "test.xlsx")
    assert exc_info.value.setting == "BOMS_DIR"
    assert exc_info.value.reason == "not set"


def test_workbook_functions_raise_storage_location_error(tmp_path, monkeypatch):
    """Workbook functions raise StorageLocationError with PURCHASING_LOG_PATH when empty or missing."""
    monkeypatch.setattr(config, "WORKBOOK_PATH", "")
    with pytest.raises(log_writer.StorageLocationError) as exc_info:
        log_writer.append_row({"B": "Test"})
    assert exc_info.value.setting == "PURCHASING_LOG_PATH"
    assert exc_info.value.reason == "not set"

    with pytest.raises(log_writer.StorageLocationError) as exc_info:
        log_writer.update_row(12, {"B": "Test"})
    assert exc_info.value.setting == "PURCHASING_LOG_PATH"
    assert exc_info.value.reason == "not set"

    with pytest.raises(log_writer.StorageLocationError) as exc_info:
        log_writer.blank_row(12)
    assert exc_info.value.setting == "PURCHASING_LOG_PATH"
    assert exc_info.value.reason == "not set"

    with pytest.raises(log_writer.StorageLocationError) as exc_info:
        log_writer.get_row_info(12)
    assert exc_info.value.setting == "PURCHASING_LOG_PATH"
    assert exc_info.value.reason == "not set"

    missing_wb = str(tmp_path / "missing_log.xlsx")
    monkeypatch.setattr(config, "WORKBOOK_PATH", missing_wb)
    with pytest.raises(log_writer.StorageLocationError) as exc_info:
        log_writer.append_row({"B": "Test"})
    assert exc_info.value.setting == "PURCHASING_LOG_PATH"
    assert exc_info.value.reason == "does not exist"
    assert exc_info.value.path == missing_wb


def test_storage_problem_message_pure_and_exact():
    """storage_problem_message is pure, exact, and formats according to spec."""
    msg_unset = text_rules.storage_problem_message("QUOTES_DIR", "", "not set")
    assert "QUOTES_DIR" in msg_unset
    assert "not set" in msg_unset
    assert "An admin needs to fix the server's .env." in msg_unset
    assert msg_unset == "⚠️ I can't reach a storage location. *QUOTES_DIR* not set: `not set`. An admin needs to fix the server's .env."

    msg_missing = text_rules.storage_problem_message("QUOTES_DIR", "/some/missing/path", "does not exist")
    assert msg_missing == "⚠️ I can't reach a storage location. *QUOTES_DIR* does not exist: `/some/missing/path`. An admin needs to fix the server's .env."


def test_quote_with_missing_folder(tmp_path, monkeypatch):
    """lifecycle.handle_quote with missing folder replies once in thread and does not recreate folder."""
    monkeypatch.setattr(slack_io, "download_file", lambda f: b"%PDF-1.4 dummy quote")
    say = MagicMock()
    client = MagicMock()

    missing_quotes = tmp_path / "missing_quotes_dir"
    monkeypatch.setattr(config, "QUOTES_DIR", str(missing_quotes))

    lifecycle.handle_quote(
        client=client,
        say=say,
        channel="C_PURCHASING",
        thread_ts="123456.78",
        event_ts="123456.79",
        files=[{"name": "Quote.pdf", "id": "F123"}],
    )

    assert say.call_count == 1
    say_text = say.call_args[1]["text"]
    assert "QUOTES_DIR" in say_text
    assert str(missing_quotes) in say_text
    assert say.call_args[1]["thread_ts"] == "123456.78"
    client.reactions_add.assert_not_called()
    assert not missing_quotes.exists()


def test_confirmation_with_missing_folder(tmp_path, monkeypatch):
    """lifecycle.handle_confirmation with missing folder replies with storage problem message."""
    from tests.test_11_roster_sync import create_fixture_workbook

    temp_wb = tmp_path / "Purchasing-Log.xlsx"
    create_fixture_workbook(str(temp_wb))
    monkeypatch.setattr(config, "WORKBOOK_PATH", str(temp_wb))

    missing_conf = tmp_path / "missing_conf_dir"
    monkeypatch.setattr(config, "CONFIRMATIONS_DIR", str(missing_conf))

    monkeypatch.setattr(slack_io, "download_file", lambda f: b"%PDF-1.4 dummy confirmation")

    def sync_submit_write_task(action_fn, channel, thread_ts, user_id, task_type, description, success_callback, failure_callback, client=None):
        try:
            res = action_fn()
            success_callback(res)
        except Exception as e:
            failure_callback(e)

    monkeypatch.setattr(lifecycle.queue_worker, "submit_write_task", sync_submit_write_task)

    say = MagicMock()
    client = MagicMock()

    lifecycle.handle_confirmation(
        client=client,
        say=say,
        channel="C_PURCHASING",
        thread_ts="123456.78",
        user_id="U_BUYER",
        event_ts="123456.79",
        text="Row 12",
        files=[{"name": "Confirmation.pdf", "id": "F456"}],
    )

    assert say.call_count == 1
    say_text = say.call_args[1]["text"]
    assert "CONFIRMATIONS_DIR" in say_text
    assert str(missing_conf) in say_text
    assert say.call_args[1]["thread_ts"] == "123456.78"
    client.reactions_add.assert_not_called()
    assert not missing_conf.exists()


def test_blank_template_uses_storage_problem_message(tmp_path, monkeypatch):
    """ops.handle_template_command uses text_rules.storage_problem_message for missing or unset template."""
    say = MagicMock()
    client = MagicMock()

    missing_path = str(tmp_path / "missing_template.pdf")
    monkeypatch.setattr(config, "EPIF_TEMPLATE_PATH", missing_path)

    ops.handle_template_command(client, say, channel="C123", thread_ts="ts1", user_id="U123")
    assert say.call_count == 1
    expected = text_rules.storage_problem_message("EPIF_TEMPLATE_PATH", missing_path, "does not exist")
    assert say.call_args[1]["text"] == expected

    say.reset_mock()
    monkeypatch.setattr(config, "EPIF_TEMPLATE_PATH", "")
    ops.handle_template_command(client, say, channel="C123", thread_ts="ts1", user_id="U123")
    assert say.call_count == 1
    expected_unset = text_rules.storage_problem_message("EPIF_TEMPLATE_PATH", "", "not set")
    assert say.call_args[1]["text"] == expected_unset
