"""Slack client I/O helpers and thread/user resolution routines.

WHY THIS EXISTS:
----------------
Wraps Slack API client interactions for finding messages in threads, resolving
user names against roster/Slack profiles, downloading file attachments using
bot authentication, and logging rejections.

Ticket 12 adds `deny()`: in Slack Bolt, calling respond(text=...) from a block action
listener defaults to replacing the message the button was clicked on. When an
unauthorized user clicked Approve or another stage button, the purchase request card
disappeared from the channel, replaced by a padlock error visible only to that user.
`deny()` ensures all permission refusals and informational responses use
response_type="ephemeral" and replace_original=False, leaving the request card intact.

Ticket 14:
Deletes the regex-based prose parsing branch that scraped bot summary text and
invented dummy vendor emails. Replaces thread modal search with
find_request_metadata_in_thread to read structured Slack message metadata only.
Narrows find_row_in_thread to match only 'Logged to row N', preventing false
matches on bare row numbers or fund/price numbers in human conversation.

Ticket 27:
Adds get_card_payload to fetch the metadata payload of the exact card message at
card_ts, supporting multi-card threads without falling back to newest card.

Ticket 51:
Clarifies that `deny()` is for slash commands and block actions only, never for
the `app_mention` / `message` event path. Bolt puts a `respond` object in event
contexts, but invoking it raises `ValueError` because events have no `response_url`.
Event replies must always use `say()` in-thread.

Ticket 65:
Adds `alert_admins(client, text)`: posts card or processing failure alerts to
config.ADMIN_ALERT_CHANNEL. Never raises: returns False and logs a WARNING when
the channel is unset, client is None, or chat_postMessage raises.

Ticket 67:
Adds `post_dm_card(client, user_id, text, blocks)`: posts a DM card to a user ID
and returns `(dm_channel, dm_ts)` or `None` on failure.

Ticket 68:
Adds `get_card_by_ts(client, channel, thread_ts, card_ts)`: fetches a card message in a
thread by its timestamp and reads (request, history, state) from the actions button value,
never from message metadata. Used by DM card stage actions to read thread state.

Ticket 100 / ADR 0015 Decisions 2 and 4:
Adds `bot_user_id(client)`: resolves and caches the bot's own Slack user ID.
Adds `classify_thread_files(messages, bot_user_id, read_fields)`: purely classifies
thread file attachments by role (epifs, boms, quotes, flattened_epifs).
Updates `find_epif_in_thread(client, channel, thread_ts)` to use classify_thread_files,
returning the newest real EPIF, or the newest flattened EPIF so the existing error can
reach the uploader, or (None, None).

Imports:
    - config, epif_parser, roster, text_rules
May NOT import:
    - app.py
    - lifecycle handlers or ops handlers
"""
import json
import logging
import os
import re
from datetime import datetime
from typing import Callable

import requests

try:
    from . import config, epif_parser, roster
except ImportError:
    import config
    import epif_parser
    import roster

log = logging.getLogger("p-bot")

_CACHED_BOT_USER_ID: str | None = None


def bot_user_id(client) -> str | None:
    """Resolve and cache the bot's own Slack user ID.

    WHY THIS EXISTS:
    Ticket 100 / ADR 0015 Decision 4: Centralized bot user ID lookup cached across
    calls so that find_epif_in_thread and classify_thread_files can reliably identify
    and skip messages authored by the bot itself without repeated Slack auth_test calls.
    """
    global _CACHED_BOT_USER_ID
    if _CACHED_BOT_USER_ID:
        return _CACHED_BOT_USER_ID
    if client:
        try:
            auth = client.auth_test()
            if isinstance(auth, dict) and auth.get("user_id"):
                _CACHED_BOT_USER_ID = str(auth.get("user_id"))
                return _CACHED_BOT_USER_ID
        except Exception as e:
            log.warning("Failed to get bot_user_id from auth_test: %s", e)
    return None


def deny(respond, text: str) -> None:
    """Reply privately to whoever acted, leaving the original message intact.

    NOTE: For slash commands and block actions ONLY, never for app_mention or message
    event paths. Bolt provides a respond callable in event contexts, but calling it raises
    ValueError because event payloads do not contain a response_url. Event replies must
    always use say() in the thread.
    """
    respond(text=text, response_type="ephemeral", replace_original=False)


