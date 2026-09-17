import json
import os
import sys

import pytest

# Determine project root and src directory
_CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(_CURRENT_DIR) if os.path.basename(_CURRENT_DIR) == "tests" else _CURRENT_DIR
SRC_DIR = os.path.join(PROJECT_ROOT, "src")
for p in (PROJECT_ROOT, SRC_DIR):
    if p not in sys.path:
        sys.path.insert(0, p)

from src import roster


@pytest.fixture(autouse=True)
def temp_roster_file(tmp_path, monkeypatch):
    test_roster_path = str(tmp_path / "roster.json")
    monkeypatch.setattr(roster, "ROSTER_PATH", test_roster_path)
    return test_roster_path


def test_roster_first_run_seeding(temp_roster_file):
    assert not os.path.exists(temp_roster_file)
    data = roster.load_roster()
    assert os.path.exists(temp_roster_file)
    assert "requesters" in data
    assert set(data["requesters"].values()) == set(roster.DEFAULT_VALID_REQUESTERS)
    assert "admins" in data
    assert "approvers" in data
    assert "buyers" in data
    assert data["buyers"] == []
    assert "vendors" in data
    assert "U07L2RFEPJ9" in data["approvers"]
    assert "Fisher Scientific" in data["vendors"]

    # Assert seeded file's contents on disk
    with open(temp_roster_file, "r", encoding="utf-8") as f:
        disk_data = json.load(f)
    assert set(disk_data["requesters"].values()) == set(roster.DEFAULT_VALID_REQUESTERS)


def test_get_valid_requesters_returns_exactly_roster_names_for_single_name(tmp_path, monkeypatch):
    """get_valid_requesters() returns exactly the roster's names for a roster file containing one name."""
    custom_roster_path = str(tmp_path / "single_member_roster.json")
    with open(custom_roster_path, "w", encoding="utf-8") as f:
        json.dump({
            "requesters": {"U_ALICE": "Alice"},
            "admins": [],
            "approvers": ["U07L2RFEPJ9"],
            "buyers": [],
            "vendors": [],
        }, f)
    monkeypatch.setattr(roster, "ROSTER_PATH", custom_roster_path)

    valid_names = roster.get_valid_requesters()
    assert valid_names == {"Alice"}


def test_name_in_default_valid_requesters_not_in_roster_does_not_validate(tmp_path, monkeypatch):
    """A name in DEFAULT_VALID_REQUESTERS but not in roster.json does not validate."""
    custom_roster_path = str(tmp_path / "custom_roster.json")
    with open(custom_roster_path, "w", encoding="utf-8") as f:
        json.dump({
            "requesters": {"U_BOB": "Bob"},
            "admins": [],
            "approvers": ["U07L2RFEPJ9"],
            "buyers": [],
            "vendors": [],
        }, f)
    monkeypatch.setattr(roster, "ROSTER_PATH", custom_roster_path)

    valid_names = roster.get_valid_requesters()
    assert "Bob" in valid_names
    for seed_name in roster.DEFAULT_VALID_REQUESTERS:
        assert seed_name not in valid_names


def test_default_valid_requesters_referenced_only_in_get_initial_seed():
    """Source scan asserting DEFAULT_VALID_REQUESTERS is referenced only inside _get_initial_seed."""
    import ast

    roster_file = os.path.join(SRC_DIR, "roster.py")
    with open(roster_file, "r", encoding="utf-8") as f:
        tree = ast.parse(f.read(), filename=roster_file)

    references = []
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            for child in ast.walk(node):
                if isinstance(child, ast.Name) and child.id == "DEFAULT_VALID_REQUESTERS":
                    references.append((node.name, child.lineno))

    assert len(references) > 0, "DEFAULT_VALID_REQUESTERS should be referenced in _get_initial_seed"
    for func_name, lineno in references:
        assert func_name == "_get_initial_seed", (
            f"DEFAULT_VALID_REQUESTERS referenced at line {lineno} in function '{func_name}', "
            "but must only be referenced inside '_get_initial_seed'."
        )

    for root, _, files in os.walk(SRC_DIR):
        for fname in files:
            if not fname.endswith(".py") or fname == "roster.py":
                continue
            fpath = os.path.join(root, fname)
            with open(fpath, "r", encoding="utf-8") as f:
                content = f.read()
            assert "DEFAULT_VALID_REQUESTERS" not in content, (
                f"{fname} references DEFAULT_VALID_REQUESTERS; it must only be in roster.py"
            )


