"""Tests for Ticket 54: One list of storage settings, no default paths, and /blank-template fixed.

Covers:
- No default paths for WORKBOOK_PATH, EPIFS_DIR, CONFIRMATIONS_DIR, QUOTES_DIR, BOMS_DIR, EPIF_TEMPLATE_PATH.
- TEMPLATE_DIR deleted. No IGLeg in any string attribute of config.
- STORAGE_SETTINGS drives check_storage_paths.
- Startup check and /blank-template agree.
- No TEMPLATE_DIR anywhere in src/.
"""
import importlib
import os
from unittest.mock import MagicMock

import pytest

from src import config, ops, path_validator


@pytest.fixture
def clean_config_env(monkeypatch):
    """Ensure storage env vars are absent and restore config on teardown."""
    env_keys = [
        "PURCHASING_LOG_PATH",
        "EPIFS_DIR",
        "CONFIRMATIONS_DIR",
        "QUOTES_DIR",
        "BOMS_DIR",
        "EPIF_TEMPLATE_PATH",
        "TEMPLATE_DIR",
    ]
    for k in env_keys:
        monkeypatch.delenv(k, raising=False)

    yield
    importlib.reload(config)


def test_no_default_paths_and_no_template_dir(clean_config_env, monkeypatch):
    """With none of the six settings in the environment, config attributes are empty strings,

    TEMPLATE_DIR does not exist on config, and no string attribute of config contains 'IGLeg'.
    """
    # Prevent reloading from reading candidates if any
    monkeypatch.setattr(config, "_env_candidates", [])
    importlib.reload(config)

    assert config.WORKBOOK_PATH == ""
    assert config.EPIFS_DIR == ""
    assert config.CONFIRMATIONS_DIR == ""
    assert config.QUOTES_DIR == ""
    assert config.BOMS_DIR == ""
    assert config.EPIF_TEMPLATE_PATH == ""
    assert not hasattr(config, "TEMPLATE_DIR")

    for attr_name in dir(config):
        if attr_name.startswith("_"):
            continue
        val = getattr(config, attr_name)
        if isinstance(val, str):
            # BASE_DIR and paths anchored to it (like LOG_FILE, LOADED_ENV_PATH) reflect the checkout path
            # on the local machine (e.g. C:\Users\IGLeg\...).
            if attr_name in ("BASE_DIR", "LOG_FILE", "REJECTIONS_LOG_FILE", "LOADED_ENV_PATH"):
                continue
            assert "IGLeg" not in val, f"config.{attr_name} contains 'IGLeg': {val}"


def test_storage_settings_drives_startup_check(monkeypatch, tmp_path):
    """Setting config.STORAGE_SETTINGS to include an extra entry is reported by check_storage_paths."""
    missing_file = str(tmp_path / "extra_file.txt")
    extra_settings = (
        ("PURCHASING_LOG_PATH", "WORKBOOK_PATH", "file"),
        ("EPIFS_DIR", "EPIFS_DIR", "folder"),
        ("CONFIRMATIONS_DIR", "CONFIRMATIONS_DIR", "folder"),
        ("QUOTES_DIR", "QUOTES_DIR", "folder"),
        ("BOMS_DIR", "BOMS_DIR", "folder"),
        ("EPIF_TEMPLATE_PATH", "EPIF_TEMPLATE_PATH", "file"),
        ("EXTRA_SETTING", "EXTRA_SETTING_ATTR", "file"),
    )
    monkeypatch.setattr(config, "STORAGE_SETTINGS", extra_settings, raising=False)
    monkeypatch.setattr(config, "EXTRA_SETTING_ATTR", missing_file, raising=False)

    # Make the normal ones valid so only extra fails
    valid_file = tmp_path / "valid.txt"
    valid_file.write_text("ok", encoding="utf-8")
    valid_dir = tmp_path / "valid_dir"
    valid_dir.mkdir()

    monkeypatch.setattr(config, "WORKBOOK_PATH", str(valid_file))
    monkeypatch.setattr(config, "EPIFS_DIR", str(valid_dir))
    monkeypatch.setattr(config, "CONFIRMATIONS_DIR", str(valid_dir))
    monkeypatch.setattr(config, "QUOTES_DIR", str(valid_dir))
    monkeypatch.setattr(config, "BOMS_DIR", str(valid_dir))
    monkeypatch.setattr(config, "EPIF_TEMPLATE_PATH", str(valid_file))

    problems = path_validator.check_storage_paths()
    reported_settings = [p.setting for p in problems]
    assert "EXTRA_SETTING" in reported_settings
    assert len(problems) == 1
    assert problems[0].setting == "EXTRA_SETTING"
    assert problems[0].reason == "does not exist"


