"""Tests for Ticket 22: A live roster panel on App Home.

Acceptance criteria:
- build_app_home_view(user_id) for a registered user shows that user's name — asserted on the specific name, not on block count
- For an unregistered user it shows the registration prompt, and that prompt appears above the static command content
- The panel shows the roles the user holds, and shows them correctly for a user holding all three and for a user holding none
- The panel's button opens the ticket-19 modal — asserted on the action_id / callback, not on a screenshot
- remove-member appears in both build_app_home_view() and get_help_message(), and a test asserts the shared constant is the only place it is written
- build_app_home_view makes no Slack API call and holds no client
- The existing drift test still passes and now covers the changed commands
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
            "requesters": {
                "U_REG_PLAIN": "David Plain",
                "U_REG_ALL": "Alice AllRoles",
                "U_ISAAC": "Isaac",
            },
            "admins": ["U_REG_ALL"],
            "approvers": ["U_REG_ALL"],
            "buyers": ["U_REG_ALL"],
            "vendors": [],
        }, f)
    monkeypatch.setattr(roster, "ROSTER_PATH", roster_path)
    monkeypatch.setattr(config, "ADMIN_ALERT_CHANNEL", "C_ALERTS")
    return roster_path


def _extract_all_text(view: dict) -> str:
    """Extract all text strings from a Block Kit view dict."""
    parts = []
    for b in view.get("blocks", []):
        txt = b.get("text", {})
        if isinstance(txt, dict):
            parts.append(txt.get("text", ""))
        for el in b.get("elements", []):
            if isinstance(el, dict):
                parts.append(el.get("text", ""))
    return "\n".join(parts)


# 1. Registered user shows user's name
def test_build_app_home_view_registered_user_shows_name():
    """build_app_home_view(user_id) for a registered user shows that user's name."""
    view = blocks.build_app_home_view(user_id="U_REG_PLAIN")
    text = _extract_all_text(view)
    assert "David Plain" in text, "Expected registered user's name 'David Plain' in App Home view"


# 2. Unregistered user shows registration prompt above static content
def test_build_app_home_view_unregistered_user_shows_prompt_above_static_content():
    """Unregistered user sees registration prompt, placed above static command content."""
    view = blocks.build_app_home_view(user_id="U_UNKNOWN")
    blocks_list = view.get("blocks", [])

    prompt_idx = None
    static_cmd_idx = None

    for i, b in enumerate(blocks_list):
        b_str = json.dumps(b)
        if "not registered" in b_str.lower() or "register" in b_str.lower():
            if prompt_idx is None:
                prompt_idx = i
        if "start something" in b_str.lower() or "slash commands" in b_str.lower() or "/new-purchase" in b_str:
            if static_cmd_idx is None:
                static_cmd_idx = i

    assert prompt_idx is not None, "Registration prompt missing for unregistered user"
    assert static_cmd_idx is not None, "Static command content section missing"
    assert prompt_idx < static_cmd_idx, (
        f"Registration prompt (block {prompt_idx}) must appear above static command content (block {static_cmd_idx})"
    )


# 3. Roles shown correctly: all three roles vs none
def test_build_app_home_view_roles_all_three():
    """Panel shows Admin, Approver, and Buyer when user holds all three roles."""
    view = blocks.build_app_home_view(user_id="U_REG_ALL")
    text = _extract_all_text(view)
    assert "Alice AllRoles" in text
    assert "Admin" in text, "Expected Admin role listed"
    assert "Approver" in text, "Expected Approver role listed"
    assert "Buyer" in text, "Expected Buyer role listed"


def test_build_app_home_view_roles_none():
    """Panel shows 'None' when user holds no roles."""
    view = blocks.build_app_home_view(user_id="U_REG_PLAIN")
    text = _extract_all_text(view)
    assert "David Plain" in text

    # Locate the block with roles
    found_role_line = False
    for line in text.splitlines():
        if "Roles:" in line or "roles:" in line.lower():
            found_role_line = True
            assert "None" in line, f"Expected 'None' for user with no roles, got: {line}"
            assert "Admin" not in line
            assert "Approver" not in line
            assert "Buyer" not in line
    assert found_role_line, "Roles line not found in App Home panel"