def alert_admins(client, text: str) -> bool:
    """Post an alert message to config.ADMIN_ALERT_CHANNEL.

    WHY THIS EXISTS:
    ----------------
    ADR 0010 decision 7: A missing card or a failed drop must be reported loudly
    in the admin alert channel so an admin can investigate immediately.
    Never raises: returns False and logs a WARNING if channel is unset, client is
    None, or client.chat_postMessage raises.
    """
    channel = getattr(config, "ADMIN_ALERT_CHANNEL", "")
    if not channel:
        log.warning("Admin alert not posted: ADMIN_ALERT_CHANNEL is unset")
        return False
    if client is None:
        log.warning("Admin alert not posted: client is None")
        return False
    try:
        client.chat_postMessage(channel=channel, text=text)
        return True
    except Exception as e:
        log.warning("Failed to post admin alert to %s: %s", channel, e)
        return False


def post_dm_card(client, user_id: str, text: str, blocks: list) -> tuple[str, str] | None:
    """Post a DM card to a user and return (channel_id, ts) or None on failure.

    WHY THIS EXISTS:
    ----------------
    ADR 0010 decision 2 & Ticket 67:
    The assigned buyer's DM carries a card with next-step buttons. Slack's chat.postMessage
    accepts a user ID as the channel parameter and returns the opened DM channel ID along
    with the message timestamp.
    """
    try:
        resp = client.chat_postMessage(channel=user_id, text=text, blocks=blocks)
        return (resp["channel"], resp["ts"])
    except Exception as e:
        log.warning("Failed to post DM card to user %s: %s", user_id, e)
        return None



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
                valid_set = set()
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


def classify_thread_files(
    messages: list[dict],
    bot_user_id: str | None,
    read_fields: Callable[[dict], dict],
) -> dict[str, list[dict]]:
    """Classify thread attachments into epifs, boms, quotes, and flattened_epifs.

    WHY THIS EXISTS:
    Ticket 100 / ADR 0015 Decisions 2 and 4: Classifies files posted in a thread purely
    without a Slack client. Non-EPIF PDFs (quotes, invoices, W-9s) and bot-posted files
    are never parsed as EPIFs, and quotes uploaded via @Purchasing quote are not saved twice.
    """
    result: dict[str, list[dict]] = {
        "epifs": [],
        "boms": [],
        "quotes": [],
        "flattened_epifs": [],
    }

    def _msg_ts(m: dict) -> float:
        try:
            return float(m.get("ts") or 0)
        except (ValueError, TypeError):
            return 0.0

    sorted_messages = sorted(messages or [], key=_msg_ts)

    for msg in sorted_messages:
        # Rule 1: Skip if user == bot_user_id or it has a bot_id
        if (bot_user_id and msg.get("user") == bot_user_id) or msg.get("bot_id"):
            continue

        # Rule 2: Skip if it is an @Purchasing quote command
        text = msg.get("text") or ""
        if bot_user_id and f"<@{bot_user_id}>" in text:
            remainder = text.replace(f"<@{bot_user_id}>", "").strip().lower()
            if remainder.startswith(tuple(config.QUOTE_KEYWORDS)):
                continue

        # Process each file of the message
        files = msg.get("files") or []
        for file_obj in files:
            name = (file_obj.get("name") or "").lower()
            if name.endswith((".xlsx", ".csv")):
                result["boms"].append({
                    "file": file_obj,
                    "user": msg.get("user"),
                    "ts": msg.get("ts"),
                })
            elif name.endswith(".pdf"):
                try:
                    fields = read_fields(file_obj)
                except epif_parser.FlattenedPdfError:
                    fields = {}
                except Exception as e:
                    log.warning("Could not read fields for %s: %s", file_obj.get("name"), e)
                    fields = {}

                if epif_parser.is_epif_form(fields):
                    result["epifs"].append({
                        "file": file_obj,
                        "user": msg.get("user"),
                        "ts": msg.get("ts"),
                    })
                elif not fields and "epif" in name:
                    result["flattened_epifs"].append({
                        "file": file_obj,
                        "user": msg.get("user"),
                        "ts": msg.get("ts"),
                    })
                else:
                    result["quotes"].append({
                        "file": file_obj,
                        "user": msg.get("user"),
                        "ts": msg.get("ts"),
                    })
            else:
                # Anything else (images, etc.) is skipped
                continue

    return result


