"""Tests for ticket 09 — refreshed App Home and help text.

Checks:
- The shared constants (_INTERFACE_RULE, _BUTTON_LIST, _STAGE_DEFINITIONS,
  _ADMIN_COMMANDS) appear byte-for-byte in both rendered surfaces (drift guard).
- Neither surface contains 'Claim' or '@p-bot'.
- Both surfaces show the approve-and-mention example in both mention orders.
- Both surfaces explain that a forgotten mention still leaves the request approved
  and how a buyer takes an unassigned request.
- Both surfaces list 'add-buyer' and 'remove-buyer'.
- Both surfaces carry the four stage words plus the 'Assigned isn't a stage' line.
- No link to the Purchasing Log (ADR 0002 decision 9).
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import blocks as blocks_mod


def _app_home_text() -> str:
    """Collect all mrkdwn text strings from the App Home view into one string."""
    view = blocks_mod.build_app_home_view()
    parts = []
    for block in view["blocks"]:
        txt = block.get("text", {})
        if isinstance(txt, dict):
            parts.append(txt.get("text", ""))
        for el in block.get("elements", []):
            if isinstance(el, dict):
                parts.append(el.get("text", ""))
    return "\n".join(parts)


def _help_text() -> str:
    return blocks_mod.get_help_message()


# ---------------------------------------------------------------------------
# Drift guard: shared constants must appear verbatim in both surfaces
# ---------------------------------------------------------------------------

def test_interface_rule_identical_in_both():
    home = _app_home_text()
    help_ = _help_text()
    rule = blocks_mod._INTERFACE_RULE
    assert rule in home, "Interface rule missing from App Home"
    assert rule in help_, "Interface rule missing from help message"


def test_button_list_identical_in_both():
    home = _app_home_text()
    help_ = _help_text()
    bl = blocks_mod._BUTTON_LIST
    assert bl in home, "Button list missing from App Home"
    assert bl in help_, "Button list missing from help message"


def test_stage_definitions_identical_in_both():
    home = _app_home_text()
    help_ = _help_text()
    sd = blocks_mod._STAGE_DEFINITIONS
    assert sd in home, "Stage definitions missing from App Home"
    assert sd in help_, "Stage definitions missing from help message"


def test_admin_commands_identical_in_both():
    home = _app_home_text()
    help_ = _help_text()
    ac = blocks_mod._ADMIN_COMMANDS
    assert ac in home, "Admin commands missing from App Home"
    assert ac in help_, "Admin commands missing from help message"


# ---------------------------------------------------------------------------
# 'Claim' must not appear in either surface
# ---------------------------------------------------------------------------

def test_no_claim_in_app_home():
    home = _app_home_text()
    assert "Claim" not in home, "Found 'Claim' in App Home"
    assert "claim" not in home, "Found 'claim' in App Home"


def test_no_claim_in_help():
    help_ = _help_text()
    assert "Claim" not in help_, "Found 'Claim' in help message"
    assert "claim" not in help_, "Found 'claim' in help message"


# ---------------------------------------------------------------------------
# '@p-bot' must not appear in either surface
# ---------------------------------------------------------------------------

def test_no_p_bot_in_app_home():
    home = _app_home_text()
    assert "@p-bot" not in home, "Found '@p-bot' in App Home"


def test_no_p_bot_in_help():
    help_ = _help_text()
    assert "@p-bot" not in help_, "Found '@p-bot' in help message"


# ---------------------------------------------------------------------------
# Approval+assignment example shown in both mention orders
# ---------------------------------------------------------------------------

def test_approval_example_both_orders_in_app_home():
    home = _app_home_text()
    assert "@Dylan @Purchasing approved" in home, "First mention order missing from App Home"
    assert "@Purchasing approved @Dylan" in home, "Second mention order missing from App Home"


def test_approval_example_both_orders_in_help():
    help_ = _help_text()
    assert "@Dylan @Purchasing approved" in help_, "First mention order missing from help message"
    assert "@Purchasing approved @Dylan" in help_, "Second mention order missing from help message"


# ---------------------------------------------------------------------------
# Forgotten-mention fallback: still approved, buyer can take it
# ---------------------------------------------------------------------------

def test_forgotten_mention_and_assign_fallback_in_app_home():
    home = _app_home_text()
    assert "still approved" in home, "Forgotten-mention note missing from App Home"
    assert "@Purchasing assign" in home, "Assign keyword missing from App Home"


def test_forgotten_mention_and_assign_fallback_in_help():
    help_ = _help_text()
    assert "still approved" in help_, "Forgotten-mention note missing from help message"
    assert "@Purchasing assign" in help_, "Assign keyword missing from help message"


# ---------------------------------------------------------------------------
# add-buyer and remove-buyer listed in both surfaces
# ---------------------------------------------------------------------------

def test_add_buyer_in_app_home():
    assert "add-buyer" in _app_home_text()


def test_remove_buyer_in_app_home():
    assert "remove-buyer" in _app_home_text()


def test_add_buyer_in_help():
    assert "add-buyer" in _help_text()


def test_remove_buyer_in_help():
    assert "remove-buyer" in _help_text()


# ---------------------------------------------------------------------------
# Four stages present, with 'Assigned isn't a stage' line
# ---------------------------------------------------------------------------

def test_four_stages_in_app_home():
    home = _app_home_text()
    for stage in ("Approved", "Processed", "Confirmed", "Delivered"):
        assert stage in home, f"Stage '{stage}' missing from App Home"


def test_four_stages_in_help():
    help_ = _help_text()
    for stage in ("Approved", "Processed", "Confirmed", "Delivered"):
        assert stage in help_, f"Stage '{stage}' missing from help message"


def test_assigned_not_a_stage_in_app_home():
    assert "Assigned isn't a stage" in _app_home_text()


def test_assigned_not_a_stage_in_help():
    assert "Assigned isn't a stage" in _help_text()


# ---------------------------------------------------------------------------
# No link to Purchasing Log (ADR 0002 decision 9)
# ---------------------------------------------------------------------------

def test_no_purchasing_log_link_in_app_home():
    home = _app_home_text()
    assert "Purchasing-Log.xlsx" not in home or "http" not in home, \
        "App Home must not link to Purchasing Log"


def test_no_purchasing_log_link_in_help():
    help_ = _help_text()
    # The log file name may appear in troubleshooting text but must not be a hyperlink
    assert "http" not in help_, "Help message must not contain URLs"
