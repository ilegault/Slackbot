"""Tests for Ticket 146: /purchasing-help carries the Log link.

Acceptance criteria:
- get_help_message() includes the clickable Log link right after the bot title and before _INTERFACE_RULE
- Missing or malformed PURCHASING_LOG_URL shows the not-set sentence and no '<http'
- Help and App Home share _LOG_LINK_LABEL and _LOG_LINK_NOT_SET
- A malformed setting logs one WARNING naming PURCHASING_LOG_URL; an empty one logs none
- build_dm_help_blocks() carries the Log link intact across chunk_mrkdwn packing
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

from src import blocks, config  # noqa: E402


def _welcome_section(view: dict) -> dict:
    assert view["blocks"][0]["type"] == "header"
    section = view["blocks"][1]
    assert section["type"] == "section"
    return section


def test_help_links_the_log(monkeypatch):
    monkeypatch.setattr(config, "PURCHASING_LOG_URL", "https://example.org/log?e=1")
    text = blocks.get_help_message()
    expected_line = "*Purchasing Log:* <https://example.org/log?e=1|Open Purchasing Log>"
    assert expected_line in text
    title_idx = text.index("🤖 *Hirst Lab Purchasing Bot*")
    link_idx = text.index(expected_line)
    rule_idx = text.index(blocks._INTERFACE_RULE)
    assert title_idx < link_idx < rule_idx


@pytest.mark.parametrize("raw", [
    "",
    "www.example.com/log",
    "C:\\Users\\x\\Purchasing-Log.xlsx",
    "https://exa mple.com",
])
def test_help_not_set_shows_the_sentence(monkeypatch, raw):
    monkeypatch.setattr(config, "PURCHASING_LOG_URL", raw)
    text = blocks.get_help_message()
    assert "*Purchasing Log:* The Purchasing Log link isn't set up yet. Ask an admin." in text
    assert "<http" not in text


def test_help_and_app_home_share_the_log_link_strings(monkeypatch):
    monkeypatch.setattr(config, "PURCHASING_LOG_URL", "https://example.org/log")
    help_text = blocks.get_help_message()
    home_welcome = _welcome_section(blocks.build_app_home_view("U_TEST"))
    assert blocks._LOG_LINK_LABEL in help_text
    assert blocks._LOG_LINK_LABEL == home_welcome["accessory"]["text"]["text"]

    monkeypatch.setattr(config, "PURCHASING_LOG_URL", "")
    help_text_unset = blocks.get_help_message()
    home_welcome_unset = _welcome_section(blocks.build_app_home_view("U_TEST"))
    assert blocks._LOG_LINK_NOT_SET in help_text_unset
    assert blocks._LOG_LINK_NOT_SET in home_welcome_unset["text"]["text"]


def test_help_malformed_setting_warns(monkeypatch, caplog):
    monkeypatch.setattr(config, "PURCHASING_LOG_URL", "www.example.com/log")
    with caplog.at_level("WARNING"):
        blocks.get_help_message()
    hits = [r for r in caplog.records if r.levelname == "WARNING" and "PURCHASING_LOG_URL" in r.getMessage()]
    assert len(hits) == 1

    caplog.clear()
    monkeypatch.setattr(config, "PURCHASING_LOG_URL", "")
    with caplog.at_level("WARNING"):
        blocks.get_help_message()
    assert not [r for r in caplog.records if r.levelname == "WARNING" and "PURCHASING_LOG_URL" in r.getMessage()]


def test_dm_help_blocks_carry_the_log_link(monkeypatch):
    monkeypatch.setattr(config, "PURCHASING_LOG_URL", "https://example.org/log")
    dm_blocks = blocks.build_dm_help_blocks()
    section_text = "\n".join(
        blk["text"]["text"]
        for blk in dm_blocks
        if blk.get("type") == "section" and isinstance(blk.get("text"), dict)
    )
    assert "|Open Purchasing Log>" in section_text
