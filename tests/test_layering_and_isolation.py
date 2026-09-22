"""Tests enforcing architectural layering rules and module isolation.

WHY THIS EXISTS:
----------------
Guards against architectural erosion:
1. Verifies pure layers (blocks, text_rules) can be imported and executed
   without importing Bolt App or Slack SDK.
2. Verifies that no module under src/ imports app (downward import flow invariant).
3. Verifies that importing src.app does not perform online auth verification when
   dummy tokens are configured (as in CI).
"""
import ast
import os
import subprocess
import sys

# Determine project root and src directory
_CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(_CURRENT_DIR) if os.path.basename(_CURRENT_DIR) == "tests" else _CURRENT_DIR
SRC_DIR = os.path.join(PROJECT_ROOT, "src")
for p in (PROJECT_ROOT, SRC_DIR):
    if p not in sys.path:
        sys.path.insert(0, p)


def test_pure_layers_importable_without_app():
    """Verify blocks, text_rules, and bom can be imported and called without initializing src.app."""
    code = (
        "import sys\n"
        "from src import blocks, text_rules, bom\n"
        "assert 'src.app' not in sys.modules, 'src.app was loaded'\n"
        "assert 'app' not in sys.modules, 'app was loaded'\n"
        "assert 'slack_bolt' not in sys.modules, 'slack_bolt was loaded'\n"
        "assert 'slack_sdk' not in sys.modules, 'slack_sdk was loaded'\n"
        "req = {'item_description': 'Resistors', 'total_price': 10.0}\n"
        "b = blocks.build_request_blocks('posted', req)\n"
        "assert isinstance(b, list) and len(b) > 0\n"
        "parsed = {'item_description': 'Resistors', 'vendor': 'DigiKey', 'total_price': 10.0}\n"
        "draft = text_rules.generate_email_draft(parsed, 'Isaac')\n"
        "assert 'Resistors' in draft and 'DigiKey' in draft\n"
        "items, ship, errs = bom.parse_line_items('1 | Item | P1 | 5.00')\n"
        "assert len(items) == 1 and errs == []\n"
    )
    res = subprocess.run(
        [sys.executable, "-c", code],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
    )
    assert res.returncode == 0, f"Subprocess failed:\nSTDOUT:\n{res.stdout}\nSTDERR:\n{res.stderr}"


def test_no_module_in_src_imports_app():
    """Walk src/ dynamically and assert no module imports app or src.app."""
    for root, _, files in os.walk(SRC_DIR):
        for fname in files:
            if not fname.endswith(".py"):
                continue
            fpath = os.path.join(root, fname)
            rel_path = os.path.relpath(fpath, PROJECT_ROOT)

            with open(fpath, "r", encoding="utf-8") as f:
                tree = ast.parse(f.read(), filename=fpath)

            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        assert alias.name not in ("app", "src.app"), (
                            f"{rel_path}:{node.lineno} imports '{alias.name}'. No module in src/ may import app."
                        )
                elif isinstance(node, ast.ImportFrom):
                    module = node.module or ""
                    # Check "from app import ...", "from src.app import ...", "from . import app", etc.
                    imported_names = [alias.name for alias in node.names]
                    assert module not in ("app", "src.app", ".app"), (
                        f"{rel_path}:{node.lineno} imports from '{module}'. No module in src/ may import from app."
                    )
                    if node.level > 0 and module in ("", "app"):
                        assert "app" not in imported_names, (
                            f"{rel_path}:{node.lineno} imports 'app' relatively. No module in src/ may import app."
                        )


def test_app_importable_with_dummy_or_missing_tokens():
    """Verify that importing src.app does not make network auth calls when dummy tokens are present.

    In CI and testing environments, SLACK_BOT_TOKEN is set to a dummy value (e.g., xoxb-test-not-a-real-token).
    App construction must set token_verification_enabled=False to avoid Bolt raising BoltError or attempting
    an online auth.test during module import.
    """
    code = (
        "import os\n"
        "os.environ['SLACK_BOT_TOKEN'] = 'xoxb-test-not-a-real-token'\n"
        "os.environ['SLACK_APP_TOKEN'] = 'xapp-test-not-a-real-token'\n"
        "from src import app\n"
        "assert app.app is not None\n"
    )
    res = subprocess.run(
        [sys.executable, "-c", code],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
    )
    assert res.returncode == 0, f"Subprocess failed:\nSTDOUT:\n{res.stdout}\nSTDERR:\n{res.stderr}"


def test_grad_student_buyers_deleted_and_unreferenced():
    """Verify config.GRAD_STUDENT_BUYERS is deleted and unreferenced in src/."""
    from src import config
    assert not hasattr(config, "GRAD_STUDENT_BUYERS"), "config.GRAD_STUDENT_BUYERS must be deleted."

    for root, _, files in os.walk(SRC_DIR):
        for fname in files:
            if not fname.endswith(".py"):
                continue
            fpath = os.path.join(root, fname)
            rel_path = os.path.relpath(fpath, PROJECT_ROOT)
            with open(fpath, "r", encoding="utf-8") as f:
                content = f.read()
            assert "GRAD_STUDENT_BUYERS" not in content, (
                f"{rel_path} still references GRAD_STUDENT_BUYERS."
            )