def find_epif_in_thread(client, channel: str, thread_ts: str):
    """Find the newest EPIF in the thread, returning (file_obj, poster).

    WHY THIS EXISTS:
    Ticket 100 / ADR 0015 Decision 2: Classifies thread attachments using
    classify_thread_files. Returns the newest real EPIF, or the newest flattened
    EPIF so the existing flattened-PDF error can still reach the uploader, or (None, None).
    """
    try:
        replies = client.conversations_replies(channel=channel, ts=thread_ts, limit=200)
        messages = replies.get("messages", [])
    except Exception as e:
        log.warning("Could not fetch replies for thread %s in %s: %s", thread_ts, channel, e)
        return None, None

    def _read_fields(file_obj: dict) -> dict:
        try:
            pdf_bytes = download(file_obj)
            return epif_parser.read_fields(pdf_bytes)
        except epif_parser.FlattenedPdfError:
            return {}
        except Exception as e:
            log.warning("Could not read fields for %s: %s", file_obj.get("name"), e)
            return {}

    b_id = bot_user_id(client)
    classified = classify_thread_files(messages, b_id, _read_fields)

    if classified.get("epifs"):
        newest = classified["epifs"][-1]
        return newest["file"], newest["user"]
    if classified.get("flattened_epifs"):
        newest = classified["flattened_epifs"][-1]
        return newest["file"], newest["user"]
    return None, None


def find_request_metadata_in_thread(client, channel: str, thread_ts: str):
    """Find a purchase request posted via Slack metadata in the thread if present."""
    try:
        replies = client.conversations_replies(channel=channel, ts=thread_ts, limit=100, include_all_metadata=True)
        for msg in replies.get("messages", []):
            meta = msg.get("metadata", {})
            if meta and meta.get("event_type") == "purchase_request":
                payload = meta.get("event_payload", {})
                parsed = dict(payload.get("parsed", {}))
                if parsed.get("date_of_purchase") and isinstance(parsed["date_of_purchase"], str):
                    parsed["date_of_purchase"] = epif_parser.parse_date(parsed["date_of_purchase"])
                if payload.get("items"):
                    parsed["items"] = payload.get("items")
                if "shipping" in payload:
                    parsed["shipping"] = payload.get("shipping")
                return parsed, payload.get("requester"), payload.get("user_id"), payload.get("is_pending_name", False)
    except Exception as e:
        log.warning("Could not search thread for modal request metadata: %s", e)
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


def _parse_card_button_value(msg: dict) -> tuple[dict, list, str] | None:
    """Extract (request, history, state) from the actions-block button value of a message.

    Returns None if the message has no actions button or the value lacks state.
    Never reads message metadata — the button value is the store.
    """
    for b in msg.get("blocks", []):
        if b.get("type") == "actions":
            for elem in b.get("elements", []):
                val_str = elem.get("value")
                if val_str:
                    try:
                        val_data = json.loads(val_str)
                        if isinstance(val_data, dict) and "state" in val_data:
                            return (
                                val_data.get("request", {}),
                                val_data.get("history", []),
                                val_data.get("state"),
                            )
                    except Exception:
                        pass
    return None


def find_card_in_thread(client, channel: str, thread_ts: str) -> tuple[dict | None, str | None, list, str | None]:
    """Find request card message in thread.

    Returns (req_data, msg_ts, history, current_state).
    """
    try:
        replies = client.conversations_replies(channel=channel, ts=thread_ts, limit=100, include_all_metadata=True)
        for msg in reversed(replies.get("messages", [])):
            parsed = _parse_card_button_value(msg)
            if parsed is not None:
                req_data, history, state = parsed
                return req_data, msg.get("ts"), history, state
            meta = msg.get("metadata", {})
            if meta and meta.get("event_type") == "purchase_request":
                payload = meta.get("event_payload", {})
                return (payload, msg.get("ts"), [], "posted")
    except Exception as e:
        log.warning("Could not search thread for card message: %s", e)
    return None, None, [], None


def get_card_by_ts(client, channel: str, thread_ts: str, card_ts: str) -> tuple[dict, list, str] | None:
    """Find a card message in thread by card_ts and read (request, history, state) from button value.

    WHY THIS EXISTS:
    ----------------
    ADR 0010 decision 2 & Ticket 68:
    The DM card is only a view with a pointer to the thread card. Every click on the DM card
    must read the thread card to learn the true state. Never read message metadata for state —
    the button value is the store. Returns None when the message is not found or has no actions button.
    """
    target_ts = str(card_ts)
    try:
        replies = client.conversations_replies(channel=channel, ts=thread_ts, limit=100)
        for msg in replies.get("messages", []):
            if str(msg.get("ts")) == target_ts:
                return _parse_card_button_value(msg)
    except Exception as e:
        log.warning("Could not fetch card by ts %s in thread %s: %s", card_ts, thread_ts, e)
    return None


