"""Operational, diagnostic, administrative, and template command handlers.

WHY THIS EXISTS:
----------------
Implements administrative commands (health, queue status, logs, update, restart,
roster promotions/removals) and template distribution.

Imports:
    - admin, config, queue_worker, roster, blocks
May NOT import:
    - app.py
"""
import json
import logging
import os
import re

try:
    from . import admin, config, log_writer, queue_worker, roster, slack_io, text_rules
except ImportError:
    import admin
    import config
    import log_writer
    import queue_worker
    import roster
    import slack_io
    import text_rules

log = logging.getLogger("p-bot")


def handle_health_status(client, say, channel: str, thread_ts: str):
    """Publish comprehensive health and diagnostics report."""
    health_blocks = admin.build_health_blocks()
    say(
        text="🩺 *P-Bot System Health & Status*",
        blocks=health_blocks,
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
    """Show tail or full log files to authorized administrators in the alert channel.

    WHY THIS EXISTS:
    ----------------
    Ticket 23 / Spec Part A:
    Logs carry names, Slack IDs, and purchase details. To prevent leakage:
    1. Caller must be an authorized admin (admin.is_admin_user).
    2. config.ADMIN_ALERT_CHANNEL must be configured.
    3. Command must be executed in config.ADMIN_ALERT_CHANNEL.
    Tail <= 2,800 chars is posted inline with header containing actual line count k.
    Tail > 2,800 chars, 'all' (whole p_bot.log), and 'rejections' (whole rejections.log)
    are uploaded via client.files_upload_v2 into the thread.
    No 100-line clamp; tokens and webhook URLs are masked.
    """
    # 1. Admin permission check
    if not admin.is_admin_user(user_id):
        log.warning("Unauthorized user %s attempted to run '@p-bot logs'", user_id)
        say(text="🔒 This command is restricted to bot administrators.", thread_ts=thread_ts)
        return

    # 2. Alert channel configured check
    alert_channel = getattr(config, "ADMIN_ALERT_CHANNEL", None)
    if not alert_channel:
        say(
            text="⚠️ Logs are unavailable: ADMIN_ALERT_CHANNEL is not set in the bot's .env.",
            thread_ts=thread_ts,
        )
        return

    # 3. Channel restriction check
    if channel != alert_channel:
        say(
            text=f"🔒 Logs are only available in <#{alert_channel}>.",
            thread_ts=thread_ts,
        )
        return

    # 4. Parse the form from text
    stripped_text, _, _ = text_rules.parse_mentions(text)
    tokens = stripped_text.strip().split()
    remaining = tokens[1:] if len(tokens) > 1 else []

    target_file = None
    tail_n = None
    is_tail = False
    filename = None
    comment = None
    arg_lower = None

    if len(remaining) == 0:
        is_tail = True
        tail_n = 30
        target_file = config.LOG_FILE
    elif len(remaining) == 1:
        arg = remaining[0]
        arg_lower = arg.lower()
        if arg_lower == "all":
            target_file = config.LOG_FILE
            filename = "p_bot.log"
        elif arg_lower == "rejections":
            target_file = config.REJECTIONS_LOG_FILE
            filename = "rejections.log"
        elif re.fullmatch(r"-?\d+", arg):
            is_tail = True
            tail_n = max(1, int(arg))
            target_file = config.LOG_FILE
        else:
            say(
                text="Unknown logs option. Use `logs [n]`, `logs all`, or `logs rejections`.",
                thread_ts=thread_ts,
            )
            return
    else:
        say(
            text="Unknown logs option. Use `logs [n]`, `logs all`, or `logs rejections`.",
            thread_ts=thread_ts,
        )
        return

    # Read the log file
    try:
        masked_text, k = admin.read_log_file(target_file, n=tail_n if is_tail else None)
    except FileNotFoundError:
        say(text=f"Log file not found at `{target_file}`.", thread_ts=thread_ts)
        return
    except Exception as e:
        say(text=f"Error reading log file: {e}", thread_ts=thread_ts)
        return

    # Decide delivery method
    if is_tail and len(masked_text) <= 2800:
        say(
            text=f"📋 *Recent Bot Logs (Last {k} lines):*\n```\n{masked_text}\n```",
            thread_ts=thread_ts,
        )
        return

    # Upload as file in thread
    if is_tail:
        filename = f"p_bot_last_{k}_lines.log"
        comment = f"📋 Last {k} lines of p_bot.log (too long to post inline)."
    elif arg_lower == "all":
        filename = "p_bot.log"
        comment = f"📋 Full p_bot.log ({k} lines)."
    elif arg_lower == "rejections":
        filename = "rejections.log"
        comment = f"📋 Full rejections.log ({k} lines)."

    try:
        client.files_upload_v2(
            channel=channel,
            thread_ts=thread_ts,
            content=masked_text,
            filename=filename,
            title=filename,
            initial_comment=comment,
        )
    except Exception as e:
        log.warning("Could not upload %s: %s", filename, e, exc_info=True)
        say(text=f"⚠️ Could not upload {filename}: {e}", thread_ts=thread_ts)


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


def handle_promote_admin(client, say, channel: str, thread_ts: str, user_id: str, text: str):
    """Admin command to propose promoting another user to admin."""
    if not admin.is_admin_user(user_id):
        log.warning("Unauthorized user %s attempted to run '@p-bot promote-admin'", user_id)
        say(text="🔒 This command is restricted to bot administrators.", thread_ts=thread_ts)
        return

    match = re.search(r"<@([A-Z0-9_]+)>", text)
    if not match:
        say(text="⚠️ Please mention the user to promote, e.g. `@p-bot promote-admin @user`.", thread_ts=thread_ts)
        return

    target_user_id = match.group(1)
    if config.ADMIN_ALERT_CHANNEL:
        client.chat_postMessage(
            channel=config.ADMIN_ALERT_CHANNEL,
            text=f"👑 Admin promotion proposed for <@{target_user_id}> by <@{user_id}>.",
            blocks=[
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": (
                            f"👑 *Admin Promotion Request:*\n"
                            f"Proposed Admin: <@{target_user_id}> (`{target_user_id}`)\n"
                            f"Proposed by: <@{user_id}>\n"
                            f"Approve promoting them to bot administrator in `roster.json`?"
                        ),
                    },
                },
                {
                    "type": "actions",
                    "elements": [
                        {
                            "type": "button",
                            "text": {"type": "plain_text", "text": "Approve Admin Promotion"},
                            "style": "primary",
                            "action_id": "approve_new_admin",
                            "value": json.dumps({"slack_id": target_user_id}),
                        }
                    ],
                },
            ],
        )
        say(text=f"👑 Admin promotion proposal for <@{target_user_id}> has been sent to the admin alerts channel for approval.", thread_ts=thread_ts)
    else:
        say(text="⚠️ ADMIN_ALERT_CHANNEL is not configured.", thread_ts=thread_ts)


