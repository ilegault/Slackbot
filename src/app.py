"""The Slack side. Everything here is plumbing - the thinking is in the other files.

Flow of operations:

    1. Approval & Logging:
       Someone posts an EPIF pdf in #hirst-lab or a DM
         -> Charlie replies in that thread: "@p-bot approved" (or DMs the bot)
         -> Bot parses & validates EPIF, saves PDF to EPIFs/, logs row in Purchasing-Log.xlsx (via Lock Queue).
         -> If requester is an undergrad, bot pings grad students in thread to claim the purchase.
         -> If requester is a grad student, bot pings requester with pre-drafted email template.

    2. Claiming (for undergrad purchases):
       Grad student replies: "@p-bot claim" (or "I will order this")
         -> Bot tags both grad student and requester in the thread to coordinate cart/punchout.

    3. Submission / Cart Adjustments:
       Grad student replies: "@p-bot submitted $152.49" (or "processed")
         -> Bot records Date Processed (Col U) and updates Total Price (Col H) if price changed.

    4. Confirmation:
       User replies: "@p-bot confirmed" (with optional attachment)
         -> Bot records Date Confirmed (Col V) and saves confirmation to Order-Confirmations/.
         -> Status formula automatically becomes "Confirmed".

    5. Delivery:
       User replies: "@p-bot delivered"
         -> Bot records Date of Delivery (Col W) and Received By (Col X).
         -> Status formula automatically becomes "Delivered".

    6. Quotes:
       User posts/mentions "@p-bot quote" with attached quote PDF/file
         -> Bot saves quote to Quotes/.

    7. Health, Diagnostics & Admin:
       - "@p-bot health" / "@p-bot status" -> System health card (uptime, disk, memory, paths, queue)
       - "@p-bot queue" -> Pending write tasks status
       - "@p-bot logs [n]" -> Tail bot logs (Admin only)
       - "@p-bot update" -> Pull git updates & restart (Admin only)
       - "@p-bot restart" -> Restart bot process (Admin only)
"""
from datetime import datetime
import logging
from logging.handlers import RotatingFileHandler
import os
import re
import sys
import traceback

import requests
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler

try:
    from . import admin
    from . import config
    from . import epif_parser
    from . import heartbeat
    from . import log_writer
    from . import queue_worker
    from . import validators
except ImportError:
    import admin
    import config
    import epif_parser
    import heartbeat
    import log_writer
    import queue_worker
    import validators

# --- App Home Block Kit View --------------------------------------------------
APP_HOME_VIEW = {
    "type": "home",
    "blocks": [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": "Purchasing Bot: P-Bot",
                "emoji": True,
            },
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "Welcome! *P-Bot* (`@p-bot`) automates logging, tracking, and archiving lab purchase requests directly to `Purchasing-Log.xlsx` and OneDrive.",
            },
        },
        {
            "type": "divider",
        },
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": "🤖 P-Bot Commands",
                "emoji": True,
            },
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    "• *`@p-bot approved`*\n"
                    "Approves the EPIF PDF in a thread. The bot validates the form, logs the row in `Purchasing-Log.xlsx`, saves the PDF to `EPIFs/`, and generates email templates or claims.\n\n"
                    "• *`@p-bot claim`*\n"
                    "(Grad Students) Claim an approved undergrad purchase to submit via Workday/ShopUW+.\n\n"
                    "• *`@p-bot submitted [$price]`*\n"
                    "Marks the order as processed in Workday (Col U). If final cart price changed with tax/shipping, include it (e.g. `@p-bot submitted $152.49`).\n\n"
                    "• *`@p-bot confirmed`*\n"
                    "Marks the order as confirmed (Col V). Attach confirmation emails/receipts to archive them in `Order-Confirmations/`.\n\n"
                    "• *`@p-bot delivered`*\n"
                    "Marks the package as delivered (Col W) and logs who received it (Col X).\n\n"
                    "• *`@p-bot quote`*\n"
                    "Saves an attached vendor quote directly to `Purchasing/Quotes/`.\n\n"
                    "• *`@p-bot health` / `@p-bot status`*\n"
                    "Displays system health, host uptime, disk space, storage connectivity, and Excel lock queue status.\n\n"
                    "• *`@p-bot queue`*\n"
                    "Shows pending write tasks in the automatic Excel lock retry queue.\n\n"
                    "• *`@p-bot logs [n]`* _(Admin Only)_\n"
                    "Displays the last `n` lines of application logs directly in Slack.\n\n"
                    "• *`@p-bot update`* _(Admin Only)_\n"
                    "Pulls latest code updates via git, updates dependencies, and restarts the bot.\n\n"
                    "• *`@p-bot restart`* _(Admin Only)_\n"
                    "Gracefully restarts the bot process.\n\n"
                    "• *`@p-bot help`*\n"
                    "Displays the command reference in Slack."
                ),
            },
        },
        {
            "type": "divider",
        },
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": "📋 How to Use (Step-by-Step)",
                "emoji": True,
            },
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    "1. *Post EPIF Form:* Fill out the lab EPIF PDF and upload it to the purchasing channel or a DM.\n"
                    "2. *Approval:* Charlie or lab admin replies in thread with `@p-bot approved`.\n"
                    "3. *Ordering:* Grad student / requester coordinates purchasing through Workday or department admin.\n"
                    "4. *Status Updates:* Keep the lab updated by tagging `@p-bot` with `submitted`, `confirmed`, and `delivered` as the package arrives."
                ),
            },
        },
        {
            "type": "divider",
        },
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": "⚠️ Common Issues & Troubleshooting",
                "emoji": True,
            },
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    "• *Excel Locked:* If `Purchasing-Log.xlsx` is open in Excel, P-Bot automatically queues your update and writes it immediately once closed.\n"
                    "• *Validation Rejections:* Make sure all required fields in the EPIF PDF are filled (Vendor, Total Price, Project ID/Fund, Item Description).\n"
                    "• *Price Mismatch:* If the final invoice or checkout total differs from the EPIF estimate, mention the exact price with `@p-bot submitted $XX.XX`.\n"
                    "• *File Attachments:* For confirmations and quotes, ensure you attach the file in the same Slack message where you tag the bot."
                ),
            },
        },
        {
            "type": "divider",
        },
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": "💬 Questions, Feedback & Complaints",
                "emoji": True,
            },
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "Bot maintained by: *Isaac Legault*\n\nIf you experience any bugs, errors, or have suggestions/complaints, please feel free to DM me directly on Slack",
            },
        },
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": "Hirst Lab Automation • Report issues to Isaac Legault",
                },
            ],
        },
    ],
}


