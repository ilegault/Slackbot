"""Tests for ticket 147: The health screen shows whether the Log link is set, and SETUP.md documents it.

WHY THIS EXISTS:
----------------
Ticket 147 / ADR 0021 Decisions 2-4:
`@Purchasing health` shows one line (`Log link: set` or `Log link: not set`) outside the
storage section using `text_rules.log_link_url` without ever exposing the URL itself, and
`docs/SETUP.md` documents `PURCHASING_LOG_URL` as an optional browser link rather than a
storage path.
"""
import os
import sys

import pytest

_CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(_CURRENT_DIR) if os.path.basename(_CURRENT_DIR) == "tests" else _CURRENT_DIR
SRC_DIR = os.path.join(PROJECT_ROOT, "src")
for p in (PROJECT_ROOT, SRC_DIR):
    if p not in sys.path:
        sys.path.insert(0, p)

from src import admin, config  # noqa: E402


def _point_storage_at_tmp(tmp_path, monkeypatch) -> None:
    """Point all six storage settings at temp paths, mirroring test_55_health_paths."""
    wb_file = tmp_path / "Purchasing-Log.xlsx"
    wb_file.write_text("dummy", encoding="utf-8")
    epifs_dir = tmp_path / "EPIFs"
    epifs_dir.mkdir()
    conf_dir = tmp_path / "Order-Confirmations"
    conf_dir.mkdir()
    quotes_dir = tmp_path / "Quotes"
    quotes_dir.mkdir()
    boms_dir = tmp_path / "BOMs"
    boms_dir.mkdir()
    template_file = tmp_path / "EPIF_TEMPLATE.pdf"
    template_file.write_text("dummy", encoding="utf-8")

    monkeypatch.setattr(config, "WORKBOOK_PATH", str(wb_file))
    monkeypatch.setattr(config, "EPIFS_DIR", str(epifs_dir))
    monkeypatch.setattr(config, "CONFIRMATIONS_DIR", str(conf_dir))
    monkeypatch.setattr(config, "QUOTES_DIR", str(quotes_dir))
    monkeypatch.setattr(config, "BOMS_DIR", str(boms_dir))
    monkeypatch.setattr(config, "EPIF_TEMPLATE_PATH", str(template_file))


def _section_texts(blocks: list[dict]) -> list[str]:
    """Return the mrkdwn/plain text of every section block."""
    texts = []
    for b in blocks:
        if b.get("type") == "section" and "text" in b and "text" in b["text"]:
            texts.append(b["text"]["text"])
    return texts


def test_health_says_log_link_set(tmp_path, monkeypatch):
    """With a valid PURCHASING_LOG_URL, health shows 'Log link: set' and never the URL."""
    _point_storage_at_tmp(tmp_path, monkeypatch)
    monkeypatch.setattr(config, "PURCHASING_LOG_URL", "https://example.org/log?e=1")

    blocks = admin.build_health_blocks(admin.get_system_health())
    combined = "\n".join(_section_texts(blocks))

    assert "Log link: set" in combined
    assert "Log link: not set" not in combined
    assert "example.org" not in str(blocks)


@pytest.mark.parametrize("raw_url", ["", "www.example.com/log", "https://exa mple.com"])
def test_health_says_log_link_not_set(tmp_path, monkeypatch, raw_url):
    """Empty or malformed PURCHASING_LOG_URL renders as 'Log link: not set'."""
    _point_storage_at_tmp(tmp_path, monkeypatch)
    monkeypatch.setattr(config, "PURCHASING_LOG_URL", raw_url)

    blocks = admin.build_health_blocks(admin.get_system_health())
    combined = "\n".join(_section_texts(blocks))

    assert "Log link: not set" in combined


def test_log_link_line_sits_outside_storage(tmp_path, monkeypatch):
    """The Log link block sits outside the storage section and storage still lists all six settings."""
    _point_storage_at_tmp(tmp_path, monkeypatch)
    monkeypatch.setattr(config, "PURCHASING_LOG_URL", "https://example.org/log?e=1")

    blocks = admin.build_health_blocks(admin.get_system_health())
    texts = _section_texts(blocks)

    log_link_blocks = [t for t in texts if t == "Log link: set"]
    assert len(log_link_blocks) == 1

    storage_setting_names = [setting for setting, _, _ in config.STORAGE_SETTINGS]
    for t in log_link_blocks:
        assert "Storage & OneDrive Directory Health" not in t
        for name in storage_setting_names:
            assert name not in t

    storage_blocks = [
        t for t in texts
        if "Storage & OneDrive Directory Health" in t
        or any(name in t for name in storage_setting_names)
    ]
    storage_combined = "\n".join(storage_blocks)
    for name in storage_setting_names:
        assert name in storage_combined
    assert "PURCHASING_LOG_URL" not in storage_combined


def test_hand_built_health_dict_still_renders():
    """Hand-built health dicts without log_link_set still render with 'Log link: not set'."""
    h = {
        "host": "test-host",
        "os": "Windows 11",
        "uptime": "1 minute",
        "disk": "C:\\ - 10.0 GB free",
        "memory": "50.0 MB",
        "bot_version": "1.0.0",
        "storage": [],
        "queue": {"pending_count": 0},
    }
    blocks = admin.build_health_blocks(h)
    combined = "\n".join(_section_texts(blocks))

    assert "Log link: not set" in combined


def test_setup_documents_purchasing_log_url():
    """docs/SETUP.md documents PURCHASING_LOG_URL as an optional browser link, keeping all 5 storage rows."""
    setup_path = os.path.join(os.getcwd(), "docs", "SETUP.md")
    with open(setup_path, "r", encoding="utf-8") as f:
        text = f.read()

    assert "PURCHASING_LOG_URL=https://" in text
    assert "### Purchasing Log link (optional)" in text

    url_rows = [line for line in text.splitlines() if line.startswith("| **PURCHASING_LOG_URL** |")]
    assert len(url_rows) == 1
    assert "Not a storage path" in url_rows[0]

    for setting in (
        "PURCHASING_LOG_PATH",
        "EPIFS_DIR",
        "CONFIRMATIONS_DIR",
        "QUOTES_DIR",
        "BOMS_DIR",
    ):
        assert setting in text
