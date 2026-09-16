"""Pure text parsing, extracting, and templating rules.

WHY THIS EXISTS:
----------------
This is the lowest pure domain layer for string operations, formatting, regex
matching, and email generation. It has no Slack dependencies, makes no network
or I/O calls, and contains no state.

Imports:
    - config (only)
May NOT import:
    - Slack SDK / Bolt
    - storage modules (log_writer, queue_worker, roster, etc.)
    - handlers or listeners
"""
import re

try:
    from . import config
except ImportError:
    import config


def extract_request_info(body: dict) -> tuple[str, str, str | None, str | None, bool]:
    """Extract (kind, identifier, user_id, channel_id, is_verbose_msg) from Slack Bolt request body."""
    if not isinstance(body, dict):
        return "unknown", "unknown", None, None, False

    # 1. Slash commands
    if "command" in body:
        return "command", body.get("command", ""), body.get("user_id"), body.get("channel_id"), False

    # 2. Block actions (interactive button clicks, select menus)
    if body.get("type") == "block_actions":
        actions = body.get("actions", [])
        act_id = actions[0].get("action_id", "unknown_action") if actions else "no_action"
        user_id = body.get("user", {}).get("id")
        channel_id = body.get("channel", {}).get("id")
        return "block_actions", act_id, user_id, channel_id, False

    # 3. View submission (modal submit)
    if body.get("type") == "view_submission":
        cb_id = body.get("view", {}).get("callback_id", "unknown_callback")
        user_id = body.get("user", {}).get("id")
        return "view_submission", cb_id, user_id, None, False

    # 4. View closed (modal cancel)
    if body.get("type") == "view_closed":
        cb_id = body.get("view", {}).get("callback_id", "unknown_callback")
        user_id = body.get("user", {}).get("id")
        return "view_closed", cb_id, user_id, None, False

    # 5. Events (app_mention, message, app_home_opened, etc.)
    if body.get("type") == "event_callback":
        ev = body.get("event", {})
        ev_type = ev.get("type", "unknown_event")
        user_id = ev.get("user")
        channel_id = ev.get("channel")
        is_verbose = (ev_type == "message" and (ev.get("channel_type") != "im" or ev.get("subtype") == "bot_message"))
        return "event", ev_type, user_id, channel_id, is_verbose

    # 6. Shortcuts
    if body.get("type") in ("shortcut", "message_action"):
        cb_id = body.get("callback_id", "unknown_shortcut")
        user_id = body.get("user", {}).get("id")
        channel_id = body.get("channel", {}).get("id")
        return "shortcut", cb_id, user_id, channel_id, False

    # Fallback
    b_type = body.get("type", "unknown")
    user_id = body.get("user_id") or body.get("user", {}).get("id")
    channel_id = body.get("channel_id") or body.get("channel", {}).get("id")
    return b_type, b_type, user_id, channel_id, False


def extract_row_from_text(text: str) -> int | None:
    """Extract explicit row number from message text (e.g. 'row 17', '#17')."""
    match = re.search(r"row\s*#?\s*(\d+)", text, re.I)
    if match:
        return int(match.group(1))
    match = re.search(r"\b(\d{2,4})\b", text)
    if match:
        val = int(match.group(1))
        if config.FIRST_DATA_ROW <= val <= config.LAST_DATA_ROW:
            return val
    return None


def extract_price_from_text(text: str) -> float | None:
    """Extract dollar amount or updated price from message text (e.g. '$152.49', '152.49')."""
    match = re.search(r"\$\s*([0-9]{1,3}(?:,[0-9]{3})*(?:\.[0-9]{1,2})?|[0-9]+(?:\.[0-9]{1,2})?)", text)
    if match:
        val_str = match.group(1).replace(",", "")
        try:
            return float(val_str)
        except ValueError:
            pass
    match = re.search(r"(?:price|total|for|amount)\s*(?:of|is|:)?\s*\$?([0-9]+(?:\.[0-9]{1,2})?)", text, re.I)
    if match:
        try:
            return float(match.group(1))
        except ValueError:
            pass
    return None


def _extract_modal_field(values: dict, block_id: str, action_id: str, field_type: str = "value"):
    """Safely extract field value from Slack modal state values dict."""
    block = values.get(block_id)
    if not isinstance(block, dict):
        return None
    action = block.get(action_id)
    if isinstance(action, dict):
        if field_type == "selected_option":
            opt = action.get("selected_option")
            return opt.get("value") if isinstance(opt, dict) else opt
        elif field_type == "selected_date":
            return action.get("selected_date")
        else:
            return action.get("value")
    return action


def generate_email_draft(parsed: dict, requester_name: str) -> str:
    """Generate a pre-filled email draft matching the lab's purchasing request format."""
    vendor = parsed.get("vendor") or "Vendor"
    amount = parsed.get("total_price")
    amount_str = f"${amount:,.2f}" if amount is not None else "the specified amount"
    project_id = parsed.get("project_id") or "PG000025831"
    fund = parsed.get("fund")
    fund_str = f" (Fund {fund})" if fund else ""
    link = parsed.get("link") or "[Link to product / cart]"
    item = parsed.get("item_description") or "supplies"

    return (
        f"Subject: Hirst Lab purchase request - {vendor} - {item}\n\n"
        f"Hello Tina and Ally,\n\n"
        f"We would like to make a purchase from {vendor} for {amount_str} under project ID {project_id}{fund_str}.\n"
        f"Attached is the filled out EPIF and the link to the website:\n"
        f"{link}\n\n"
        f"Please let me know if you have any questions or edits that need to be made.\n\n"
        f"All the best,\n"
        f"{requester_name}"
    )
