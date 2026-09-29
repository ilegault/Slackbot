"""Tests for Ticket 52: A hyphen and a space are the same in two-word commands.

Covers all acceptance criteria from .scratch/commands-paths-and-name/issues/52-hyphen-equals-space.md:
- Both spellings, every two-word keyword in config.ALL_KEYWORD_TUPLES, returning identical canonical value
- Drive real app.dispatch_command as an admin with remove-vendor / remove vendor / add-vendor / add vendor
- keyword_argument pure behavior (hyphen spelling, space spelling, extra spaces, no argument)
- Help text and App Home view contain remove-vendor and the hyphen-or-space explanation line
"""
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

from src import app, blocks, config, roster, text_rules


# ---------------------------------------------------------------------------
# Criterion 1: Both spellings, every two-word keyword in ALL_KEYWORD_TUPLES
# ---------------------------------------------------------------------------
def test_both_spellings_every_two_word_keyword():
    """Iterate over every multi-word phrase in config.ALL_KEYWORD_TUPLES and assert
    parse_keyword returns the same canonical value for hyphen spelling and space spelling
    followed by an argument (e.g. 'remove-vendor Thorlabs', 'remove vendor Thorlabs').
    """
    checked = 0
    for kw_tuple in config.ALL_KEYWORD_TUPLES:
        for phrase in kw_tuple:
            if " " in phrase or "-" in phrase:
                hyphen_spelling = phrase.replace(" ", "-")
                space_spelling = phrase.replace("-", " ")

                hyphen_with_arg = f"{hyphen_spelling} Thorlabs"
                space_with_arg = f"{space_spelling} Thorlabs"

                res_hyphen = text_rules.parse_keyword(hyphen_with_arg)
                res_space = text_rules.parse_keyword(space_with_arg)

                assert res_hyphen == phrase, (
                    f"parse_keyword('{hyphen_with_arg}') returned {res_hyphen!r}, expected {phrase!r}"
                )
                assert res_space == phrase, (
                    f"parse_keyword('{space_with_arg}') returned {res_space!r}, expected {phrase!r}"
                )
                assert res_hyphen == res_space
                checked += 1

    assert checked > 0, "No multi-word keywords found in config.ALL_KEYWORD_TUPLES"


# ---------------------------------------------------------------------------
# Criterion 3: Drive real app.dispatch_command for remove-vendor & add-vendor
# ---------------------------------------------------------------------------
@pytest.fixture
def temp_roster(tmp_path, monkeypatch):
    """Seed a temporary roster with an admin and sample vendors."""
    r_file = tmp_path / "roster.json"
    monkeypatch.setattr(roster, "ROSTER_PATH", str(r_file))

    data = {
        "requesters": {"U_ADMIN": "AdminUser"},
        "admins": ["U_ADMIN"],
        "approvers": ["U_APPROVER"],
        "buyers": ["U_BUYER"],
        "vendors": ["Temporary Vendor Inc", "Fisher Scientific"],
    }
    roster.save_roster(data)
    return r_file


def test_remove_vendor_hyphen_and_space_drives_dispatch_command(temp_roster, tmp_path, monkeypatch):
    """Drive real app.dispatch_command as admin with '@Purchasing remove-vendor Temporary Vendor Inc'
    and '@Purchasing remove vendor Temporary Vendor Inc' against temp rosters, asserting removal.
    """
    client = MagicMock()
    say = MagicMock()

    # 1. Hyphen spelling: remove-vendor
    assert "Temporary Vendor Inc" in roster.get_vendors()
    app.dispatch_command(
        client=client,
        say=say,
        channel="C_ADMIN",
        thread_ts="100.1",
        user="U_ADMIN",
        event_ts="100.1",
        text="@Purchasing remove-vendor Temporary Vendor Inc",
    )
    say.assert_called_once()
    assert "removed from `roster.json`" in say.call_args[1]["text"]
    assert "Temporary Vendor Inc" not in roster.get_vendors()

    # 2. Space spelling: remove vendor on a fresh temp roster
    r_file_2 = tmp_path / "roster_fresh.json"
    monkeypatch.setattr(roster, "ROSTER_PATH", str(r_file_2))
    roster.save_roster({
        "requesters": {"U_ADMIN": "AdminUser"},
        "admins": ["U_ADMIN"],
        "approvers": ["U_APPROVER"],
        "buyers": ["U_BUYER"],
        "vendors": ["Temporary Vendor Inc", "Fisher Scientific"],
    })
    assert "Temporary Vendor Inc" in roster.get_vendors()

    say.reset_mock()
    app.dispatch_command(
        client=client,
        say=say,
        channel="C_ADMIN",
        thread_ts="100.2",
        user="U_ADMIN",
        event_ts="100.2",
        text="@Purchasing remove vendor Temporary Vendor Inc",
    )
    say.assert_called_once()
    assert "removed from `roster.json`" in say.call_args[1]["text"]
    assert "Temporary Vendor Inc" not in roster.get_vendors()


