"""Tests for Ticket 19: One /roster-set-name covering register, correct and rename.

Acceptance criteria:
- blocks.build_roster_set_name_view(user_id, current_name) exists, is pure, and is asserted on without faking views_open
- The modal shows the submitter's current registered name; for an unregistered user it says so — asserted on the specific name, not on block count
- The modal does not contain the full lab roster
- Submitting a name another member holds: a field error, and nothing posted to ADMIN_ALERT_CHANNEL — assert on the absence
- Submitting "  isaac " from the user registered as Isaac: applied immediately, roster.json updated, nothing posted to the alert channel
- Submitting a brand-new name from an unregistered user: the alert channel gets one message with an approve_new_requester button carrying that name, and roster.json is unchanged until it is clicked
- Clicking that button registers the name and triggers sync_roster_lists
- Submitting a different name from a registered user: a rename request reaches the alert channel naming both names
- Each of the four outcomes tells the submitter which one happened
- chat_postEphemeral appears nowhere in src/, and the invariant 5 guard test asserts zero
- ruff check ., python scripts/check_tests_first.py and pytest -q all pass
"""
import ast
import json
import os
import sys
from unittest.mock import MagicMock

import pytest

_CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(_CURRENT_DIR) if os.path.basename(_CURRENT_DIR) == "tests" else _CURRENT_DIR
SRC_DIR = os.path.join(PROJECT_ROOT, "src")
for p in (PROJECT_ROOT, SRC_DIR):
    if p not in sys.path:
        sys.path.insert(0, p)

from src import app, blocks, config, roster


@pytest.fixture(autouse=True)
def temp_roster(tmp_path, monkeypatch):
    roster_path = str(tmp_path / "roster.json")
    with open(roster_path, "w", encoding="utf-8") as f:
        json.dump({
            "requesters": {"U_ISAAC": "Isaac", "U_DYLAN": "Dylan"},
            "admins": ["U_ADMIN"],
            "approvers": ["U07L2RFEPJ9"],
            "buyers": ["U_DYLAN"],
            "vendors": [],
        }, f)
    monkeypatch.setattr(roster, "ROSTER_PATH", roster_path)
    monkeypatch.setattr(config, "ADMIN_ALERT_CHANNEL", "C_ALERTS")
    return roster_path


# 1. Pure modal builder assertions
def test_build_roster_set_name_view_pure_registered():
    """Modal for registered user shows their current name and does not contain the full lab roster."""
    view = blocks.build_roster_set_name_view("U_ISAAC", "Isaac")
    assert isinstance(view, dict)
    assert view["type"] == "modal"
    assert view["callback_id"] == config.ROSTER_SET_NAME_CALLBACK_ID

    # View text includes specific name
    view_str = json.dumps(view)
    assert "Isaac" in view_str
    assert "registered in the roster as *Isaac*" in view_str

    # View does not contain the full lab roster
    for name in roster.DEFAULT_VALID_REQUESTERS:
        if name != "Isaac":
            assert name not in view_str


def test_build_roster_set_name_view_pure_unregistered():
    """Modal for unregistered user states they are not yet registered."""
    view = blocks.build_roster_set_name_view("U_NEW", None)
    assert isinstance(view, dict)
    view_str = json.dumps(view)
    assert "not yet registered" in view_str

    # View does not contain the full lab roster
    for name in roster.DEFAULT_VALID_REQUESTERS:
        assert name not in view_str


# 2. Outcome 1: Submitting a name another member already holds
def test_submit_name_another_member_holds_returns_field_error_and_no_alert():
    """Submitting a name another member holds returns a modal field error and posts nothing to alert channel."""
    ack = MagicMock()
    client = MagicMock()

    view_impersonate = {
        "state": {"values": {"block_proposed_name": {"proposed_name": {"value": "Isaac"}}}},
        "private_metadata": json.dumps({"user_id": "U_BOB", "channel_id": "C_MAIN"}),
    }
    app.handle_roster_set_name_submit(ack, {"user": {"id": "U_BOB"}}, client, view_impersonate)

    ack.assert_called_once()
    assert ack.call_args[1]["response_action"] == "errors"
    assert "block_proposed_name" in ack.call_args[1]["errors"]
    assert "already held" in ack.call_args[1]["errors"]["block_proposed_name"]

    # Nothing posted to ADMIN_ALERT_CHANNEL or anywhere
    client.chat_postMessage.assert_not_called()