# 4. Panel button opens ticket-19 modal
def test_build_app_home_view_has_roster_set_name_button():
    """Panel has an action button with action_id opening the roster modal."""
    action_id = getattr(config, "ACTION_OPEN_ROSTER_SET_NAME", "open_roster_set_name")

    # Registered user
    view_reg = blocks.build_app_home_view(user_id="U_REG_PLAIN")
    btn_reg = None
    for b in view_reg.get("blocks", []):
        acc = b.get("accessory", {})
        if acc.get("action_id") == action_id:
            btn_reg = acc
            break
        for el in b.get("elements", []):
            if el.get("action_id") == action_id:
                btn_reg = el
                break
    assert btn_reg is not None, f"Button with action_id '{action_id}' missing for registered user"

    # Unregistered user
    view_unreg = blocks.build_app_home_view(user_id="U_UNREG")
    btn_unreg = None
    for b in view_unreg.get("blocks", []):
        acc = b.get("accessory", {})
        if acc.get("action_id") == action_id:
            btn_unreg = acc
            break
        for el in b.get("elements", []):
            if el.get("action_id") == action_id:
                btn_unreg = el
                break
    assert btn_unreg is not None, f"Button with action_id '{action_id}' missing for unregistered user"


def test_handle_open_roster_set_name_action_opens_modal():
    """Clicking the panel button opens the ticket-19 /roster-set-name modal."""
    ack = MagicMock()
    client = MagicMock()
    body = {
        "user": {"id": "U_ISAAC"},
        "trigger_id": "trig_test_123",
    }

    # Find the registered handler function for ACTION_OPEN_ROSTER_SET_NAME
    action_id = getattr(config, "ACTION_OPEN_ROSTER_SET_NAME", "open_roster_set_name")
    handler = None
    # Check if app has action registered or if function exists in app module
    for func_name in ("handle_open_roster_set_name_action", "handle_open_roster_set_name"):
        if hasattr(app, func_name):
            handler = getattr(app, func_name)
            break

    assert handler is not None, f"Handler for {action_id} not found in app.py"

    handler(ack=ack, body=body, client=client)
    ack.assert_called_once()
    client.views_open.assert_called_once()

    call_kwargs = client.views_open.call_args[1]
    assert call_kwargs["trigger_id"] == "trig_test_123"
    modal = call_kwargs["view"]
    assert modal["type"] == "modal"
    assert modal["callback_id"] == config.ROSTER_SET_NAME_CALLBACK_ID
    assert "Isaac" in json.dumps(modal)


# 5. App home view makes no Slack API calls and holds no client
def test_build_app_home_view_pure_no_slack_calls():
    """build_app_home_view takes only user_id, holds no client, and makes no API calls."""
    import inspect
    sig = inspect.signature(blocks.build_app_home_view)
    params = list(sig.parameters.keys())
    assert "client" not in params, "build_app_home_view must not take a Slack client parameter"

    # AST scan to verify no client or network calls inside build_app_home_view
    blocks_file = os.path.join(SRC_DIR, "blocks.py")
    with open(blocks_file, "r", encoding="utf-8") as f:
        tree = ast.parse(f.read(), filename=blocks_file)

    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "build_app_home_view":
            for sub in ast.walk(node):
                if isinstance(sub, ast.Attribute):
                    assert sub.attr not in (
                        "views_open", "views_publish", "chat_postMessage",
                        "chat_postEphemeral", "chat_update",
                    ), f"Forbidden Slack client call '{sub.attr}' in build_app_home_view"


# 6. handle_app_home_opened event listener passes user_id
def test_handle_app_home_opened_passes_user_id():
    """handle_app_home_opened passes event user_id to build_app_home_view and publishes."""
    client = MagicMock()
    event = {"user": "U_ISAAC"}

    app.handle_app_home_opened(client=client, event=event)
    client.views_publish.assert_called_once()
    call_kwargs = client.views_publish.call_args[1]
    assert call_kwargs["user_id"] == "U_ISAAC"
    view = call_kwargs["view"]
    assert view["type"] == "home"
    assert "Isaac" in _extract_all_text(view)