def handle_remove_vendor(client, say, channel: str, thread_ts: str, user_id: str, text: str):
    """Admin command to remove a vendor from the Workday punchout catalog list."""
    if not admin.is_admin_user(user_id):
        log.warning("Unauthorized user %s attempted to run '@p-bot remove vendor'", user_id)
        say(text="🔒 This command is restricted to bot administrators.", thread_ts=thread_ts)
        return

    match = re.search(r"(?:remove vendor|delete vendor)\s+(.+)", text, re.I)
    if not match:
        say(text="⚠️ Please specify the vendor name, e.g. `@p-bot remove vendor Fisher Scientific`.", thread_ts=thread_ts)
        return

    vendor_name = match.group(1).strip()
    removed = roster.remove_vendor(vendor_name)
    if removed:
        say(
            text=f"✅ Vendor *{vendor_name}* was removed from `roster.json`. (Run `@p-bot restart` to update dropdowns).",
            thread_ts=thread_ts,
        )
    else:
        all_vendors = roster.get_vendors()
        close = [v for v in all_vendors if vendor_name.lower() in v.lower()]
        close_str = f"\nDid you mean: {', '.join(close[:5])}?" if close else ""
        say(
            text=f"⚠️ Vendor '{vendor_name}' was not found in the catalog list.{close_str}",
            thread_ts=thread_ts,
        )


def handle_add_approver(client, say, channel: str, thread_ts: str, user_id: str, text: str):
    """Admin command to add a user to the approver list."""
    if not admin.is_admin_user(user_id):
        log.warning("Unauthorized user %s attempted to run '@p-bot add-approver'", user_id)
        say(text="🔒 This command is restricted to bot administrators.", thread_ts=thread_ts)
        return

    match = re.search(r"<@([A-Z0-9_]+)>", text)
    if not match:
        say(text="⚠️ Please mention the user to add as approver, e.g. `@p-bot add-approver @user`.", thread_ts=thread_ts)
        return

    target_id = match.group(1)
    roster.add_approver(target_id)
    say(
        text=f"✅ <@{target_id}> added to purchase approvers in `roster.json`. (Run `@p-bot restart` to reload).",
        thread_ts=thread_ts,
    )