def test_roster_backfill_missing_buyers_key(tmp_path, monkeypatch):
    """A roster JSON without a 'buyers' key loads cleanly and get_buyers returns []."""
    test_roster = str(tmp_path / "legacy_roster.json")
    legacy_data = {
        "requesters": {"U1": "Isaac"},
        "admins": ["U1"],
        "approvers": ["U07L2RFEPJ9"],
        "vendors": ["Fisher Scientific"],
    }
    with open(test_roster, "w", encoding="utf-8") as f:
        json.dump(legacy_data, f)
    monkeypatch.setattr(roster, "ROSTER_PATH", test_roster)

    # Must not raise KeyError, must return []
    assert roster.get_buyers() == []

    # Verify backfill was saved to disk
    with open(test_roster, "r", encoding="utf-8") as f:
        disk_data = json.load(f)
    assert "buyers" in disk_data
    assert disk_data["buyers"] == []


def test_buyer_management():
    """Test get_buyers, is_buyer, add_buyer, and remove_buyer functions."""
    assert roster.get_buyers() == []
    assert roster.is_buyer("U_BUYER1") is False
    assert roster.is_buyer("") is False
    assert roster.is_buyer(None) is False

    roster.add_buyer("U_BUYER1")
    buyers = roster.get_buyers()
    assert "U_BUYER1" in buyers
    assert roster.is_buyer("U_BUYER1") is True
    assert roster.is_buyer("U_OTHER") is False

    # Adding duplicate should not duplicate
    roster.add_buyer("U_BUYER1")
    assert roster.get_buyers().count("U_BUYER1") == 1

    removed = roster.remove_buyer("U_BUYER1")
    assert removed is True
    assert "U_BUYER1" not in roster.get_buyers()
    assert roster.is_buyer("U_BUYER1") is False

    # Removing non-existent returns False
    assert roster.remove_buyer("NONEXISTENT") is False


def test_add_and_get_requester(temp_roster_file):
    roster.add_requester("U12345678", "Dylan")
    reqs = roster.get_requesters()
    assert reqs.get("U12345678") == "Dylan"

    # Reload fresh from disk
    with open(temp_roster_file, "r", encoding="utf-8") as f:
        disk_data = json.load(f)
    assert disk_data["requesters"]["U12345678"] == "Dylan"

    valid_names = roster.get_valid_requesters()
    assert "Dylan" in valid_names
    assert "Isaac" in valid_names


def test_admin_management():
    roster.add_admin("U999ADMIN")
    admins = roster.get_admins()
    assert "U999ADMIN" in admins


def test_approver_management():
    roster.add_approver("UNEWAPPROVER")
    approvers = roster.get_approvers()
    assert "UNEWAPPROVER" in approvers
    assert "U07L2RFEPJ9" in approvers

    removed = roster.remove_approver("UNEWAPPROVER")
    assert removed is True
    assert "UNEWAPPROVER" not in roster.get_approvers()

    # Removing non-existent returns False
    assert roster.remove_approver("NONEXISTENT") is False


def test_vendor_management():
    roster.add_vendor("Custom Bio Tech")
    vendors = roster.get_vendors()
    assert "Custom Bio Tech" in vendors

    # Remove existing
    assert roster.remove_vendor("Custom Bio Tech") is True
    assert "Custom Bio Tech" not in roster.get_vendors()

    # Case-insensitive removal
    roster.add_vendor("Acme Supplies")
    assert roster.remove_vendor("acme supplies") is True
    assert "Acme Supplies" not in roster.get_vendors()

    # Non-existent vendor
    assert roster.remove_vendor("NonExistentVendor123") is False
