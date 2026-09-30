"""Tests for Ticket 59: README and docs describe the current bot.

Acceptance criteria:
- README.md contains none of @p-bot, P-Bot, claim, submitted (case-insensitive, whole words).
- Every slash command registered with @app.command(...) in src/app.py appears in README.md.
- Every canonical admin keyword in config.ALL_KEYWORD_TUPLES marked (Admin Only) appears in README.md in hyphen form.
- No file under docs/ outside docs/adr/ contains @p-bot or P-Bot; docs/adr/ is untouched.
- p_bot.log and p_bot.spec are still named where docs describe build and logs.
"""

import ast
import re
import subprocess
from pathlib import Path

from src import blocks, config

REPO_ROOT = Path(__file__).resolve().parent.parent


def test_readme_contains_no_forbidden_words():
    """README.md contains none of @p-bot, P-Bot, claim, submitted (case-insensitive, whole words)."""
    readme_path = REPO_ROOT / "README.md"
    assert readme_path.exists(), "README.md does not exist"
    content = readme_path.read_text(encoding="utf-8")

    assert "@p-bot" not in content.lower(), "Found '@p-bot' in README.md"
    assert "p-bot" not in content.lower(), "Found 'p-bot' in README.md"

    # Whole-word check for 'claim' and 'submitted'
    claim_matches = re.findall(r"\bclaim\b", content, re.IGNORECASE)
    assert not claim_matches, f"Found whole-word 'claim' in README.md: {claim_matches}"

    submitted_matches = re.findall(r"\bsubmitted\b", content, re.IGNORECASE)
    assert not submitted_matches, f"Found whole-word 'submitted' in README.md: {submitted_matches}"


def test_every_slash_command_in_src_app_appears_in_readme():
    """Every slash command registered with @app.command(...) in src/app.py appears in README.md."""
    app_py_path = REPO_ROOT / "src" / "app.py"
    readme_path = REPO_ROOT / "README.md"
    content_app = app_py_path.read_text(encoding="utf-8")
    content_readme = readme_path.read_text(encoding="utf-8")

    tree = ast.parse(content_app, filename=str(app_py_path))
    slash_commands = []
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            for decorator in node.decorator_list:
                if (
                    isinstance(decorator, ast.Call)
                    and isinstance(decorator.func, ast.Attribute)
                    and decorator.func.attr == "command"
                    and decorator.args
                    and isinstance(decorator.args[0], ast.Constant)
                ):
                    slash_commands.append(decorator.args[0].value)

    assert slash_commands, "No slash commands found in src/app.py via AST"
    for cmd in slash_commands:
        assert cmd in content_readme, f"Slash command '{cmd}' missing from README.md"


def test_admin_keywords_appear_in_readme_in_hyphen_form():
    """Every canonical admin keyword in config.ALL_KEYWORD_TUPLES that the help text marks (Admin Only) appears in README.md in hyphen form."""
    readme_path = REPO_ROOT / "README.md"
    content_readme = readme_path.read_text(encoding="utf-8")
    help_text = blocks.get_help_message()

    # Find keywords that help text marks as (Admin Only)
    admin_keywords_in_help = []
    for line in help_text.splitlines():
        if "(Admin Only" in line:
            # find `@Purchasing <keyword>`
            match = re.search(r"@Purchasing\s+([a-zA-Z0-9_\-]+)", line)
            if match:
                admin_keywords_in_help.append(match.group(1))

    assert admin_keywords_in_help, "No admin keywords found in help text"

    # Also check against config.ADMIN_ONLY_KEYWORDS
    for kw in config.ADMIN_ONLY_KEYWORDS:
        assert kw in content_readme, f"Admin keyword '{kw}' missing from README.md"

    for kw in admin_keywords_in_help:
        assert kw in content_readme, f"Admin keyword '{kw}' from help text missing from README.md"


def test_docs_contain_no_p_bot_outside_adr():
    """No file under docs/ outside docs/adr/ contains @p-bot or P-Bot."""
    docs_dir = REPO_ROOT / "docs"
    assert docs_dir.exists(), "docs/ does not exist"

    md_files = [
        f for f in docs_dir.rglob("*.md")
        if "adr" not in f.parts
    ]
    assert len(md_files) > 0, "No markdown files found under docs/ outside adr/"

    violations = []
    for f in md_files:
        text = f.read_text(encoding="utf-8")
        if "@p-bot" in text.lower():
            violations.append(f"{f.relative_to(REPO_ROOT)}: contains @p-bot")
        # Check P-Bot (case-insensitive)
        if re.search(r"\bp-bot\b", text, re.IGNORECASE):
            violations.append(f"{f.relative_to(REPO_ROOT)}: contains P-Bot")

    assert not violations, "Found forbidden bot names in docs:\n" + "\n".join(violations)


def test_docs_adr_is_unmodified():
    """docs/adr/ has not been modified relative to master."""
    res = subprocess.run(
        ["git", "diff", "--stat", "origin/master", "--", "docs/adr"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    assert res.stdout.strip() == "", f"docs/adr has modifications:\n{res.stdout}"


def test_build_and_logs_still_name_p_bot_log_and_spec():
    """p_bot.log and p_bot.spec are still named where docs describe build and logs."""
    readme_path = REPO_ROOT / "README.md"
    readme_content = readme_path.read_text(encoding="utf-8")
    assert "p_bot.log" in readme_content

    exe_guide = REPO_ROOT / "docs" / "EXECUTABLE_BUILD.md"
    assert exe_guide.exists()
    exe_text = exe_guide.read_text(encoding="utf-8")
    assert "p_bot.spec" in exe_text
    assert "p_bot.log" in exe_text

    mon_spec = REPO_ROOT / "docs" / "MONITORING_AND_QUEUE_SPEC.md"
    assert mon_spec.exists()
    mon_text = mon_spec.read_text(encoding="utf-8")
    assert "p_bot.log" in mon_text
