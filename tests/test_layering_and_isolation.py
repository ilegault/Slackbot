"""Tests enforcing architectural layering rules and module isolation.

WHY THIS EXISTS:
----------------
Guards against architectural erosion:
1. Verifies pure layers (blocks, text_rules) can be imported and executed
   without importing Bolt App or Slack SDK.
2. Verifies that no module under src/ imports app (downward import flow invariant).
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
    """Verify blocks and text_rules can be imported and called without initializing src.app."""
    code = (
        "import sys\n"
        "from src import blocks, text_rules\n"
        "assert 'src.app' not in sys.modules, 'src.app was loaded'\n"
        "assert 'app' not in sys.modules, 'app was loaded'\n"
        "req = {'item_description': 'Resistors', 'total_price': 10.0}\n"
        "b = blocks.build_request_blocks('posted', req)\n"
        "assert isinstance(b, list) and len(b) > 0\n"
        "parsed = {'item_description': 'Resistors', 'vendor': 'DigiKey', 'total_price': 10.0}\n"
        "draft = text_rules.generate_email_draft(parsed, 'Isaac')\n"
        "assert 'Resistors' in draft and 'DigiKey' in draft\n"
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