def handle_remove_approver(client, say, channel: str, thread_ts: str, user_id: str, text: str):
    """Admin command to remove a user from the approver list."""
    if not admin.is_admin_user(user_id):
        log.warning("Unauthorized user %s attempted to run '@p-bot remove-approver'", user_id)
        say(text="🔒 This command is restricted to bot administrators.", thread_ts=thread_ts)
        return

    match = re.search(r"<@([A-Z0-9_]+)>", text)
    if not match:
        say(text="⚠️ Please mention the user to remove from approvers, e.g. `@p-bot remove-approver @user`.", thread_ts=thread_ts)
        return

    target_id = match.group(1)
    if roster.remove_approver(target_id):
        say(
            text=f"✅ <@{target_id}> removed from purchase approvers in `roster.json`. (Run `@p-bot restart` to reload).",
            thread_ts=thread_ts,
        )
    else:
        say(text=f"⚠️ <@{target_id}> was not in the approvers list.", thread_ts=thread_ts)


def handle_add_buyer(client, say, channel: str, thread_ts: str, user_id: str, text: str):
    """Admin command to add a user to the purchase buyer list."""
    if not admin.is_admin_user(user_id):
        log.warning("Unauthorized user %s attempted to run '@p-bot add-buyer'", user_id)
        say(text="🔒 This command is restricted to bot administrators.", thread_ts=thread_ts)
        return

    match = re.search(r"<@([A-Z0-9_]+)>", text)
    if not match:
        say(text="⚠️ Please mention the user to add as buyer, e.g. `@p-bot add-buyer @user`.", thread_ts=thread_ts)
        return

    target_id = match.group(1)
    roster.add_buyer(target_id)

    warning = ""
    requesters = roster.get_requesters() if hasattr(roster, "get_requesters") else {}
    if target_id not in requesters:
        warning = (
            f"\n⚠️ *Warning:* <@{target_id}> does not have a mapped requester name in `roster.json`. "
            f"Please have them run `/roster-set-name` (or link their account) so their name appears on claimed orders."
        )

    say(
        text=f"✅ <@{target_id}> added to purchase buyers in `roster.json`.{warning}",
        thread_ts=thread_ts,
    )


def handle_remove_buyer(client, say, channel: str, thread_ts: str, user_id: str, text: str):
    """Admin command to remove a user from the purchase buyer list."""
    if not admin.is_admin_user(user_id):
        log.warning("Unauthorized user %s attempted to run '@p-bot remove-buyer'", user_id)
        say(text="🔒 This command is restricted to bot administrators.", thread_ts=thread_ts)
        return

    match = re.search(r"<@([A-Z0-9_]+)>", text)
    if not match:
        say(text="⚠️ Please mention the user to remove from buyers, e.g. `@p-bot remove-buyer @user`.", thread_ts=thread_ts)
        return

    target_id = match.group(1)
    if roster.remove_buyer(target_id):
        say(
            text=f"✅ <@{target_id}> removed from purchase buyers in `roster.json`.",
            thread_ts=thread_ts,
        )
    else:
        say(text=f"⚠️ <@{target_id}> was not in the buyers list.", thread_ts=thread_ts)


