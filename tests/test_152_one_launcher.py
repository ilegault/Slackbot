"""Tests for Ticket 152: the autostart script installs one launcher and removes the old ones.

Acceptance criteria:
- `setup_autostart.main()` installs no Startup-folder shortcut and no PowerShell CreateShortcut.
- `setup_autostart.main()` removes `P-Bot.lnk` and `EPIF-Bot.lnk` while leaving other files intact.
- `setup_autostart.main()` registers `Purchasing-Bot` and unregisters `P-Bot`.
- `docs/SETUP.md` describes one launcher (`Purchasing-Bot`) and the refusal alert, without
  mentioning a startup shortcut or backup startup folder.
"""

import os
import sys
from pathlib import Path
from types import SimpleNamespace

_CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = (
    os.path.dirname(_CURRENT_DIR)
    if os.path.basename(_CURRENT_DIR) == "tests"
    else _CURRENT_DIR
)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from scripts import setup_autostart  # noqa: E402


def _fake_autostart(monkeypatch, tmp_path: Path):
    """Fake subprocess.run, startup_dir, and BOT_DIR under tmp_path."""
    startup = tmp_path / "Startup"
    startup.mkdir(parents=True, exist_ok=True)
    bot_dir = tmp_path / "BotDir"
    bot_dir.mkdir(parents=True, exist_ok=True)

    calls: list[list[str]] = []

    def fake_run(cmd, *args, **kwargs):
        calls.append(list(cmd))
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(setup_autostart.subprocess, "run", fake_run)
    monkeypatch.setattr(setup_autostart, "startup_dir", lambda: str(startup))
    monkeypatch.setattr(setup_autostart, "BOT_DIR", str(bot_dir))
    return startup, calls


def _ps_scripts(calls: list[list[str]]) -> list[str]:
    """Extract the -Command PowerShell script strings from recorded subprocess calls."""
    scripts = []
    for cmd in calls:
        if "-Command" in cmd:
            idx = cmd.index("-Command")
            if idx + 1 < len(cmd):
                scripts.append(cmd[idx + 1])
    return scripts


def test_autostart_installs_no_startup_shortcut(monkeypatch, tmp_path):
    """On an empty startup folder, main() leaves no P-Bot.lnk and runs no CreateShortcut."""
    startup, calls = _fake_autostart(monkeypatch, tmp_path)

    setup_autostart.main()

    assert not (startup / "P-Bot.lnk").exists()
    for script in _ps_scripts(calls):
        assert "CreateShortcut" not in script


def test_autostart_removes_old_shortcuts(monkeypatch, tmp_path):
    """main() removes P-Bot.lnk and EPIF-Bot.lnk while leaving Other.lnk intact."""
    startup, _calls = _fake_autostart(monkeypatch, tmp_path)
    (startup / "P-Bot.lnk").write_text("", encoding="utf-8")
    (startup / "EPIF-Bot.lnk").write_text("", encoding="utf-8")
    (startup / "Other.lnk").write_text("", encoding="utf-8")

    setup_autostart.main()

    assert not (startup / "P-Bot.lnk").exists()
    assert not (startup / "EPIF-Bot.lnk").exists()
    assert (startup / "Other.lnk").exists()


def test_autostart_registers_purchasing_bot_and_drops_p_bot(monkeypatch, tmp_path):
    """Recorded PowerShell registers Purchasing-Bot and unregisters P-Bot."""
    _startup, calls = _fake_autostart(monkeypatch, tmp_path)

    setup_autostart.main()

    scripts = _ps_scripts(calls)
    assert scripts, "Expected at least one PowerShell -Command call"
    combined = "\n".join(scripts)
    assert '$taskName = "Purchasing-Bot"' in combined
    assert "Register-ScheduledTask" in combined
    assert 'Unregister-ScheduledTask -TaskName "P-Bot"' in combined


def test_setup_md_describes_one_launcher_and_the_refusal():
    """docs/SETUP.md describes Purchasing-Bot and the refusal alert, with no startup shortcut."""
    setup_md = Path(PROJECT_ROOT) / "docs" / "SETUP.md"
    content = setup_md.read_text(encoding="utf-8")

    assert "Purchasing-Bot" in content
    assert "A second Purchasing bot tried to start" in content
    lower = content.lower()
    assert "startup shortcut" not in lower
    assert "backup startup folder" not in lower