def test_submit_name_another_member_holds_with_whitespace_and_case():
    """Impersonation check normalizes case, whitespace, and punctuation."""
    ack = MagicMock()
    client = MagicMock()

    view_impersonate = {
        "state": {"values": {"block_proposed_name": {"proposed_name": {"value": "  isaac.  "}}}},
        "private_metadata": json.dumps({"user_id": "U_BOB", "channel_id": "C_MAIN"}),
    }
    app.handle_roster_set_name_submit(ack, {"user": {"id": "U_BOB"}}, client, view_impersonate)

    ack.assert_called_once()
    assert ack.call_args[1]["response_action"] == "errors"
    assert "already held" in ack.call_args[1]["errors"]["block_proposed_name"]
    client.chat_postMessage.assert_not_called()


# 3. Outcome 2: Submitting normalization-only change to submitter's own name
def test_submit_normalization_change_applies_immediately():
    """Submitting '  isaac ' from user registered as Isaac applies immediately, no alert posted."""
    ack = MagicMock()
    client = MagicMock()

    view_normalize = {
        "state": {"values": {"block_proposed_name": {"proposed_name": {"value": "  isaac "}}}},
        "private_metadata": json.dumps({"user_id": "U_ISAAC", "channel_id": "C_MAIN"}),
    }
    app.handle_roster_set_name_submit(ack, {"user": {"id": "U_ISAAC"}}, client, view_normalize)

    ack.assert_called_once_with()
    # Roster updated immediately
    assert roster.get_requesters()["U_ISAAC"] == "isaac"

    # Nothing posted to alert channel
    alert_calls = [c for c in client.chat_postMessage.call_args_list if c[1].get("channel") == "C_ALERTS"]
    assert len(alert_calls) == 0

    # Submitter receives DM telling them it was applied
    user_calls = [c for c in client.chat_postMessage.call_args_list if c[1].get("channel") == "U_ISAAC"]
    assert len(user_calls) == 1
    assert "updated" in user_calls[0][1]["text"]


# 4. Outcome 4: Brand-new name from unregistered user
def test_submit_brand_new_name_unregistered_user_creates_alert_and_approval_works(monkeypatch):
    """Submitting a new name from unregistered user waits on admin; roster unchanged until clicked."""
    ack = MagicMock()
    client = MagicMock()

    # Track sync task calls
    sync_mock = MagicMock()
    monkeypatch.setattr(roster, "_trigger_roster_sync", sync_mock)

    view_new = {
        "state": {"values": {"block_proposed_name": {"proposed_name": {"value": "Alice"}}}},
        "private_metadata": json.dumps({"user_id": "U_NEW", "channel_id": "C_MAIN"}),
    }
    app.handle_roster_set_name_submit(ack, {"user": {"id": "U_NEW"}}, client, view_new)

    ack.assert_called_once_with()
    # Roster unchanged before approval
    assert "U_NEW" not in roster.get_requesters()

    # Alert posted with approve_new_requester button
    alert_calls = [c for c in client.chat_postMessage.call_args_list if c[1].get("channel") == "C_ALERTS"]
    assert len(alert_calls) == 1
    alert_args = alert_calls[0][1]
    assert "Alice" in alert_args["text"]
    assert "<@U_NEW>" in alert_args["text"]

    actions_block = next(b for b in alert_args["blocks"] if b["type"] == "actions")
    btn = actions_block["elements"][0]
    assert btn["action_id"] == "approve_new_requester"
    btn_val = json.loads(btn["value"])
    assert btn_val["slack_id"] == "U_NEW"
    assert btn_val["name"] == "Alice"

    # Submitter told it is waiting on admin
    user_calls = [c for c in client.chat_postMessage.call_args_list if c[1].get("channel") == "U_NEW"]
    assert len(user_calls) == 1
    assert "waiting on an admin" in user_calls[0][1]["text"]

    # Now simulate admin clicking the button
    btn_ack = MagicMock()
    btn_respond = MagicMock()
    btn_client = MagicMock()
    body = {
        "user": {"id": "U_ADMIN"},
        "channel": {"id": "C_ALERTS"},
        "message": {"ts": "1234.5678"},
        "actions": [{"value": json.dumps(btn_val)}],
    }
    app.handle_approve_new_requester_action(btn_ack, body, btn_respond, btn_client)

    btn_ack.assert_called_once_with()
    assert roster.get_requesters()["U_NEW"] == "Alice"
    sync_mock.assert_called()