def handle_remove_member(
    client,
    say,
    channel: str,
    thread_ts: str,
    user_id: str,
    text: str,
    target_user_id: str | None = None,
    respond=None,
):
    """Admin command to remove a member from the lab roster completely.

    Hard-deletes their requester entry, strips admin/approver/buyer roles,
    and alerts ADMIN_ALERT_CHANNEL with the cell reference of the orphaned
    dropdown entry in Roles & Lists. Refuses if removing the user would leave
    the roster with no admin or no approver.

    WHY THIS EXISTS:
    ----------------
    Ticket 20: Differentiates removing a role (remove-buyer) from removing a person
    (remove-member). A graduating student is stripped of all roles and membership in
    one atomic save. Because the workbook mirror is append-only (Ticket 11 Invariant 2),
    their cell in the dropdown list remains until a human deletes it; this handler
    finds the cell and reports it to ADMIN_ALERT_CHANNEL.
    """
    if not admin.is_admin_user(user_id):
        log.warning("Unauthorized user %s attempted to run '@Purchasing remove-member'", user_id)
        msg = "🔒 Only bot administrators can remove members."
        if respond:
            slack_io.deny(respond, msg)
        else:
            say(text=msg, thread_ts=thread_ts)
        return

    target_id = target_user_id
    if not target_id:
        match = re.search(r"<@([A-Z0-9_]+)>", text)
        if match:
            target_id = match.group(1)

    if not target_id:
        say(
            text="⚠️ Please mention the user to remove, e.g. `@Purchasing remove-member @user`.",
            thread_ts=thread_ts,
        )
        return

    try:
        res = roster.remove_member(target_id)
    except ValueError as e:
        say(text=f"⚠️ {e}", thread_ts=thread_ts)
        return

    removed_name = res.get("name")
    roles = res.get("roles", [])

    if not removed_name and not roles:
        say(
            text=f"⚠️ <@{target_id}> was not found in the roster.",
            thread_ts=thread_ts,
        )
        return

    name_str = f" ({removed_name})" if removed_name else ""
    roles_str = f" (roles stripped: {', '.join(roles)})" if roles else ""
    say(
        text=f"✅ <@{target_id}>{name_str} removed from the roster{roles_str}.",
        thread_ts=thread_ts,
    )

    if removed_name and config.ADMIN_ALERT_CHANNEL:
        cell_ref = log_writer.find_requester_cell(removed_name)
        cell_desc = f"at cell {cell_ref}" if cell_ref else "in the table"
        alert_text = (
            f"⚠️ Lab member <@{target_id}> ({removed_name}) was removed from `roster.json`.\n"
            f"The 'Roles & Lists' sheet has an orphaned entry in the 'Requesters' table {cell_desc}. "
            "Please delete it manually if no longer needed."
        )
        try:
            client.chat_postMessage(
                channel=config.ADMIN_ALERT_CHANNEL,
                text=alert_text,
            )
        except Exception as e:
            log.warning("Could not send orphaned entry alert to %s: %s", config.ADMIN_ALERT_CHANNEL, e)


def handle_template_command(client, say, channel: str, thread_ts: str | None, user_id: str):
    """Provide the blank EPIF form and guide for users who prefer manual submission (Phase 3)."""
    template_dir = config.TEMPLATE_DIR
    pdf_path = os.path.join(template_dir, "EPIF_TEMPLATE_HIRST.pdf")
    readme_path = os.path.join(template_dir, "README.md")
    if not os.path.exists(readme_path):
        readme_path = os.path.join(template_dir, "README.txt")

    missing = []
    if not os.path.exists(template_dir):
        missing.append(f"Directory `{template_dir}`")
    else:
        if not os.path.exists(pdf_path):
            missing.append("`EPIF_TEMPLATE_HIRST.pdf`")
        if not os.path.exists(readme_path):
            missing.append("`README.md`")

    if missing:
        msg_missing = (
            f"⚠️ *Template files missing:*\n"
            f"Could not find {', '.join(missing)} in `{template_dir}`.\n"
            f"Please ensure `EPIF_TEMPLATE_HIRST.pdf` and `README.md` are placed in the `_TEMPLATE` directory."
        )
        if thread_ts:
            say(text=msg_missing, thread_ts=thread_ts)
        else:
            say(text=msg_missing)
        return

    guide_text = (
        "📄 *Hirst Lab Manual EPIF Submission Kit:*\n\n"
        "1. Open the attached `EPIF_TEMPLATE_HIRST.pdf` in Adobe Acrobat or your PDF editor.\n"
        "2. Fill in the required fields: *What*, *Why / URL*, *Amount*, *Vendor*, *Vendor Email*, *Date*, *Room*, *Project ID*, and tick *1 Category* + *Payment Method*.\n"
        "3. Upload your completed PDF to the purchasing channel and tag Charlie for approval.\n"
        "4. Once approved, P-Bot will validate and log your request automatically!"
    )

    if thread_ts:
        say(text=guide_text, thread_ts=thread_ts)
    else:
        say(text=guide_text)

    try:
        if hasattr(client, "files_upload_v2"):
            kwargs1 = {
                "channel": channel,
                "file": pdf_path,
                "title": "EPIF_TEMPLATE_HIRST.pdf",
                "filename": "EPIF_TEMPLATE_HIRST.pdf",
            }
            if thread_ts:
                kwargs1["thread_ts"] = thread_ts
            client.files_upload_v2(**kwargs1)

            kwargs2 = {
                "channel": channel,
                "file": readme_path,
                "title": "README.md",
                "filename": "README.md",
            }
            if thread_ts:
                kwargs2["thread_ts"] = thread_ts
            client.files_upload_v2(**kwargs2)
        else:
            kwargs1 = {
                "channels": channel,
                "file": pdf_path,
                "title": "EPIF_TEMPLATE_HIRST.pdf",
            }
            if thread_ts:
                kwargs1["thread_ts"] = thread_ts
            client.files_upload(**kwargs1)

            kwargs2 = {
                "channels": channel,
                "file": readme_path,
                "title": "README.md",
            }
            if thread_ts:
                kwargs2["thread_ts"] = thread_ts
            client.files_upload(**kwargs2)
    except Exception as e:
        log.warning("Could not upload template files via Slack API: %s", e)
        err_msg = f"*(Could not attach files directly: {e})*"
        if thread_ts:
            say(text=err_msg, thread_ts=thread_ts)
        else:
            say(text=err_msg)


