"""Tests for ticket 55: The health screen shows all six storage paths.

WHY THIS EXISTS:
----------------
Ticket 55 / ADR 0009 Decision 5:
Previously admin.get_system_health / admin.build_health_blocks checked only four
locations, omitted BOMS_DIR and EPIF_TEMPLATE_PATH, showed no paths, and kept a hard-coded
list separate from config.STORAGE_SETTINGS. Now the health screen reads config.STORAGE_SETTINGS
in order, reports per-setting status and full paths, and formats unset paths cleanly as "not set".
"""
import os
import sys

# Ensure src is on sys.path
_CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(_CURRENT_DIR) if os.path.basename(_CURRENT_DIR) == "tests" else _CURRENT_DIR
SRC_DIR = os.path.join(PROJECT_ROOT, "src")
for p in (PROJECT_ROOT, SRC_DIR):
    if p not in sys.path:
        sys.path.insert(0, p)

from src import admin, config  # noqa: E402


def _extract_all_section_text(blocks: list[dict]) -> str:
    """Helper to concatenate all mrkdwn text from section blocks."""
    texts = []
    for b in blocks:
        if b.get("type") == "section" and "text" in b and "text" in b["text"]:
            texts.append(b["text"]["text"])
    return "\n".join(texts)


def test_all_six_from_one_list(tmp_path, monkeypatch):
    """Point five settings at real temp paths and leave BOMS_DIR empty.

    Assert:
    - All six setting names appear
    - Both of two chosen real temp paths appear verbatim
    - The BOMS_DIR line says 'Not set' and 'not set'
    """
    wb_file = tmp_path / "Purchasing-Log.xlsx"
    wb_file.write_text("dummy", encoding="utf-8")
    epifs_dir = tmp_path / "EPIFs"
    epifs_dir.mkdir()
    conf_dir = tmp_path / "Order-Confirmations"
    conf_dir.mkdir()
    quotes_dir = tmp_path / "Quotes"
    quotes_dir.mkdir()
    template_file = tmp_path / "EPIF_TEMPLATE.pdf"
    template_file.write_text("dummy", encoding="utf-8")

    monkeypatch.setattr(config, "WORKBOOK_PATH", str(wb_file))
    monkeypatch.setattr(config, "EPIFS_DIR", str(epifs_dir))
    monkeypatch.setattr(config, "CONFIRMATIONS_DIR", str(conf_dir))
    monkeypatch.setattr(config, "QUOTES_DIR", str(quotes_dir))
    monkeypatch.setattr(config, "BOMS_DIR", "")
    monkeypatch.setattr(config, "EPIF_TEMPLATE_PATH", str(template_file))

    health = admin.get_system_health()
    blocks = admin.build_health_blocks(health)
    combined_text = _extract_all_section_text(blocks)

    # 1. All six setting names appear
    for setting, _, _ in config.STORAGE_SETTINGS:
        assert setting in combined_text, f"Setting name {setting} not found in health blocks"

    # 2. Both of two chosen real temp paths appear verbatim
    assert str(wb_file) in combined_text
    assert str(epifs_dir) in combined_text

    # 3. BOMS_DIR line says 'Not set' and 'not set'
    # Find the line or section for BOMS_DIR
    boms_line = None
    for line in combined_text.splitlines():
        if "BOMS_DIR" in line:
            boms_line = line
            break
    assert boms_line is not None, "BOMS_DIR line not found"
    assert "Not set" in boms_line
    assert "not set" in boms_line


def test_driven_by_list(tmp_path, monkeypatch):
    """Monkeypatch config.STORAGE_SETTINGS to add a seventh entry; assert it appears in blocks."""
    custom_dir = tmp_path / "CustomArchive"
    custom_dir.mkdir()

    extended_settings = config.STORAGE_SETTINGS + (
        ("EXTRA_ARCHIVE_DIR", "EXTRA_ARCHIVE_DIR", "folder"),
    )
    monkeypatch.setattr(config, "STORAGE_SETTINGS", extended_settings)
    monkeypatch.setattr(config, "EXTRA_ARCHIVE_DIR", str(custom_dir), raising=False)

    health = admin.get_system_health()
    blocks = admin.build_health_blocks(health)
    combined_text = _extract_all_section_text(blocks)

    assert "EXTRA_ARCHIVE_DIR" in combined_text
    assert str(custom_dir) in combined_text


def test_missing_path_shows_as_missing_with_path(tmp_path, monkeypatch):
    """Point QUOTES_DIR at a non-existent temp path: its line contains Missing and that path."""
    non_existent = str(tmp_path / "does_not_exist_quotes_dir")
    monkeypatch.setattr(config, "QUOTES_DIR", non_existent)

    health = admin.get_system_health()
    blocks = admin.build_health_blocks(health)
    combined_text = _extract_all_section_text(blocks)

    quotes_lines = []
    found = False
    for line in combined_text.splitlines():
        if "QUOTES_DIR" in line:
            found = True
            quotes_lines.append(line)
        elif found and (line.startswith("• *") or line.startswith("*")):
            break
        elif found:
            quotes_lines.append(line)

    quotes_block_text = "\n".join(quotes_lines)
    assert "Missing" in quotes_block_text
    assert non_existent in quotes_block_text


def test_long_paths_fit(monkeypatch):
    """Six settings each set to a 300-character path: every section block's text is <= 3000 chars and all 6 paths appear."""
    long_paths = {}
    for idx, (setting, attr, _) in enumerate(config.STORAGE_SETTINGS):
        # Construct path of exactly 300 characters
        # e.g. "C:\\" + 288 'a's + "\\f{idx}"
        base = f"C:\\dir{idx}\\"
        padding = "x" * (300 - len(base) - 5)
        path = f"{base}{padding}\\file"
        assert len(path) == 300, f"Expected 300 chars, got {len(path)}"
        long_paths[setting] = path
        monkeypatch.setattr(config, attr, path)

    health = admin.get_system_health()
    blocks = admin.build_health_blocks(health)

    # Every section block's text must be <= 3 000 characters
    section_texts = []
    for b in blocks:
        if b.get("type") == "section" and "text" in b and "text" in b["text"]:
            text = b["text"]["text"]
            assert len(text) <= 3000, f"Section block text exceeded 3000 chars ({len(text)} chars)"
            section_texts.append(text)

    combined = "\n".join(section_texts)
    # All six paths still appear
    for setting, path in long_paths.items():
        assert path in combined, f"Path for {setting} did not appear in blocks"
