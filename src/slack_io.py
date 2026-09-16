"""Slack client I/O helpers and thread/user resolution routines.

WHY THIS EXISTS:
----------------
Wraps Slack API client interactions for finding messages in threads, resolving
user names against roster/Slack profiles, downloading file attachments using
bot authentication, and logging rejections.

Imports:
    - config, epif_parser, interview, roster, text_rules
May NOT import:
    - app.py
    - lifecycle handlers or ops handlers
"""
import logging
import os
import re
from datetime import datetime

import requests

try:
    from . import config, epif_parser, interview, roster
except ImportError:
    import config
    import epif_parser
    import interview
    import roster

log = logging.getLogger("p-bot")


def resolve_requester(client, user_id: str | None) -> str | None:
    """Resolve Slack user ID to the exact name in the Requester Name dropdown."""
    if not user_id:
        return None
    # 1. Check explicit map in roster and config fallback
    requesters_map = roster.get_requesters() if hasattr(roster, "get_requesters") else {}
    if user_id in requesters_map:
        return requesters_map[user_id]
    cfg_map = getattr(config, "SLACK_USER_TO_REQUESTER", {})
    if user_id in cfg_map:
        return cfg_map[user_id]

    # 2. Lookup user profile via Slack API and match against valid requesters
    try:
        res = client.users_info(user=user_id)
        if res.get("ok") and "user" in res:
            user_data = res["user"]
            profile = user_data.get("profile", {})
            candidates = [
                profile.get("display_name", "").strip(),
                profile.get("real_name", "").strip(),
                user_data.get("real_name", "").strip(),
                user_data.get("name", "").strip(),
            ]
            if hasattr(roster, "get_valid_requesters"):
                valid_set = roster.get_valid_requesters()
            else:
                valid_set = getattr(config, "VALID_REQUESTERS", set())
            valid_map = {r.lower(): r for r in valid_set}
            # Try exact match first
            for cand in candidates:
                if cand and cand.lower() in valid_map:
                    return valid_map[cand.lower()]
            # Try first-name match (e.g. "Isaac Legault" -> "Isaac")
            for cand in candidates:
                if not cand:
                    continue
                first_name = cand.split()[0].lower()
                if first_name in valid_map:
                    return valid_map[first_name]
    except Exception as e:
        log.warning("Could not lookup user info for %s: %s", user_id, e)

    return None


