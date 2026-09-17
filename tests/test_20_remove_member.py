"""Tests for Ticket 20: `@Purchasing remove-member @user`

Acceptance criteria:
- roster.remove_member on a user holding all three roles removes the ID from all four lists in one save, and a re-read from disk confirms it
- remove_member on the last admin is refused, roster.json is byte-identical afterwards, and the reply says why
- remove_member on the last approver, likewise
- A non-admin issuing remove-member is denied ephemerally and no write occurs
- After a removal, one message reaches ADMIN_ALERT_CHANNEL naming the sheet, the table and the cell reference of the orphaned dropdown entry
- After a removal, the workbook is byte-identical — the mirror is append-only and a removal writes nothing to it
- After a removal, validators.validate rejects that name
- @Purchasing remove-member @user matches as a two-word keyword and @Purchasing remove-buyer @user still strips only the buyer role, leaving the requesters entry intact — assert both in the same test
- REMOVE_MEMBER_KEYWORDS lives in config.py and appears nowhere else as a literal
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

from src import app, config, log_writer, ops, roster, validators
from tests.test_11_roster_sync import create_fixture_workbook


@pytest.fixture
def clean_roster(tmp_path, monkeypatch):
    """Provide a fresh roster.json in tmp_path with multiple admins, approvers, buyers, and requesters."""
    r_file = tmp_path / "roster.json"
    monkeypatch.setattr(roster, "ROSTER_PATH", str(r_file))
    monkeypatch.setattr(config, "ADMIN_ALERT_CHANNEL", "C_ADMIN_ALERTS")

    data = {
        "requesters": {
            "U_ADMIN_1": "Isaac",
            "U_ADMIN_2": "AdminTwo",
            "U_APPROVER_1": "Charlie",
            "U_APPROVER_2": "ApproverTwo",
            "U_BUYER_1": "Dylan",
            "U_ALL_ROLES": "Katarina",
        },
        "admins": ["U_ADMIN_1", "U_ADMIN_2", "U_ALL_ROLES"],
        "approvers": ["U_APPROVER_1", "U_APPROVER_2", "U_ALL_ROLES"],
        "buyers": ["U_BUYER_1", "U_ALL_ROLES"],
        "vendors": ["Fisher Scientific", "Grainger"],
    }
    roster.save_roster(data)
    return r_file


# 1. User holding all three roles removed from all four lists in one save
def test_remove_member_all_four_lists_in_one_save(clean_roster):
    """roster.remove_member removes user from requesters, admins, approvers, and buyers in one atomic save."""
    result = roster.remove_member("U_ALL_ROLES")

    assert result["slack_id"] == "U_ALL_ROLES"
    assert result["name"] == "Katarina"
    assert set(result["roles"]) == {"admin", "approver", "buyer"}
    assert result["requester_removed"] is True

    # Re-read raw JSON directly from disk
    with open(clean_roster, "r", encoding="utf-8") as f:
        disk_data = json.load(f)

    assert "U_ALL_ROLES" not in disk_data["requesters"]
    assert "U_ALL_ROLES" not in disk_data["admins"]
    assert "U_ALL_ROLES" not in disk_data["approvers"]
    assert "U_ALL_ROLES" not in disk_data["buyers"]

    # Verify other members were untouched
    assert "U_ADMIN_1" in disk_data["admins"]
    assert "U_APPROVER_1" in disk_data["approvers"]
    assert "U_BUYER_1" in disk_data["buyers"]
    assert disk_data["requesters"]["U_ADMIN_1"] == "Isaac"


# 2. Last admin refusal: byte-identical roster.json and reply explains why
def test_remove_member_last_admin_refused(tmp_path, monkeypatch):
    """Refuse removing the last admin; roster.json must be byte-identical and reply states why."""
    r_file = tmp_path / "roster.json"
    monkeypatch.setattr(roster, "ROSTER_PATH", str(r_file))

    data = {
        "requesters": {"U_SOLE_ADMIN": "Isaac", "U_APPROVER": "Charlie"},
        "admins": ["U_SOLE_ADMIN"],
        "approvers": ["U_APPROVER", "U_APPROVER_2"],
        "buyers": [],
        "vendors": [],
    }
    roster.save_roster(data)
    with open(r_file, "rb") as f:
        bytes_before = f.read()

    # Function call raises ValueError
    with pytest.raises(ValueError) as excinfo:
        roster.remove_member("U_SOLE_ADMIN")
    assert "last admin" in str(excinfo.value).lower()

    # Disk file is byte-identical
    with open(r_file, "rb") as f:
        bytes_after = f.read()
    assert bytes_before == bytes_after

    # Handler also catches refusal and replies explaining why
    client = MagicMock()
    say = MagicMock()
    ops.handle_remove_member(
        client=client,
        say=say,
        channel="C_CHANNEL",
        thread_ts="123.456",
        user_id="U_SOLE_ADMIN",
        text="@Purchasing remove-member <@U_SOLE_ADMIN>",
    )
    say.assert_called_once()
    reply_text = say.call_args[1]["text"]
    assert "last admin" in reply_text.lower()


# 3. Last approver refusal: byte-identical roster.json and reply explains why
def test_remove_member_last_approver_refused(tmp_path, monkeypatch):
    """Refuse removing the last approver; roster.json must be byte-identical and reply states why."""
    r_file = tmp_path / "roster.json"
    monkeypatch.setattr(roster, "ROSTER_PATH", str(r_file))

    data = {
        "requesters": {"U_ADMIN_1": "Isaac", "U_ADMIN_2": "Admin2", "U_SOLE_APPROVER": "Charlie"},
        "admins": ["U_ADMIN_1", "U_ADMIN_2"],
        "approvers": ["U_SOLE_APPROVER"],
        "buyers": [],
        "vendors": [],
    }
    roster.save_roster(data)
    with open(r_file, "rb") as f:
        bytes_before = f.read()

    # Function call raises ValueError
    with pytest.raises(ValueError) as excinfo:
        roster.remove_member("U_SOLE_APPROVER")
    assert "last approver" in str(excinfo.value).lower()

    # Disk file is byte-identical
    with open(r_file, "rb") as f:
        bytes_after = f.read()
    assert bytes_before == bytes_after

    # Handler also catches refusal and replies explaining why
    client = MagicMock()
    say = MagicMock()
    ops.handle_remove_member(
        client=client,
        say=say,
        channel="C_CHANNEL",
        thread_ts="123.456",
        user_id="U_ADMIN_1",
        text="@Purchasing remove-member <@U_SOLE_APPROVER>",
    )
    say.assert_called_once()
    reply_text = say.call_args[1]["text"]
    assert "last approver" in reply_text.lower()


# 4. Non-admin issuing remove-member is denied ephemerally and no write occurs
def test_remove_member_non_admin_denied_ephemerally(clean_roster):
    """A non-admin user running remove-member receives an ephemeral denial, no write occurs."""
    with open(clean_roster, "rb") as f:
        bytes_before = f.read()

    client = MagicMock()
    say = MagicMock()
    respond = MagicMock()

    ops.handle_remove_member(
        client=client,
        say=say,
        channel="C_CHANNEL",
        thread_ts="123.456",
        user_id="U_NON_ADMIN",
        text="@Purchasing remove-member <@U_BUYER_1>",
        respond=respond,
    )

    respond.assert_called_once()
    assert respond.call_args[1].get("response_type") == "ephemeral"
    assert respond.call_args[1].get("replace_original") is False
    say.assert_not_called()

    # No write occurs to roster.json
    with open(clean_roster, "rb") as f:
        bytes_after = f.read()
    assert bytes_before == bytes_after


# 5 & 6. Alert reaches ADMIN_ALERT_CHANNEL with sheet, table, cell ref; workbook is byte-identical
def test_remove_member_alerts_admin_with_cell_ref_and_leaves_workbook_byte_identical(tmp_path, monkeypatch, clean_roster):
    """After removal, exactly one message reaches ADMIN_ALERT_CHANNEL with sheet, table, cell ref, and workbook is byte-identical."""
    wb_path = str(tmp_path / "Purchasing-Log.xlsx")
    create_fixture_workbook(wb_path, req_count=13, grad_count=3)
    monkeypatch.setattr(config, "WORKBOOK_PATH", wb_path)

    with open(wb_path, "rb") as f:
        wb_bytes_before = f.read()

    client = MagicMock()
    say = MagicMock()

    # Katarina is at index 9 in STARTING_REQUESTERS -> row 5 + 9 = row 14 -> D14
    ops.handle_remove_member(
        client=client,
        say=say,
        channel="C_CHANNEL",
        thread_ts="123.456",
        user_id="U_ADMIN_1",
        text="@Purchasing remove-member <@U_ALL_ROLES>",
    )

    # Exactly one message to ADMIN_ALERT_CHANNEL
    client.chat_postMessage.assert_called_once()
    call_kwargs = client.chat_postMessage.call_args[1]
    assert call_kwargs["channel"] == "C_ADMIN_ALERTS"
    alert_text = call_kwargs["text"]

    # Names sheet, table, and cell reference
    assert "Roles & Lists" in alert_text
    assert "Requesters" in alert_text
    assert "D14" in alert_text

    # Workbook is byte-identical (append-only mirror writes nothing on removal)
    with open(wb_path, "rb") as f:
        wb_bytes_after = f.read()
    assert wb_bytes_before == wb_bytes_after


def test_find_requester_cell_direct(tmp_path):
    """log_writer.find_requester_cell finds the exact cell reference in Roles & Lists without modifying file."""
    wb_path = str(tmp_path / "Purchasing-Log.xlsx")
    create_fixture_workbook(wb_path, req_count=13, grad_count=3)

    assert log_writer.find_requester_cell("Katarina", wb_path) == "D14"
    assert log_writer.find_requester_cell("katarina", wb_path) == "D14"
    assert log_writer.find_requester_cell("Isaac", wb_path) == "D5"
    assert log_writer.find_requester_cell("NonExistentPerson", wb_path) is None
    assert log_writer.find_requester_cell("", wb_path) is None
    assert log_writer.find_requester_cell("Katarina", str(tmp_path / "nonexistent.xlsx")) is None


# 7. Removal takes effect immediately on validators.validate
def test_remove_member_immediate_validator_rejection(clean_roster):
    """After removing a member, validators.validate immediately rejects their name."""
    parsed = {
        "item_description": "Laser Diode",
        "purpose": "Optics experiment",
        "total_price": 100.0,
        "vendor": "Fisher Scientific",
        "vendor_contact_email": "orders@fisher.com",
        "date_of_purchase": "09/17/26",
        "project_id": "PG000025831",
        "fund": "133",
        "delivery_room": "ERB 212",
        "payment_method": "PCard",
    }

    # Before removal, Katarina is valid
    problems_before = validators.validate(parsed, "Katarina")
    assert not any("Requester Name dropdown" in p for p in problems_before)

    # Remove member
    roster.remove_member("U_ALL_ROLES")

    # After removal, Katarina is rejected
    problems_after = validators.validate(parsed, "Katarina")
    assert any("Requester Name dropdown" in p for p in problems_after)


# 8. remove-member vs remove-buyer distinction in the same test
def test_remove_member_vs_remove_buyer_distinction(clean_roster):
    """remove-buyer strips only buyer role leaving requesters intact; remove-member hard-deletes member."""
    # U_BUYER_1 is in requesters as "Dylan" and in buyers
    assert roster.is_buyer("U_BUYER_1")
    assert roster.get_requesters().get("U_BUYER_1") == "Dylan"

    client = MagicMock()
    say = MagicMock()

    # 1. Run remove-buyer via dispatch_command
    app.dispatch_command(
        client=client,
        say=say,
        channel="C_MAIN",
        thread_ts="100.1",
        user="U_ADMIN_1",
        event_ts="100.1",
        text="@Purchasing remove-buyer <@U_BUYER_1>",
    )

    # Buyer role is stripped, but requester entry is intact
    assert not roster.is_buyer("U_BUYER_1")
    assert roster.get_requesters().get("U_BUYER_1") == "Dylan"

    # 2. Run remove-member via dispatch_command
    say.reset_mock()
    app.dispatch_command(
        client=client,
        say=say,
        channel="C_MAIN",
        thread_ts="100.2",
        user="U_ADMIN_1",
        event_ts="100.2",
        text="@Purchasing remove-member <@U_BUYER_1>",
    )

    # Member is completely removed from requesters as well
    assert "U_BUYER_1" not in roster.get_requesters()


# 9. REMOVE_MEMBER_KEYWORDS lives in config.py and appears nowhere else as a literal
def test_remove_member_keywords_lives_in_config_and_no_literals_in_src():
    """REMOVE_MEMBER_KEYWORDS lives in config.py and does not appear as string literals elsewhere in src/."""
    assert hasattr(config, "REMOVE_MEMBER_KEYWORDS")
    assert "remove-member" in config.REMOVE_MEMBER_KEYWORDS
    assert "remove member" in config.REMOVE_MEMBER_KEYWORDS
    assert config.REMOVE_MEMBER_KEYWORDS in config.ALL_KEYWORD_TUPLES

    target_literals = {"remove-member", "remove member"}
    violations = []

    for root, _, files in os.walk(SRC_DIR):
        for fname in files:
            if not fname.endswith(".py"):
                continue
            fpath = os.path.join(root, fname)
            rel_path = os.path.relpath(fpath, PROJECT_ROOT).replace("\\", "/")
            if rel_path == "src/config.py":
                continue

            with open(fpath, "r", encoding="utf-8") as f:
                tree = ast.parse(f.read(), filename=fpath)

            for node in ast.walk(tree):
                # Ignore docstrings
                if isinstance(node, (ast.FunctionDef, ast.ClassDef, ast.Module)):
                    continue
                if isinstance(node, ast.Constant) and isinstance(node.value, str):
                    val = node.value.strip().lower()
                    if val in target_literals:
                        violations.append((rel_path, node.lineno, val))

    assert not violations, f"Found literal remove-member strings in src/ outside config.py: {violations}"