def get_card_payload(client, channel: str, thread_ts: str | None, card_ts: str) -> dict | None:
    """Fetch the metadata event_payload of the exact card message at card_ts."""
    target_ts = str(card_ts)
    search_ts = str(thread_ts) if thread_ts else target_ts
    try:
        replies = client.conversations_replies(
            channel=channel,
            ts=search_ts,
            limit=100,
            include_all_metadata=True,
        )
        for msg in replies.get("messages", []):
            if str(msg.get("ts")) == target_ts:
                meta = msg.get("metadata", {})
                if meta and meta.get("event_type") == "purchase_request":
                    payload = dict(meta.get("event_payload") or {})
                    # Also attach state and history from button value if not already in payload
                    for b in msg.get("blocks", []):
                        if b.get("type") == "actions":
                            for elem in b.get("elements", []):
                                val_str = elem.get("value")
                                if val_str:
                                    try:
                                        val_data = json.loads(val_str)
                                        if isinstance(val_data, dict):
                                            if "state" not in payload and "state" in val_data:
                                                payload["state"] = val_data["state"]
                                            if "history" not in payload and "history" in val_data:
                                                payload["history"] = val_data["history"]
                                    except Exception:
                                        pass
                    if "parsed" in payload and isinstance(payload["parsed"], dict):
                        parsed = dict(payload["parsed"])
                        if parsed.get("date_of_purchase") and isinstance(parsed["date_of_purchase"], str):
                            parsed["date_of_purchase"] = epif_parser.parse_date(parsed["date_of_purchase"])
                        payload["parsed"] = parsed
                    return payload
    except Exception as e:
        log.warning("Could not fetch card payload for ts %s in channel %s: %s", card_ts, channel, e)
    return None


def find_posted_cards_in_thread(
    client, channel: str, thread_ts: str, user_id: str, vendor: str,
) -> list:
    """Find all posted purchase request cards in the thread from the same requester and vendor.

    Returns a list of (msg_ts, req_payload, history) for every card whose state is
    'posted', whose user_id matches, and whose vendor matches (case-insensitively,
    whitespace-trimmed). Used by handle_epif_drop to supersede stale posted cards
    when a corrected EPIF is uploaded to the same thread (ADR 0006 decision 9).

    WHY THIS EXISTS:
        Dropping a corrected EPIF into a thread today leaves two approvable cards.
        This scanner finds only 'posted' matches so that an approved or later card
        is never touched — a real purchase must not be hidden by a stray upload.
    """
    vendor_norm = vendor.strip().lower()
    results = []
    try:
        replies = client.conversations_replies(
            channel=channel, ts=thread_ts, limit=100, include_all_metadata=True
        )
        for msg in replies.get("messages", []):
            msg_ts = msg.get("ts")
            state = None
            card_req = None
            history = []

            # Read state and request from the first button value found.
            for blk in msg.get("blocks", []):
                if blk.get("type") == "actions":
                    for elem in blk.get("elements", []):
                        val_str = elem.get("value")
                        if val_str:
                            try:
                                val_data = json.loads(val_str)
                                if isinstance(val_data, dict) and "state" in val_data:
                                    state = val_data["state"]
                                    card_req = val_data.get("request", {})
                                    history = val_data.get("history", [])
                            except Exception:
                                pass
                    if state is not None:
                        break

            # Only a card whose button value explicitly says state=="posted" qualifies.
            # A card in any terminal state (delivered, declined, cancelled) has no
            # buttons and therefore no button value — do not assume "posted" from
            # metadata alone.
            if state != "posted":
                continue

            # Prefer the full metadata payload (includes user_id, items, parsed).
            meta = msg.get("metadata", {})
            if meta and meta.get("event_type") == "purchase_request":
                card_req = meta.get("event_payload", {})

            if card_req is None:
                continue

            if card_req.get("user_id") != user_id:
                continue

            card_vendor = (card_req.get("parsed", {}).get("vendor") or "").strip().lower()
            if card_vendor != vendor_norm:
                continue

            results.append((msg_ts, card_req, list(history)))
    except Exception as e:
        log.warning("Could not scan thread for posted cards: %s", e)
    return results



def get_thread_parent_author(client, channel: str, thread_ts: str) -> str | None:
    """Find the author (user_id) of the thread's parent message."""
    try:
        replies = client.conversations_replies(channel=channel, ts=thread_ts, limit=1)
        messages = replies.get("messages", [])
        if messages:
            return messages[0].get("user")
    except Exception as e:
        log.warning("Could not fetch thread parent author for ts %s in channel %s: %s", thread_ts, channel, e)
    return None