# --- Setup Logging ------------------------------------------------------------
def setup_logging():
    """Configure comprehensive console and rotating file logging."""
    logger = logging.getLogger("p-bot")
    logger.setLevel(logging.INFO)

    # Avoid duplicate handlers if setup is called multiple times
    if logger.hasHandlers():
        logger.handlers.clear()

    formatter = logging.Formatter(
        fmt="[%(asctime)s] [%(levelname)-7s] [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Console Handler (stdout)
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    # Rotating File Handler (p_bot.log) - 10MB per file, max 5 backups
    try:
        file_handler = RotatingFileHandler(
            config.LOG_FILE,
            maxBytes=10 * 1024 * 1024,
            backupCount=5,
            encoding="utf-8",
        )
        file_handler.setLevel(logging.INFO)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
    except Exception as e:
        logger.warning("Could not initialize file logging at %s: %s", config.LOG_FILE, e)

    return logger


log = setup_logging()
app = App(token=os.environ.get("SLACK_BOT_TOKEN"))


def resolve_requester(client, user_id: str | None) -> str | None:
    """Resolve Slack user ID to the exact name in the Requester Name dropdown."""
    if not user_id:
        return None
    # 1. Check explicit map in config
    if user_id in config.SLACK_USER_TO_REQUESTER:
        return config.SLACK_USER_TO_REQUESTER[user_id]

    # 2. Lookup user profile via Slack API and match against VALID_REQUESTERS
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
            valid_map = {r.lower(): r for r in config.VALID_REQUESTERS}
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
    user_str = f"{requester_name} ({user_id})" if requester_name and user_id else (user_id or requester_name or "Unknown User")

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

    log.warning("Form validation failed for '%s' submitted by %s: %s", filename, user_str, "; ".join(problems))


def find_epif_in_thread(client, channel: str, thread_ts: str):
    """Newest PDF posted in the thread, plus who posted it."""
    replies = client.conversations_replies(channel=channel, ts=thread_ts, limit=200)
    for message in reversed(replies.get("messages", [])):
        for attachment in message.get("files", []):
            name = attachment.get("name", "").lower()
            if name.endswith(".pdf"):
                return attachment, message.get("user")
    return None, None


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


def get_help_message() -> str:
    """Command guide for the bot description and help command."""
    return (
        "🤖 *Hirst Lab Purchasing Bot (P-Bot) Commands:*\n\n"
        "• `@p-bot approved` — Charlie approves an EPIF PDF in a thread. The bot parses, validates, "
        "logs it to `Purchasing-Log.xlsx`, saves the PDF to `EPIFs/`, and initiates the purchasing thread.\n"
        "• `@p-bot claim` — (Grad Student) Claim an approved undergrad purchase to buy via Workday/ShopUW.\n"
        "• `@p-bot submitted [$price]` — Mark an order as submitted in Workday (`Date Processed`, Col U) "
        "and update final cart total if price changed (e.g. `@p-bot submitted $152.49`).\n"
        "• `@p-bot confirmed` — Mark an order as confirmed (`Date Confirmed`, Col V). Attach confirmation emails/receipts "
        "to save them into `Order-Confirmations/`.\n"
        "• `@p-bot delivered` — Mark an order as delivered (`Date of Delivery`, Col W & `Received By`, Col X).\n"
        "• `@p-bot quote` — Save an attached quote PDF/file directly into `Purchasing/Quotes/`.\n"
        "• `@p-bot health` / `@p-bot status` — View system health, host uptime, disk space, and storage status.\n"
        "• `@p-bot queue` — View the Excel lock write queue status.\n"
        "• `@p-bot logs [n]` — _(Admin Only)_ View recent bot log entries.\n"
        "• `@p-bot update` — _(Admin Only)_ Pull latest git code and restart bot.\n"
        "• `@p-bot restart` — _(Admin Only)_ Restart the bot process.\n"
        "• `@p-bot help` — Display this command reference."
    )


def handle_epif_processing(client, say, channel: str, thread_ts: str, approver: str, event_ts: str, direct_file=None, direct_poster=None):
    """Core logic to inspect thread/file, parse, validate, and enqueue row write & PDF archiving."""
    log.info("Processing EPIF request from approver/poster: %s in channel: %s", approver or direct_poster, channel)
    if direct_file:
        file_obj, poster = direct_file, direct_poster
    else:
        file_obj, poster = find_epif_in_thread(client, channel, thread_ts)

    if file_obj is None:
        log.info("No PDF attachment found in thread/message %s", thread_ts)
        say(text="I couldn't find a PDF in this thread/message.", thread_ts=thread_ts)
        return

    requester = resolve_requester(client, poster)
    file_name = file_obj.get("name", "EPIF.pdf")
    log.info("Found file '%s' posted by %s (resolved requester: %s)", file_name, poster, requester)

    try:
        pdf_bytes = download(file_obj)
        log.info("Downloaded %s (%d bytes)", file_name, len(pdf_bytes))
        parsed = epif_parser.parse_epif(pdf_bytes)
        log.info("Parsed EPIF fields: Item='%s', Vendor='%s', Total=$%s, Project=%s, Fund=%s, Category='%s'",
                 parsed.get("item_description"), parsed.get("vendor"), parsed.get("total_price"),
                 parsed.get("project_id"), parsed.get("fund"), parsed.get("category"))
    except (epif_parser.FlattenedPdfError, RuntimeError) as error:
        log_rejection(poster or approver, file_name, [str(error)], requester_name=requester)
        target_dm = poster or approver
        tell(client, target_dm, str(error))
        if channel != target_dm:
            say(text=f"Error processing {file_name}: {str(error)}", thread_ts=thread_ts)
        return

    problems = validators.validate(parsed, requester_name=requester)
    if problems:
        log_rejection(poster or approver, file_name, problems, requester_name=requester)
        bullets = "\n".join(f"  • {p}" for p in problems)
        target_dm = poster or approver
        tell(
            client,
            target_dm,
            f"I couldn't log *{file_name}* yet:\n{bullets}\n\n"
            "Fix those in the EPIF, re-upload it to the thread, and ask for "
            "approval again.",
        )
        if channel != target_dm:
            say(text=f"Not logged - {len(problems)} problem(s), requester DM'd.",
                thread_ts=thread_ts)
        return

    # Define atomic write action for the queue
    def write_action():
        row_num = log_writer.append_row(log_writer.build_row(parsed, requester))
        saved_epif_path = log_writer.save_epif(pdf_bytes, file_name)
        return row_num, saved_epif_path

    def on_success(result):
        row, saved_path = result
        log.info("✅ Successfully logged order to Row %d and saved EPIF to %s", row, saved_path)

        try:
            client.reactions_add(channel=channel, timestamp=event_ts, name="white_check_mark")
        except Exception as e:
            log.debug("Could not add checkmark reaction: %s", e)

        is_grad_buyer = requester in config.GRAD_STUDENT_BUYERS
        ping_user = f"<@{poster}>" if poster else (requester or "Requester")

        if is_grad_buyer:
            log.info("Requester %s is a grad buyer; sending pre-drafted email", requester)
            say(
                text=(
                    f"Logged to row {row}: {parsed['item_description']} — "
                    f"${parsed['total_price']:,.2f} from {parsed['vendor']} "
                    f"({parsed['category']}).\n"
                    f"Saved EPIF to `{saved_path}`.\n\n"
                    f"📢 {ping_user} Please submit this purchase (via Workday or by emailing Tina & Ally). "
                    f"When submitted, reply with `@p-bot submitted [$amount]` and keep me updated when confirmed!"
                ),
                thread_ts=thread_ts,
            )

            if poster:
                email_draft = generate_email_draft(parsed, requester or "Grad Student")
                dm_text = (
                    f"Hi {requester or 'there'}! Your purchase request for *{parsed['item_description']}* "
                    f"has been approved and logged to *Row {row}* in the Purchasing Log.\n\n"
                    f"📋 *Next Steps:*\n"
                    f"1. Submit via Workday or send this email to purchasing (Tina / Ally / Lisa):\n\n"
                    f"```\n{email_draft}\n```\n\n"
                    f"2. Reply with `@p-bot submitted` once ordered, and `@p-bot confirmed` when confirmed!"
                )
                try:
                    tell(client, poster, dm_text)
                except Exception as e:
                    log.warning("Could not DM requester %s: %s", poster, e)

        else:
            log.info("Requester %s is undergrad/non-buyer; broadcasting claim request to grad buyers", requester)
            buyers_list = ", ".join(sorted(config.GRAD_STUDENT_BUYERS))
            say(
                text=(
                    f"Logged to row {row}: {parsed['item_description']} — "
                    f"${parsed['total_price']:,.2f} from {parsed['vendor']} "
                    f"({parsed['category']}).\n"
                    f"Saved EPIF to `{saved_path}`.\n\n"
                    f"📢 {ping_user}'s request is approved!\n"
                    f"⚠️ *Needs a Grad Student Buyer to process in Workday / ShopUW.*\n"
                    f"Grad students ({buyers_list}): please reply here with `@p-bot claim` to take on this order."
                ),
                thread_ts=thread_ts,
            )

    def on_failure(error):
        log.error("Failed to write to workbook: %s", error)
        say(text=f"Error saving/logging EPIF: {error}", thread_ts=thread_ts)

    queue_worker.submit_write_task(
        action_fn=write_action,
        channel=channel,
        thread_ts=thread_ts,
        user_id=approver or direct_poster or "",
        task_type="append",
        description=f"EPIF for {requester or 'requester'}: {parsed.get('item_description', 'Order')}",
        success_callback=on_success,
        failure_callback=on_failure,
        client=client,
    )


def handle_claim(client, say, channel: str, thread_ts: str, user_id: str, event_ts: str):
    """Assign a grad student to an approved order thread."""
    grad_name = resolve_requester(client, user_id) or "Grad Student"
    row = find_row_in_thread(client, channel, thread_ts)
    log.info("Claim event by %s (User: %s) for thread %s (Row: %s)", grad_name, user_id, thread_ts, row)

    try:
        client.reactions_add(channel=channel, timestamp=event_ts, name="raised_hand")
    except Exception as e:
        log.debug("Could not add reaction: %s", e)

    row_info = log_writer.get_row_info(row) if row else {}
    item_str = f" for *{row_info['item_description']}*" if row_info.get("item_description") else ""
    row_str = f" (Row {row})" if row else ""

    say(
        text=(
            f"✋ <@{user_id}> ({grad_name}) has claimed order{item_str}{row_str}!\n"
            f"Please coordinate here with the requester for cart/punchout options. "
            f"Once placed in Workday, reply here with `@p-bot submitted [$total_price]`."
        ),
        thread_ts=thread_ts,
    )


def handle_submission(client, say, channel: str, thread_ts: str, user_id: str, event_ts: str, text: str):
    """Mark an order as Submitted/Processed in Workday (Col U) and optionally update Total Price (Col H)."""
    user_name = resolve_requester(client, user_id) or "Buyer"
    row = extract_row_from_text(text)
    if not row and thread_ts:
        row = find_row_in_thread(client, channel, thread_ts)
    if not row and user_name:
        row = log_writer.find_latest_unconfirmed_row_for_requester(user_name)

    if not row:
        log.warning("Could not identify row for submission by %s (%s). Text: %s", user_name, user_id, text)
        say(
            text="I couldn't figure out which order you're submitting. Please specify the row number (e.g. `@p-bot submitted row 17`).",
            thread_ts=thread_ts,
        )
        return

    today = datetime.now().date()
    update_vals = {config.COLUMN_DATE_PROCESSED: today}

    price = extract_price_from_text(text)
    if price is not None:
        update_vals[config.COLUMN_TOTAL_PRICE] = price

    log.info("Queueing submission update for Row %d on %s (Price: %s) by %s", row, today, price, user_name)

    def write_action():
        return log_writer.update_row(row, update_vals)

    def on_success(res):
        try:
            client.reactions_add(channel=channel, timestamp=event_ts, name="shopping_trolley")
        except Exception as e:
            log.debug("Could not add reaction: %s", e)

        try:
            row_info = log_writer.get_row_info(row)
            item_str = f" for *{row_info['item_description']}*" if row_info.get("item_description") else ""
        except Exception:
            item_str = ""

        price_str = f" with Total Price updated to *${price:,.2f}*" if price is not None else ""
        say(
            text=(
                f"🛒 Order{item_str} (Row {row}) marked as *Processed / Submitted* on {today.strftime('%m/%d/%y')}{price_str}.\n"
                f"Please keep me updated with `@p-bot confirmed` once confirmation from Workday or admin arrives!"
            ),
            thread_ts=thread_ts,
        )

    def on_failure(error):
        log.error("Error updating Order Log for row %d: %s", row, error)
        say(text=f"Error updating Order Log for row {row}: {error}", thread_ts=thread_ts)

    queue_worker.submit_write_task(
        action_fn=write_action,
        channel=channel,
        thread_ts=thread_ts,
        user_id=user_id,
        task_type="update",
        description=f"Submission for row {row} by {user_name}",
        success_callback=on_success,
        failure_callback=on_failure,
        client=client,
    )


def handle_confirmation(client, say, channel: str, thread_ts: str, user_id: str, event_ts: str, text: str, files=None):
    """Mark an order as Confirmed in Purchasing-Log.xlsx (Col V) and save confirmation files."""
    requester_name = resolve_requester(client, user_id)
    row = extract_row_from_text(text)
    if not row and thread_ts:
        row = find_row_in_thread(client, channel, thread_ts)
    if not row and requester_name:
        row = log_writer.find_latest_unconfirmed_row_for_requester(requester_name)

    if not row:
        log.warning("Could not identify row for confirmation by %s (%s). Text: %s", requester_name, user_id, text)
        say(
            text="I couldn't figure out which order you're confirming. Please specify the row number (e.g. `@p-bot confirmed row 17`).",
            thread_ts=thread_ts,
        )
        return

    today = datetime.now().date()
    update_vals = {config.COLUMN_DATE_CONFIRMED: today}

    def write_action():
        saved_files = []
        if files:
            for f in files:
                fname = f.get("name", "Order_Confirmation.pdf")
                try:
                    content = download_file(f)
                    saved = log_writer.save_confirmation(content, fname)
                    saved_files.append(saved)
                    log.info("Saved confirmation file '%s' to %s", fname, saved)
                except Exception as e:
                    log.warning("Could not save confirmation attachment %s: %s", fname, e)
        log_writer.update_row(row, update_vals)
        return row, saved_files

    def on_success(result):
        res_row, saved_files = result
        try:
            client.reactions_add(channel=channel, timestamp=event_ts, name="white_check_mark")
        except Exception as e:
            log.debug("Could not add reaction: %s", e)

        try:
            row_info = log_writer.get_row_info(row)
            item_str = f" for *{row_info['item_description']}*" if row_info.get("item_description") else ""
        except Exception:
            item_str = ""

        conf_msg = f"✅ Order{item_str} (Row {row}) has been marked as *Confirmed* in the Purchasing Log (Date Confirmed: {today.strftime('%m/%d/%y')})."
        if saved_files:
            conf_msg += f"\nSaved {len(saved_files)} confirmation file(s) to `Order-Confirmations`."

        say(text=conf_msg, thread_ts=thread_ts)

    def on_failure(error):
        log.error("Error updating Order Log for row %d: %s", row, error)
        say(text=f"Error updating Order Log for row {row}: {error}", thread_ts=thread_ts)

    queue_worker.submit_write_task(
        action_fn=write_action,
        channel=channel,
        thread_ts=thread_ts,
        user_id=user_id,
        task_type="update",
        description=f"Confirmation for row {row} by {requester_name or user_id}",
        success_callback=on_success,
        failure_callback=on_failure,
        client=client,
    )


def handle_delivery(client, say, channel: str, thread_ts: str, user_id: str, event_ts: str, text: str):
    """Mark an order as Delivered in Purchasing-Log.xlsx (Col W) and record Received By (Col X)."""
    requester_name = resolve_requester(client, user_id) or "Lab Member"
    row = extract_row_from_text(text)
    if not row and thread_ts:
        row = find_row_in_thread(client, channel, thread_ts)
    if not row and requester_name:
        row = log_writer.find_latest_unconfirmed_row_for_requester(requester_name)

    if not row:
        log.warning("Could not identify row for delivery by %s (%s). Text: %s", requester_name, user_id, text)
        say(
            text="I couldn't figure out which order was delivered. Please specify the row number (e.g. `@p-bot delivered row 17`).",
            thread_ts=thread_ts,
        )
        return

    today = datetime.now().date()
    update_vals = {
        config.COLUMN_DATE_DELIVERY: today,
        config.COLUMN_RECEIVED_BY: requester_name,
    }

    def write_action():
        return log_writer.update_row(row, update_vals)

    def on_success(res):
        try:
            client.reactions_add(channel=channel, timestamp=event_ts, name="package")
        except Exception as e:
            log.debug("Could not add reaction: %s", e)

        try:
            row_info = log_writer.get_row_info(row)
            item_str = f" for *{row_info['item_description']}*" if row_info.get("item_description") else ""
        except Exception:
            item_str = ""

        say(
            text=f"📦 Order{item_str} (Row {row}) has been marked as *Delivered* (Date: {today.strftime('%m/%d/%y')}, Received By: {requester_name}).",
            thread_ts=thread_ts,
        )

    def on_failure(error):
        log.error("Error updating Order Log for row %d: %s", row, error)
        say(text=f"Error updating Order Log for row {row}: {error}", thread_ts=thread_ts)

    queue_worker.submit_write_task(
        action_fn=write_action,
        channel=channel,
        thread_ts=thread_ts,
        user_id=user_id,
        task_type="update",
        description=f"Delivery for row {row} by {requester_name}",
        success_callback=on_success,
        failure_callback=on_failure,
        client=client,
    )


def handle_quote(client, say, channel: str, thread_ts: str, event_ts: str, files=None):
    """Save quote file(s) into the lab's Quotes directory."""
    log.info("Processing quote archive request in channel %s", channel)
    if not files:
        if thread_ts:
            try:
                replies = client.conversations_replies(channel=channel, ts=thread_ts, limit=50)
                for msg in reversed(replies.get("messages", [])):
                    if msg.get("files"):
                        files = msg.get("files")
                        break
            except Exception:
                pass

    if not files:
        log.warning("No quote attachment found in quote request message/thread %s", thread_ts)
        say(text="Please attach the quote file (PDF or image) with your message.", thread_ts=thread_ts)
        return

    saved_paths = []
    for f in files:
        fname = f.get("name", "Vendor_Quote.pdf")
        try:
            content = download_file(f)
            saved = log_writer.save_quote(content, fname)
            saved_paths.append(saved)
            log.info("Saved quote file '%s' to %s", fname, saved)
        except Exception as e:
            log.warning("Could not download/save quote %s: %s", fname, e)

    if saved_paths:
        try:
            client.reactions_add(channel=channel, timestamp=event_ts, name="page_facing_up")
        except Exception:
            pass
        say(
            text=f"📄 Saved {len(saved_paths)} quote file(s) to `Purchasing\\Quotes` (`{saved_paths[0]}`).",
            thread_ts=thread_ts,
        )
    else:
        say(text="Failed to save attached quote file.", thread_ts=thread_ts)


# --- Diagnostic & Admin Command Handlers --------------------------------------

def handle_health_status(client, say, channel: str, thread_ts: str):
    """Publish comprehensive health and diagnostics report."""
    blocks = admin.build_health_blocks()
    say(
        text="🩺 *P-Bot System Health & Status*",
        blocks=blocks,
        thread_ts=thread_ts,
    )


def handle_queue_status(client, say, channel: str, thread_ts: str):
    """Report pending tasks in the Excel write queue."""
    q = queue_worker.get_queue_status()
    pending = q["pending_count"]

    if pending == 0:
        say(
            text="✅ *Excel Write Queue:* All clear! There are currently 0 pending write tasks.",
            thread_ts=thread_ts,
        )
        return

    status_lines = [f"⏳ *Excel Write Queue:* `{pending} pending task(s)`"]
    if q.get("is_locked"):
        status_lines.append("⚠️ `Purchasing-Log.xlsx` is currently open in Excel. Tasks are retrying automatically every 5s.")

    curr = q.get("current_task")
    if curr:
        status_lines.append(
            f"\n*Currently Active:* Task `{curr['task_id']}` ({curr['task_type']}) — {curr['description']}\n"
            f"  • Submitted by: <@{curr['user_id']}> at {curr['created_at']} (Retries: {curr['retry_count']})"
        )

    queued = q.get("queued_tasks", [])
    if queued:
        status_lines.append("\n*Queued Tasks:*")
        for i, t in enumerate(queued, 1):
            status_lines.append(f"  {i}. Task `{t['task_id']}` ({t['task_type']}) — {t['description']} (<@{t['user_id']}>)")

    say(text="\n".join(status_lines), thread_ts=thread_ts)


def handle_logs(client, say, channel: str, thread_ts: str, user_id: str, text: str):
    """Show tail of application logs to authorized administrators."""
    if not admin.is_admin_user(user_id):
        log.warning("Unauthorized user %s attempted to run '@p-bot logs'", user_id)
        say(text="🔒 This command is restricted to bot administrators.", thread_ts=thread_ts)
        return

    # Extract optional line count (default 30, max 100)
    match = re.search(r"\blogs?\s+(\d+)\b", text, re.I)
    n = int(match.group(1)) if match else 30
    n = max(1, min(100, n))

    log_tail = admin.get_tail_logs(n=n)
    if len(log_tail) > 2800:
        log_tail = log_tail[-2800:]

    say(
        text=f"📋 *Recent Bot Logs (Last {n} lines):*\n```\n{log_tail}\n```",
        thread_ts=thread_ts,
    )


def handle_update(client, say, channel: str, thread_ts: str, user_id: str):
    """Pull latest changes from git, update dependencies, and trigger restart."""
    if not admin.is_admin_user(user_id):
        log.warning("Unauthorized user %s attempted to run '@p-bot update'", user_id)
        say(text="🔒 This command is restricted to bot administrators.", thread_ts=thread_ts)
        return

    say(text="🔄 Checking for updates and pulling latest changes from git repository...", thread_ts=thread_ts)
    success, msg = admin.execute_git_update()
    say(text=msg, thread_ts=thread_ts)

    if success and "already up to date" not in msg.lower():
        say(text="🚀 Code updated! Restarting P-Bot process in 2 seconds...", thread_ts=thread_ts)
        admin.execute_restart(delay=2.0)


def handle_restart(client, say, channel: str, thread_ts: str, user_id: str):
    """Restart the bot process cleanly if queue is idle."""
    if not admin.is_admin_user(user_id):
        log.warning("Unauthorized user %s attempted to run '@p-bot restart'", user_id)
        say(text="🔒 This command is restricted to bot administrators.", thread_ts=thread_ts)
        return

    q = queue_worker.get_queue_status()
    if q["pending_count"] > 0:
        say(
            text=f"⚠️ Cannot restart yet: {q['pending_count']} write task(s) are currently in the queue. Please wait until they finish.",
            thread_ts=thread_ts,
        )
        return

    say(text="🔄 Restarting P-Bot process cleanly...", thread_ts=thread_ts)
    admin.execute_restart(delay=1.5)


# --- Dispatcher Helpers -------------------------------------------------------

def dispatch_command(client, say, channel: str, thread_ts: str, user: str, event_ts: str, text: str, files=None, direct_file=None):
    """Single dispatch point for all app_mention and direct message commands."""
    text_lower = text.lower()

    if any(kw in text_lower for kw in config.HELP_KEYWORDS):
        say(text=get_help_message(), thread_ts=thread_ts)
    elif any(kw in text_lower for kw in config.STATUS_KEYWORDS):
        handle_health_status(client, say, channel, thread_ts)
    elif any(kw in text_lower for kw in config.QUEUE_KEYWORDS):
        handle_queue_status(client, say, channel, thread_ts)
    elif any(kw in text_lower for kw in config.LOGS_KEYWORDS):
        handle_logs(client, say, channel, thread_ts, user, text)
    elif any(kw in text_lower for kw in config.UPDATE_KEYWORDS):
        handle_update(client, say, channel, thread_ts, user)
    elif any(kw in text_lower for kw in config.RESTART_KEYWORDS):
        handle_restart(client, say, channel, thread_ts, user)
    elif any(kw in text_lower for kw in config.QUOTE_KEYWORDS):
        handle_quote(client, say, channel, thread_ts, event_ts, files)
    elif any(kw in text_lower for kw in config.CLAIM_KEYWORDS):
        handle_claim(client, say, channel, thread_ts, user, event_ts)
    elif any(kw in text_lower for kw in config.SUBMIT_KEYWORDS):
        handle_submission(client, say, channel, thread_ts, user, event_ts, text)
    elif any(kw in text_lower for kw in config.CONFIRM_KEYWORDS):
        handle_confirmation(client, say, channel, thread_ts, user, event_ts, text, files)
    elif any(kw in text_lower for kw in config.DELIVERED_KEYWORDS):
        handle_delivery(client, say, channel, thread_ts, user, event_ts, text)
    elif config.TRIGGER_KEYWORD in text_lower or direct_file or any(w in text_lower for w in ("check", "test")):
        handle_epif_processing(
            client, say, channel, thread_ts, user, event_ts,
            direct_file=direct_file, direct_poster=user if direct_file else None
        )


@app.event("app_mention")
def on_mention(event, client, say):
    text = event.get("text", "")
    channel = event["channel"]
    thread_ts = event.get("thread_ts") or event["ts"]
    user = event.get("user")
    event_ts = event["ts"]
    files = event.get("files", [])

    log.info("Received app_mention from user %s in channel %s: '%s'", user, channel, text)
    dispatch_command(client, say, channel, thread_ts, user, event_ts, text, files=files)


@app.event("message")
def on_direct_message(event, client, say):
    # Only process direct messages (DMs), ignore bot's own messages and standard channel chatter
    if event.get("channel_type") != "im" or event.get("subtype") == "bot_message":
        return

    user = event.get("user")
    channel = event["channel"]
    thread_ts = event.get("thread_ts") or event["ts"]
    event_ts = event["ts"]
    text = event.get("text", "")

    log.info("Received DM from user %s: '%s'", user, text)

    # Look for files attached in this direct message
    files = event.get("files", [])
    pdf_files = [f for f in files if f.get("name", "").lower().endswith(".pdf")]
    direct_file = pdf_files[0] if pdf_files else None

    dispatch_command(
        client, say, channel, thread_ts, user, event_ts, text,
        files=files, direct_file=direct_file
    )


@app.event("app_home_opened")
def handle_app_home_opened(client, event):
    """Publish the App Home view whenever a user opens the Home tab."""
    user_id = event.get("user")
    if not user_id:
        return
    try:
        client.views_publish(
            user_id=user_id,
            view=APP_HOME_VIEW,
        )
        log.info("Published App Home view to user %s", user_id)
    except Exception as e:
        log.warning("Failed to publish App Home view to user %s: %s", user_id, e)


@app.error
def handle_global_errors(error, body, logger):
    """Global error catcher for Slack Bolt events."""
    log.exception("Global unhandled exception in Slack Bolt app: %s", error)
    try:
        tb = traceback.format_exc()
        heartbeat.send_crash_alert(app.client, str(error), exc_info=tb)
    except Exception as alert_err:
        log.warning("Could not dispatch crash alert: %s", alert_err)


def main():
    """Main application startup routine."""
    setup_logging()
    log.info("=" * 70)
    log.info("🤖 Starting P-Bot (Hirst Lab Purchasing Bot) v%s...", config.BOT_VERSION)
    log.info("Base Directory: %s", config.BASE_DIR)
    if config.LOADED_ENV_PATH:
        log.info("Loaded .env from: %s", config.LOADED_ENV_PATH)
    else:
        log.warning("No .env file found; using existing environment variables.")
    log.info("Log File: %s", config.LOG_FILE)
    log.info("Rejections Log: %s", config.REJECTIONS_LOG_FILE)
    log.info("Purchasing Log Workbook: %s", config.WORKBOOK_PATH)
    log.info("EPIFs Dir: %s", config.EPIFS_DIR)
    log.info("Confirmations Dir: %s", config.CONFIRMATIONS_DIR)
    log.info("Quotes Dir: %s", config.QUOTES_DIR)
    log.info("Admin Users: %s", config.ADMIN_SLACK_USER_IDS)
    log.info("Admin Alert Channel: %s", config.ADMIN_ALERT_CHANNEL or "Not configured")
    log.info("Heartbeat URL: %s", config.HEALTHCHECK_URL or "Not configured")
    log.info("=" * 70)

    # 1. Start Lock Queue Worker
    queue_worker.start_queue_worker(client=app.client)

    # 2. Start External Heartbeat Monitor (Dead-Man's Switch)
    heartbeat.start_heartbeat()

    # 3. Post Boot / Startup Alert to Admin Channel
    heartbeat.send_startup_alert(app.client)

    app_token = os.environ.get("SLACK_APP_TOKEN")
    if not app_token:
        log.error("SLACK_APP_TOKEN environment variable is missing.")
        raise ValueError("SLACK_APP_TOKEN environment variable is missing.")
    SocketModeHandler(app, app_token).start()


if __name__ == "__main__":
    main()