def handle_approve_new_requester(client, approver_id: str, channel_id: str, msg_ts: str, slack_id: str, name: str):
    """Admin approved a new requester in the alerts channel."""
    roster.add_requester(slack_id, name)
    client.chat_update(
        channel=channel_id,
        ts=msg_ts,
        text=f"✅ Approved by <@{approver_id}>: <@{slack_id}> added as '{name}'.",
        blocks=[
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"✅ *Approved by <@{approver_id}>:* <@{slack_id}> added as *{name}* in `roster.json`.",
                },
            }
        ],
    )
    slack_io.tell(client, slack_id, f"🎉 You're approved as '{name}'!")
    log.info("Admin %s approved new requester %s (%s)", approver_id, slack_id, name)


def handle_approve_rename_requester(
    client, approver_id: str, channel_id: str, msg_ts: str, slack_id: str, old_name: str, new_name: str
):
    """Admin approved renaming a requester in the alerts channel."""
    roster.rename_requester(slack_id, new_name)
    client.chat_update(
        channel=channel_id,
        ts=msg_ts,
        text=f"✅ Approved by <@{approver_id}>: <@{slack_id}> renamed from '{old_name}' to '{new_name}'.",
        blocks=[
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"✅ *Approved by <@{approver_id}>:* <@{slack_id}> renamed from *{old_name}* to *{new_name}* in `roster.json`.",
                },
            }
        ],
    )
    slack_io.tell(client, slack_id, f"🎉 Your name change from '{old_name}' to '{new_name}' was approved!")
    log.info("Admin %s approved renaming requester %s from '%s' to '%s'", approver_id, slack_id, old_name, new_name)



def handle_approve_new_admin(client, approver_id: str, channel_id: str, msg_ts: str, slack_id: str):
    """Admin approved an admin promotion in the alerts channel."""
    roster.add_admin(slack_id)
    client.chat_update(
        channel=channel_id,
        ts=msg_ts,
        text=f"✅ Approved by <@{approver_id}>: <@{slack_id}> promoted to bot administrator.",
        blocks=[
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"✅ *Approved by <@{approver_id}>:* <@{slack_id}> promoted to bot administrator in `roster.json`.\n_Note: Requires `@p-bot restart` to reload._",
                },
            }
        ],
    )
    slack_io.tell(client, slack_id, "🎉 You have been added as a P-Bot administrator! The next `@p-bot restart` will pick this up.")
    log.info("Admin %s approved admin promotion for %s", approver_id, slack_id)


def handle_approve_new_vendor(client, approver_id: str, channel_id: str, msg_ts: str, vendor_name: str):
    """Admin approved adding a vendor to the catalog in the alerts channel."""
    roster.add_vendor(vendor_name)
    client.chat_update(
        channel=channel_id,
        ts=msg_ts,
        text=f"✅ Approved by <@{approver_id}>: Vendor '{vendor_name}' added to Workday catalog list.",
        blocks=[
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"✅ *Approved by <@{approver_id}>:* Vendor *{vendor_name}* added to Workday catalog in `roster.json`.\n_Note: Requires `@p-bot restart` to reload in dropdowns._",
                },
            }
        ],
    )
    log.info("Admin %s approved new vendor '%s'", approver_id, vendor_name)

