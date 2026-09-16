"""Tests for Ticket 15: PURCHASING_CHANNEL is a constant with a home, and has no silent fallback.

WHY THIS EXISTS:
----------------
Per Ticket 15:
1. `config.PURCHASING_CHANNEL` exists beside `ADMIN_ALERT_CHANNEL`, read from
   the environment in `config.py` like every other constant. `lifecycle.py` reads
   it from `config`.
2. The fallback chain that silently routed /new-purchase requests to `ADMIN_ALERT_CHANNEL`
   or to the requester's own DM is removed.
3. Unset is an operator-facing startup error logged through `path_validator`'s
   existing operator-facing check, and the bot refuses to post purchase requests.
4. A source scan asserts `os.environ` is read nowhere in `src/` outside `config.py`
   (excepting existing grandfathered bot-token/path reads in app/slack_io/path_validator).
"""
import ast
import os
import sys
from unittest.mock import MagicMock

import pytest

# Determine project root and src directory
_CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(_CURRENT_DIR) if os.path.basename(_CURRENT_DIR) == "tests" else _CURRENT_DIR
SRC_DIR = os.path.join(PROJECT_ROOT, "src")
for p in (PROJECT_ROOT, SRC_DIR):
    if p not in sys.path:
        sys.path.insert(0, p)

from src import config, lifecycle, path_validator, roster


@pytest.fixture(autouse=True)
def setup_roster_and_env(tmp_path, monkeypatch):
    """Ensure tests run against an isolated roster and clean config."""
    test_roster = str(tmp_path / "roster.json")
    monkeypatch.setattr(roster, "ROSTER_PATH", test_roster)
    roster.load_roster()
    monkeypatch.setattr(roster, "_trigger_roster_sync", lambda: None)
    # Ensure Isaac is registered as a requester for validation
    roster.add_requester("U123", "Isaac")
    return test_roster


def _make_valid_stage_data():
    meta = {
        "resolved_name": "Isaac",
        "user_id": "U123",
        "vendor_choice": "DigiKey",
        "vendor_custom": None,
        "route": "Workday",
        "is_pending_name": False,
    }
    stage2 = {
        "item_description": "Oscilloscope probe",
        "total_price": "120.00",
        "vendor_contact_name": "Support",
        "vendor_contact_email": "support@digikey.com",
        "project_id": "PG000025831",
        "fund": "133",
        "delivery_room": "ERB 212",
        "purpose": "Sensor testing",
        "category": "Research/Lab Supplies (3105)",
        "payment_method": "P-card",
        "date_of_purchase": "09/16/26",
    }
    return meta, stage2


# ---------------------------------------------------------------------------
# 1. config.PURCHASING_CHANNEL exists and is a constant with a home
# ---------------------------------------------------------------------------

def test_config_purchasing_channel_exists():
    """Verify config.PURCHASING_CHANNEL exists and is read in config.py."""
    assert hasattr(config, "PURCHASING_CHANNEL"), "config.PURCHASING_CHANNEL must exist."
    assert isinstance(config.PURCHASING_CHANNEL, str)


# ---------------------------------------------------------------------------
# 2. /new-purchase posts to config.PURCHASING_CHANNEL (not ADMIN_ALERT_CHANNEL)
# ---------------------------------------------------------------------------

def test_new_purchase_posts_to_config_purchasing_channel(monkeypatch):
    """Assert /new-purchase submission posts to config.PURCHASING_CHANNEL, not ADMIN_ALERT_CHANNEL."""
    target_channel = "C_PURCHASING_SPECIFIC_123"
    alert_channel = "C_ADMIN_ALERTS_456"
    monkeypatch.setattr(config, "PURCHASING_CHANNEL", target_channel)
    monkeypatch.setattr(config, "ADMIN_ALERT_CHANNEL", alert_channel)

    ack = MagicMock()
    client = MagicMock()
    body = {"user": {"id": "U123"}}
    meta, stage2 = _make_valid_stage_data()

    lifecycle._process_interview_completion(ack, client, body, meta, stage2, stage3=None)

    ack.assert_called_once()
    assert client.chat_postMessage.called, "chat_postMessage must be called to post request."

    posted_channels = [
        call_args[1].get("channel")
        for call_args in client.chat_postMessage.call_args_list
    ]

    # The request card must be posted to target_channel, and never to alert_channel
    assert target_channel in posted_channels, f"Expected post to {target_channel}, got {posted_channels}"
    assert alert_channel not in posted_channels, (
        f"Request card was unexpectedly posted to ADMIN_ALERT_CHANNEL {alert_channel}!"
    )


# ---------------------------------------------------------------------------
# 3. With PURCHASING_CHANNEL unset: startup check reports error & no post to alert/DM
# ---------------------------------------------------------------------------