def test_add_vendor_hyphen_and_space_drives_dispatch_command(temp_roster, tmp_path, monkeypatch):
    """Drive real app.dispatch_command as admin with '@Purchasing add-vendor New Vendor Corp'
    and '@Purchasing add vendor Another Vendor Ltd' against temp rosters, asserting addition.
    """
    client = MagicMock()
    say = MagicMock()

    # 1. Hyphen spelling: add-vendor
    assert "New Vendor Corp" not in roster.get_vendors()
    app.dispatch_command(
        client=client,
        say=say,
        channel="C_ADMIN",
        thread_ts="100.1",
        user="U_ADMIN",
        event_ts="100.1",
        text="@Purchasing add-vendor New Vendor Corp",
    )
    say.assert_called_once()
    assert "added to the Workday catalog" in say.call_args[1]["text"]
    assert "New Vendor Corp" in roster.get_vendors()

    # 2. Space spelling: add vendor
    say.reset_mock()
    assert "Another Vendor Ltd" not in roster.get_vendors()
    app.dispatch_command(
        client=client,
        say=say,
        channel="C_ADMIN",
        thread_ts="100.2",
        user="U_ADMIN",
        event_ts="100.2",
        text="@Purchasing add vendor Another Vendor Ltd",
    )
    say.assert_called_once()
    assert "added to the Workday catalog" in say.call_args[1]["text"]
    assert "Another Vendor Ltd" in roster.get_vendors()


# ---------------------------------------------------------------------------
# Criterion 4: keyword_argument is pure and tested directly
# ---------------------------------------------------------------------------
def test_keyword_argument_pure():
    """keyword_argument is pure and handles hyphen, space, extra spaces, and no argument."""
    assert hasattr(text_rules, "keyword_argument")

    # Hyphen spelling
    assert text_rules.keyword_argument("remove-vendor Thorlabs", "remove-vendor") == "Thorlabs"
    assert text_rules.keyword_argument("add-vendor Fisher Scientific", "add-vendor") == "Fisher Scientific"

    # Space spelling
    assert text_rules.keyword_argument("remove vendor Thorlabs", "remove-vendor") == "Thorlabs"
    assert text_rules.keyword_argument("add vendor Fisher Scientific", "add-vendor") == "Fisher Scientific"

    # Extra spaces
    assert text_rules.keyword_argument("  remove   vendor    Thorlabs Inc  ", "remove-vendor") == "Thorlabs Inc"
    assert text_rules.keyword_argument("remove-vendor   Thorlabs Inc  ", "remove-vendor") == "Thorlabs Inc"

    # Keyword with no argument returns ""
    assert text_rules.keyword_argument("remove-vendor", "remove-vendor") == ""
    assert text_rules.keyword_argument("remove vendor", "remove-vendor") == ""
    assert text_rules.keyword_argument("   remove-vendor   ", "remove-vendor") == ""
    assert text_rules.keyword_argument("   remove vendor   ", "remove-vendor") == ""
    assert text_rules.keyword_argument("", "remove-vendor") == ""
    assert text_rules.keyword_argument("   ", "remove-vendor") == ""


# ---------------------------------------------------------------------------
# Criterion 5: Help and App Home show remove-vendor and hyphen-or-space line
# ---------------------------------------------------------------------------
def test_help_and_app_home_hyphen_equals_space():
    """Help text and App Home view text contain 'remove-vendor' and not 'remove vendor <',
    and both contain the verbatim hyphen-or-space rule line.
    """
    help_text = blocks.get_help_message()
    view = blocks.build_app_home_view()

    # Collect App Home text
    parts = []
    for b in view.get("blocks", []):
        txt = b.get("text", {})
        if isinstance(txt, dict):
            parts.append(txt.get("text", ""))
        for el in b.get("elements", []):
            if isinstance(el, dict):
                parts.append(el.get("text", ""))
    app_home_text = "\n".join(parts)

    expected_line = "Two-word commands work with a hyphen or a space: `remove-vendor` = `remove vendor`."

    # Help text assertions
    assert "remove-vendor" in help_text
    assert "remove vendor <" not in help_text
    assert expected_line in help_text, f"Expected line not found in help_text: {expected_line!r}"

    # App Home view assertions
    assert "remove-vendor" in app_home_text
    assert "remove vendor <" not in app_home_text
    assert expected_line in app_home_text, f"Expected line not found in app_home_text: {expected_line!r}"