# 5. Outcome 3: Different name from registered user (rename)
def test_submit_different_name_registered_user_creates_rename_alert_and_approval_works(monkeypatch):
    """Submitting a different name from registered user reaches alert channel naming both names."""
    ack = MagicMock()
    client = MagicMock()

    sync_mock = MagicMock()
    monkeypatch.setattr(roster, "_trigger_roster_sync", sync_mock)

    view_rename = {
        "state": {"values": {"block_proposed_name": {"proposed_name": {"value": "Ike"}}}},
        "private_metadata": json.dumps({"user_id": "U_ISAAC", "channel_id": "C_MAIN"}),
    }
    app.handle_roster_set_name_submit(ack, {"user": {"id": "U_ISAAC"}}, client, view_rename)

    ack.assert_called_once_with()
    # Roster unchanged before approval
    assert roster.get_requesters()["U_ISAAC"] == "Isaac"

    # Alert posted naming BOTH Isaac and Ike
    alert_calls = [c for c in client.chat_postMessage.call_args_list if c[1].get("channel") == "C_ALERTS"]
    assert len(alert_calls) == 1
    alert_args = alert_calls[0][1]
    assert "Isaac" in alert_args["text"]
    assert "Ike" in alert_args["text"]

    actions_block = next(b for b in alert_args["blocks"] if b["type"] == "actions")
    btn = actions_block["elements"][0]
    assert btn["action_id"] == "approve_new_requester"
    btn_val = json.loads(btn["value"])
    assert btn_val["slack_id"] == "U_ISAAC"
    assert btn_val["old_name"] == "Isaac"
    assert btn_val["new_name"] == "Ike"

    # Submitter told it was sent to admins for approval
    user_calls = [c for c in client.chat_postMessage.call_args_list if c[1].get("channel") == "U_ISAAC"]
    assert len(user_calls) == 1
    assert "sent to admins" in user_calls[0][1]["text"]

    # Now simulate admin clicking approve rename
    btn_ack = MagicMock()
    btn_respond = MagicMock()
    btn_client = MagicMock()
    body = {
        "user": {"id": "U_ADMIN"},
        "channel": {"id": "C_ALERTS"},
        "message": {"ts": "1234.5678"},
        "actions": [{"value": json.dumps(btn_val)}],
    }
    app.handle_approve_new_requester_action(btn_ack, body, btn_respond, btn_client)

    btn_ack.assert_called_once_with()
    assert roster.get_requesters()["U_ISAAC"] == "Ike"
    sync_mock.assert_called()


# 6. Source scan asserting zero chat_postEphemeral calls in src/
def test_zero_chat_post_ephemeral_call_sites_in_src():
    """Pin that zero chat_postEphemeral call sites remain in src/."""
    call_sites = []
    for root, _, files in os.walk(SRC_DIR):
        for fname in files:
            if not fname.endswith(".py"):
                continue
            fpath = os.path.join(root, fname)
            with open(fpath, "r", encoding="utf-8") as f:
                tree = ast.parse(f.read(), filename=fpath)
            for node in ast.walk(tree):
                if isinstance(node, ast.Call):
                    func = node.func
                    if isinstance(func, ast.Attribute) and func.attr == "chat_postEphemeral":
                        call_sites.append((os.path.relpath(fpath, PROJECT_ROOT), node.lineno))

    assert len(call_sites) == 0, (
        f"Expected exactly 0 chat_postEphemeral call sites in src/, found {len(call_sites)}: {call_sites}"
    )