def test_startup_and_blank_template_agree_missing_and_real(monkeypatch, tmp_path):
    """With EPIF_TEMPLATE_PATH pointing at a missing file, both check_storage_paths()

    and handle_template_command name EPIF_TEMPLATE_PATH; with it pointing at a real file,
    the first reports nothing for it and the second uploads it.
    """
    missing_path = str(tmp_path / "missing_epif_template.pdf")
    monkeypatch.setattr(config, "EPIF_TEMPLATE_PATH", missing_path)

    valid_file = tmp_path / "valid.xlsx"
    valid_file.write_text("ok", encoding="utf-8")
    valid_dir = tmp_path / "valid_dir"
    valid_dir.mkdir()

    monkeypatch.setattr(config, "WORKBOOK_PATH", str(valid_file))
    monkeypatch.setattr(config, "EPIFS_DIR", str(valid_dir))
    monkeypatch.setattr(config, "CONFIRMATIONS_DIR", str(valid_dir))
    monkeypatch.setattr(config, "QUOTES_DIR", str(valid_dir))
    monkeypatch.setattr(config, "BOMS_DIR", str(valid_dir))

    # 1. Missing path
    problems = path_validator.check_storage_paths()
    epif_problems = [p for p in problems if p.setting == "EPIF_TEMPLATE_PATH"]
    assert len(epif_problems) == 1
    assert epif_problems[0].reason == "does not exist"

    client = MagicMock()
    say = MagicMock()
    ops.handle_template_command(client, say, "C123", "ts", "U123")
    client.files_upload_v2.assert_not_called()
    assert say.call_count == 1
    reply_text = say.call_args[1]["text"]
    assert "EPIF_TEMPLATE_PATH" in reply_text
    assert missing_path in reply_text
    assert "An admin needs to fix the server's .env." in reply_text

    # 2. Real path
    real_pdf = tmp_path / "real_epif.pdf"
    real_pdf.write_bytes(b"%PDF-1.4 dummy real template")
    monkeypatch.setattr(config, "EPIF_TEMPLATE_PATH", str(real_pdf))

    problems = path_validator.check_storage_paths()
    epif_problems = [p for p in problems if p.setting == "EPIF_TEMPLATE_PATH"]
    assert len(epif_problems) == 0

    client.reset_mock()
    say.reset_mock()
    ops.handle_template_command(client, say, "C123", "ts", "U123")
    assert client.files_upload_v2.call_count == 1
    call_kwargs = client.files_upload_v2.call_args[1]
    assert call_kwargs["file"] == str(real_pdf)
    assert call_kwargs["filename"] == "EPIF_TEMPLATE_HIRST.pdf"


def test_no_template_dir_in_src():
    """Nothing in src/ references TEMPLATE_DIR."""
    src_dir = os.path.join(config.BASE_DIR, "src")
    found_occurrences = []
    for root, _, files in os.walk(src_dir):
        for f in files:
            if f.endswith(".py"):
                path = os.path.join(root, f)
                with open(path, "r", encoding="utf-8") as file_obj:
                    for line_no, line in enumerate(file_obj, 1):
                        if "TEMPLATE_DIR" in line:
                            found_occurrences.append(f"{path}:{line_no}: {line.strip()}")
    assert not found_occurrences, "Found TEMPLATE_DIR references in src:\n" + "\n".join(found_occurrences)
