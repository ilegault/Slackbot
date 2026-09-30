"""Tests for Ticket 58: Slack text says 'the Purchasing bot' and '@Purchasing'.

Covers:
- Scanned surfaces (help message, App Home, health blocks, startup alert, crash alert,
  unknown-word reply, blank-template guide text) contain no 'p-bot' (case-insensitive),
  and health header & startup alert contain 'Purchasing bot'.
- AST walk of all string constants in src/ ensures no string literal contains '@p-bot'.
- FAQ entries for @purchasing and @p-bot return identical answers containing @Purchasing
  and not @p-bot.
- config.LOG_FILE still ends with 'p_bot.log'.
"""

import ast
import json
from pathlib import Path
from unittest.mock import MagicMock

from src import admin, blocks, config, heartbeat, interview, ops, text_rules


def test_scanned_surfaces_contain_no_p_bot_and_have_purchasing_bot(monkeypatch, tmp_path):
    """Real builders produce text without 'p-bot' and with 'Purchasing bot' in headers."""
    # 1. Help message
    help_text = blocks.get_help_message()
    assert "p-bot" not in help_text.lower(), f"p-bot found in help_text: {help_text}"

    # 2. App Home view
    app_home = json.dumps(blocks.build_app_home_view("U_TEST"))
    assert "p-bot" not in app_home.lower(), f"p-bot found in app_home: {app_home}"

    # 3. Health blocks
    health = admin.get_system_health()
    health_blocks = admin.build_health_blocks(health)
    health_str = json.dumps(health_blocks)
    assert "p-bot" not in health_str.lower(), f"p-bot found in health blocks: {health_str}"
    assert "Purchasing bot" in health_blocks[0]["text"]["text"]

    # 4. Startup alert (clean)
    wb = tmp_path / "Purchasing-Log.xlsx"
    wb.write_text("dummy", encoding="utf-8")
    for attr, folder in [
        ("EPIFS_DIR", "EPIFs"),
        ("CONFIRMATIONS_DIR", "Confs"),
        ("QUOTES_DIR", "Quotes"),
        ("BOMS_DIR", "BOMs"),
    ]:
        p = tmp_path / folder
        p.mkdir()
        monkeypatch.setattr(config, attr, str(p))
    tmpl = tmp_path / "template.pdf"
    tmpl.write_text("pdf", encoding="utf-8")
    monkeypatch.setattr(config, "WORKBOOK_PATH", str(wb))
    monkeypatch.setattr(config, "EPIF_TEMPLATE_PATH", str(tmpl))
    monkeypatch.setattr(config, "ADMIN_ALERT_CHANNEL", "C_ALERT")

    mock_client = MagicMock()
    heartbeat.send_startup_alert(mock_client)
    clean_call = mock_client.chat_postMessage.call_args[1]
    clean_str = json.dumps(clean_call)
    assert "p-bot" not in clean_str.lower(), f"p-bot found in clean startup alert: {clean_str}"
    assert "Purchasing bot" in clean_call["blocks"][0]["text"]["text"]
    assert "Purchasing bot" in clean_call["text"]

    # 5. Startup alert (with a problem)
    missing_dir = str(tmp_path / "nonexistent")
    monkeypatch.setattr(config, "QUOTES_DIR", missing_dir)
    mock_client.reset_mock()
    heartbeat.send_startup_alert(mock_client)
    prob_call = mock_client.chat_postMessage.call_args[1]
    prob_str = json.dumps(prob_call)
    assert "p-bot" not in prob_str.lower(), f"p-bot found in problem startup alert: {prob_str}"
    assert "Purchasing bot" in prob_call["blocks"][0]["text"]["text"]
    assert "Purchasing bot" in prob_call["text"]

    # 6. Crash alert text
    mock_client.reset_mock()
    heartbeat.send_crash_alert(mock_client, "Division by zero", "Traceback...")
    crash_call = mock_client.chat_postMessage.call_args[1]
    crash_str = json.dumps(crash_call)
    assert "p-bot" not in crash_str.lower(), f"p-bot found in crash alert: {crash_str}"

    # 7. Unknown-word reply
    reply1 = text_rules.format_unknown_keyword_message("foobar", None)
    assert "p-bot" not in reply1.lower()
    reply2 = text_rules.format_unknown_keyword_message("updat", "update")
    assert "p-bot" not in reply2.lower()

    # 8. /blank-template guide text
    say = MagicMock()
    client = MagicMock()
    ops.handle_template_command(client, say, channel="C123", thread_ts="T123", user_id="U123")
    guide_calls = [
        call[1]["text"]
        for call in say.call_args_list
        if "Hirst Lab Manual EPIF Submission Kit" in call[1].get("text", "")
    ]
    assert len(guide_calls) == 1
    assert "p-bot" not in guide_calls[0].lower(), f"p-bot found in guide text: {guide_calls[0]}"


def test_every_at_example_in_src_says_at_purchasing():
    """No string constant in any src/*.py file contains '@p-bot'."""
    src_dir = Path(__file__).resolve().parent.parent / "src"
    py_files = list(src_dir.rglob("*.py"))
    assert len(py_files) > 0, "No python files found in src/"

    violations = []
    for py_file in py_files:
        content = py_file.read_text(encoding="utf-8")
        tree = ast.parse(content, filename=str(py_file))
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                if "@p-bot" in node.value:
                    violations.append(f"{py_file.name}:{node.lineno}: {node.value!r}")

    assert not violations, "Found '@p-bot' in string literals:\n" + "\n".join(violations)


def test_faq_purchasing_and_p_bot_aliases():
    """FAQ answers for @purchasing and @p-bot match and say @Purchasing, not @p-bot."""
    ans_purchasing = interview.match_faq("what does @purchasing do?")
    ans_pbot = interview.match_faq("what does @p-bot do?")

    assert ans_purchasing is not None, "FAQ should match 'what does @purchasing do?'"
    assert ans_pbot is not None, "FAQ should match 'what does @p-bot do?'"
    assert ans_purchasing == ans_pbot, "Both questions should return the same answer"
    assert "@Purchasing" in ans_purchasing
    assert "@p-bot" not in ans_purchasing
    assert "p-bot" not in ans_purchasing.lower()


def test_log_file_ends_with_p_bot_log():
    """config.LOG_FILE is unchanged and ends with p_bot.log."""
    assert config.LOG_FILE.endswith("p_bot.log")