def test_purchasing_channel_unset_reports_startup_error_and_refuses_post(monkeypatch, caplog):
    """When PURCHASING_CHANNEL is unset, check reports error and no request is posted to alerts or DM."""
    monkeypatch.setattr(config, "PURCHASING_CHANNEL", "")
    alert_channel = "C_ADMIN_ALERTS_456"
    monkeypatch.setattr(config, "ADMIN_ALERT_CHANNEL", alert_channel)

    # 1. Startup check reports error
    is_valid = path_validator.check_purchasing_channel()
    assert is_valid is False, "path_validator.check_purchasing_channel() must return False when unset"

    # 2. Attempting a submission must refuse to post purchase request
    ack = MagicMock()
    client = MagicMock()
    body = {"user": {"id": "U123"}}
    meta, stage2 = _make_valid_stage_data()

    lifecycle._process_interview_completion(ack, client, body, meta, stage2, stage3=None)

    # Assert on the absence of both: no post to ADMIN_ALERT_CHANNEL, no post to user_id DM
    posted_channels = [
        call_args[1].get("channel")
        for call_args in client.chat_postMessage.call_args_list
    ]

    assert alert_channel not in posted_channels, (
        f"Fallback violation: Request was posted to ADMIN_ALERT_CHANNEL ({alert_channel})"
    )
    assert "U123" not in posted_channels, (
        "Fallback violation: Request was posted to requester DM (U123)"
    )


# ---------------------------------------------------------------------------
# 4. AST scan: os.environ is read nowhere in src/ outside config.py
# ---------------------------------------------------------------------------

def test_ast_scan_no_unapproved_os_environ_reads_outside_config():
    """Assert os.environ is read nowhere in src/ except config.py.

    Grandfathered reads per Ticket 15 Out-of-Scope (SLACK_BOT_TOKEN, SLACK_APP_TOKEN, USERNAME).
    Fails if a new inline read is added outside config.py.
    """
    # Allowed baseline: (relative_path, variable_name)
    ALLOWED_BASELINE = {
        ("src/app.py", "SLACK_BOT_TOKEN"),
        ("src/app.py", "SLACK_APP_TOKEN"),
        ("src/slack_io.py", "SLACK_BOT_TOKEN"),
        ("src/path_validator.py", "USERNAME"),
    }

    discovered_reads = []

    for root, _, files in os.walk(SRC_DIR):
        for fname in files:
            if not fname.endswith(".py") or fname == "config.py":
                continue
            fpath = os.path.join(root, fname)
            rel_path = os.path.relpath(fpath, PROJECT_ROOT).replace("\\", "/")

            with open(fpath, "r", encoding="utf-8") as f:
                tree = ast.parse(f.read(), filename=fpath)

            for node in ast.walk(tree):
                # Catch os.environ.get("VAR")
                if isinstance(node, ast.Call):
                    func = node.func
                    # os.environ.get("VAR")
                    if (
                        isinstance(func, ast.Attribute)
                        and func.attr == "get"
                        and isinstance(func.value, ast.Attribute)
                        and func.value.attr == "environ"
                        and isinstance(func.value.value, ast.Name)
                        and func.value.value.id == "os"
                    ):
                        var_name = node.args[0].value if node.args and isinstance(node.args[0], ast.Constant) else "UNKNOWN"
                        if (rel_path, var_name) not in ALLOWED_BASELINE:
                            discovered_reads.append((rel_path, node.lineno, f"os.environ.get('{var_name}')"))

                    # os.getenv("VAR")
                    if (
                        isinstance(func, ast.Attribute)
                        and func.attr == "getenv"
                        and isinstance(func.value, ast.Name)
                        and func.value.id == "os"
                    ):
                        var_name = node.args[0].value if node.args and isinstance(node.args[0], ast.Constant) else "UNKNOWN"
                        if (rel_path, var_name) not in ALLOWED_BASELINE:
                            discovered_reads.append((rel_path, node.lineno, f"os.getenv('{var_name}')"))

                # Catch direct subscript read: os.environ["VAR"]
                if isinstance(node, ast.Subscript) and isinstance(node.ctx, ast.Load):
                    val = node.value
                    if (
                        isinstance(val, ast.Attribute)
                        and val.attr == "environ"
                        and isinstance(val.value, ast.Name)
                        and val.value.id == "os"
                    ):
                        slice_node = node.slice
                        var_name = slice_node.value if isinstance(slice_node, ast.Constant) else "UNKNOWN"
                        if (rel_path, var_name) not in ALLOWED_BASELINE:
                            discovered_reads.append((rel_path, node.lineno, f"os.environ['{var_name}']"))

    assert not discovered_reads, (
        "Discovered unapproved inline environment variable read(s) in src/:\n"
        + "\n".join(f"  {r[0]}:{r[1]} -> {r[2]}" for r in discovered_reads)
        + "\nPer Invariant 4, all constants must live in config.py."
    )