def log_rejection(user_id: str | None, filename: str, problems: list, requester_name: str | None = None):
    """Log validation failures cleanly to rejections.log and p_bot.log."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    if requester_name and user_id:
        user_str = f"{requester_name} ({user_id})"
    else:
        user_str = user_id or requester_name or "Unknown User"

    entry = (
        f"[{timestamp}] REJECTION | User: {user_str} | File: {filename}\n"
        + "".join(f"  • {p}\n" for p in problems)
        + "-" * 70 + "\n"
    )

    try:
        with open(config.REJECTIONS_LOG_FILE, "a", encoding="utf-8") as f:
            f.write(entry)
    except Exception as e:
        log.warning("Failed to record rejection log to %s: %s", config.REJECTIONS_LOG_FILE, e)

    log.warning("Form validation failed for '%s' (from %s): %s", filename, user_str, "; ".join(problems))


def find_epif_in_thread(client, channel: str, thread_ts: str):
    """Newest PDF posted in the thread, plus who posted it."""
    replies = client.conversations_replies(channel=channel, ts=thread_ts, limit=200)
    for message in reversed(replies.get("messages", [])):
        for attachment in message.get("files", []):
            name = attachment.get("name", "").lower()
            if name.endswith(".pdf"):
                return attachment, message.get("user")
    return None, None


def find_modal_request_in_thread(client, channel: str, thread_ts: str):
    """Find a modal purchase request posted in the thread if present."""
    try:
        replies = client.conversations_replies(channel=channel, ts=thread_ts, limit=100, include_all_metadata=True)
        for msg in replies.get("messages", []):
            meta = msg.get("metadata", {})
            if meta and meta.get("event_type") == "purchase_request":
                payload = meta.get("event_payload", {})
                parsed = dict(payload.get("parsed", {}))
                if parsed.get("date_of_purchase") and isinstance(parsed["date_of_purchase"], str):
                    parsed["date_of_purchase"] = epif_parser.parse_date(parsed["date_of_purchase"])
                return parsed, payload.get("requester"), payload.get("user_id"), payload.get("is_pending_name", False)

            text = msg.get("text", "")
            if "🛒 *New Purchase Request" in text:
                item_m = re.search(r"•\s*\*Item:\*\s*(.+)", text)
                total_m = re.search(r"•\s*\*Total:\*\s*\$?([0-9,]+(?:\.[0-9]{1,2})?)", text)
                vendor_m = re.search(r"•\s*\*Vendor:\*\s*(.+?)(?:\s*\((.*?)\))?$", text, re.M)
                cat_m = re.search(r"•\s*\*Category:\*\s*(.+)", text)
                proj_m = re.search(r"•\s*\*Project ID / Fund:\*\s*(\S+)\s*\(Fund\s*(\S+)\)", text)
                room_m = re.search(r"•\s*\*Delivery Room:\*\s*(.+)", text)
                purp_m = re.search(r"•\s*\*Purpose:\*\s*([\s\S]+?)(?=\n💡|\n\nReply|$)", text)
                name_m = re.search(r"🛒 \*New Purchase Request from (.+?)(?:\s*\(pending name confirmation\))?:", text)

                if item_m and vendor_m and proj_m:
                    vendor_name = vendor_m.group(1).strip()
                    pay_method = vendor_m.group(2).strip() if vendor_m.group(2) else None
                    is_pending = "(pending name confirmation)" in text
                    requester_name = name_m.group(1).strip() if name_m else None
                    user_match = re.search(r"<@([A-Z0-9]+)>", text)
                    poster_id = user_match.group(1) if user_match else None
                    purpose_str = purp_m.group(1).strip() if purp_m else ""
                    parsed = {
                        "raw_fields": {},
                        "item_description": item_m.group(1).strip(),
                        "purpose": purpose_str,
                        "link": epif_parser.first_url(purpose_str),
                        "total_price": float(total_m.group(1).replace(",", "")) if total_m else None,
                        "total_price_raw": total_m.group(1) if total_m else "",
                        "vendor": vendor_name,
                        "vendor_contact_name": "",
                        "vendor_contact_email": "sales@vendor.com",
                        "date_of_purchase": datetime.now().date(),
                        "name_of_system": "",
                        "delivery_room": room_m.group(1).strip() if room_m else "",
                        "project_id": proj_m.group(1).strip(),
                        "fund": proj_m.group(2).strip(),
                        "asset_id": "",
                        "pi_of_funding": "",
                        "end_user": "",
                        "category": cat_m.group(1).strip() if cat_m else "Research/Lab Supplies (3105)",
                        "category_error": None,
                        "payment_method": (
                            pay_method
                            or ("Workday" if interview.route_vendor(vendor_name) == "workday" else "P-card")
                        ),
                    }
                    return parsed, requester_name, poster_id, is_pending
    except Exception as e:
        log.warning("Could not search thread for modal request: %s", e)
    return None, None, None, False


def find_row_in_thread(client, channel: str, thread_ts: str) -> int | None:
    """Find previously logged row number mentioned in this thread."""
    try:
        replies = client.conversations_replies(channel=channel, ts=thread_ts, limit=100)
        for msg in reversed(replies.get("messages", [])):
            text = msg.get("text", "")
            match = re.search(r"Logged to row\s*(\d+)", text, re.I)
            if match:
                return int(match.group(1))
            match = re.search(r"Row\s*#?\s*(\d+)", text, re.I)
            if match:
                return int(match.group(1))
    except Exception as e:
        log.warning("Could not search thread for row number: %s", e)
    return None


def find_all_rows_in_thread(client, channel: str, thread_ts: str) -> list:
    """Return every logged row number mentioned in this thread.

    Used by handle_cancel to blank all rows a batch request wrote.
    The approval success message contains 'Logged to row N', once per EPIF.
    """
    rows = []
    try:
        replies = client.conversations_replies(channel=channel, ts=thread_ts, limit=100)
        for msg in replies.get("messages", []):
            text = msg.get("text", "")
            for match in re.finditer(r"Logged to row\s*(\d+)", text, re.I):
                row = int(match.group(1))
                if row not in rows:
                    rows.append(row)
    except Exception as e:
        log.warning("Could not search thread for row numbers: %s", e)
    return rows


def download(file_obj) -> bytes:
    """Slack file URLs need the bot token as a bearer header."""
    url = file_obj.get("url_private_download") or file_obj.get("url_private")
    token = os.environ.get("SLACK_BOT_TOKEN")
    try:
        response = requests.get(
            url,
            headers={"Authorization": f"Bearer {token}"},
            timeout=30,
        )
        response.raise_for_status()
    except requests.exceptions.HTTPError as e:
        if response.status_code == 403:
            raise RuntimeError(
                "Slack returned 403 Forbidden while downloading the file. "
                "Ensure 'files:read' is added under OAuth & Permissions -> Bot Token Scopes, "
                "and click 'Reinstall to Workspace' in api.slack.com."
            ) from e
        raise

    if response.content[:4] != b"%PDF":
        # Slack hands back an HTML login page when the scope is missing.
        raise RuntimeError(
            "Slack returned something that isn't a PDF - the bot is probably "
            "missing the files:read scope, or needs to be reinstalled to the workspace."
        )
    return response.content


def download_file(file_obj) -> bytes:
    """Download any file attachment (PDF, screenshot/PNG, image, quote, etc.) from Slack."""
    url = file_obj.get("url_private_download") or file_obj.get("url_private")
    token = os.environ.get("SLACK_BOT_TOKEN")
    try:
        response = requests.get(
            url,
            headers={"Authorization": f"Bearer {token}"},
            timeout=30,
        )
        response.raise_for_status()
    except requests.exceptions.HTTPError:
        if response.status_code == 403:
            raise RuntimeError(
                "Slack returned 403 Forbidden while downloading the file. "
                "Ensure 'files:read' is added under OAuth & Permissions -> Bot Token Scopes, "
                "and click 'Reinstall to Workspace' in api.slack.com."
            )
        raise
    return response.content


def tell(client, user_id: str, text: str):
    client.chat_postMessage(channel=user_id, text=text)
