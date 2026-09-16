"""The Slack side. Everything here is plumbing - the thinking is in the other files.

Flow of operations:

    1. Approval & Logging:
       Someone posts an EPIF pdf in #hirst-lab or a DM
         -> Charlie replies in that thread: "@p-bot approved" (or DMs the bot)
          -> Bot parses & validates EPIF, saves PDF to EPIFs/, logs row in Purchasing-Log.xlsx (via Lock Queue).
          -> Charlie names responsible buyer (@Dylan @Purchasing approved) or leaves unassigned.
          -> Assigned buyer receives pre-drafted email template via DM.

    2. Assignment / Handoffs:
       Buyer replies: "@Purchasing assign" to take an unassigned order, or approver/assignee reassigns.

    3. Submission / Cart Adjustments:
       Grad student replies: "@p-bot processed $152.49" (or "submitted" as a silent alias)
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
import json
import logging
import os
import sys
import time
import traceback
from datetime import datetime
from logging.handlers import RotatingFileHandler

from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler

try:
    from . import (
        admin,
        blocks,
        config,
        heartbeat,
        interview,
        lifecycle,
        ops,
        queue_worker,
        roster,
        slack_io,
        text_rules,
    )
except ImportError:
    import admin
    import blocks
    import config
    import heartbeat
    import interview
    import lifecycle
    import ops
    import queue_worker
    import roster
    import slack_io
    import text_rules


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
# token_verification_enabled=False avoids an auth.test network call on import/tests.
app = App(
    token=os.environ.get("SLACK_BOT_TOKEN"),
    token_verification_enabled=False,
)


@app.middleware
def log_request(body, next):
    """Global Bolt middleware to log incoming requests and execution outcomes/timings."""
    kind, ident, user_id, channel_id, is_verbose = text_rules.extract_request_info(body)
    user_name = None
    if user_id and hasattr(roster, "get_requesters"):
        user_name = roster.get_requesters().get(user_id)
    user_str = f"{user_id} ({user_name})" if user_name else (user_id or "unknown_user")
    chan_str = f" in {channel_id}" if channel_id else ""

    if is_verbose:
        log.debug("Incoming %s [%s] from %s%s", kind, ident, user_str, chan_str)
    else:
        log.info("Incoming %s [%s] from %s%s", kind, ident, user_str, chan_str)

    start = time.monotonic()
    try:
        return next()
    except Exception as e:
        log.exception("Handler raised exception for %s [%s] from %s: %s", kind, ident, user_str, e)
        raise
    finally:
        elapsed_ms = (time.monotonic() - start) * 1000
        if elapsed_ms > 2000:
            log.warning("Completed %s [%s] from %s in %.1f ms (> 2000 ms threshold)", kind, ident, user_str, elapsed_ms)
        else:
            if is_verbose:
                log.debug("Completed %s [%s] from %s in %.1f ms", kind, ident, user_str, elapsed_ms)
            else:
                log.info("Completed %s [%s] from %s in %.1f ms", kind, ident, user_str, elapsed_ms)


# --- Slash Commands -----------------------------------------------------------

@app.command("/new-purchase")
def handle_new_purchase_command(ack, body, client):
    """Open Screen 1 when user runs /new-purchase slash command."""
    ack()
    user_id = body.get("user_id")
    requester = slack_io.resolve_requester(client, user_id)
    modal = blocks.build_stage1_view(prefill_name_field=(requester is None), resolved_name=requester, user_id=user_id)
    try:
        client.views_open(trigger_id=body["trigger_id"], view=modal)
        log.info("Opened interview modal (Screen 1) from /new-purchase for user %s", user_id)
    except Exception as e:
        log.error("Failed to open interview modal from /new-purchase: %s", e)


@app.command("/purchasing-help")
def handle_purchasing_help_command(ack, respond):
    """Display help and command reference ephemerally."""
    ack()
    try:
        respond(text=blocks.get_help_message())
        log.info("Responded with help message for /purchasing-help")
    except Exception as e:
        log.error("Failed to respond to /purchasing-help: %s", e)


@app.command("/blank-template")
def handle_blank_template_command(ack, body, client):
    """Download blank EPIF PDF template and guide from slash command."""
    ack()
    channel_id = body.get("channel_id")
    user_id = body.get("user_id")

    def say(text, thread_ts=None):
        kw = {"channel": channel_id, "text": text}
        if thread_ts:
            kw["thread_ts"] = thread_ts
        client.chat_postMessage(**kw)

    try:
        ops.handle_template_command(client, say, channel=channel_id, thread_ts=None, user_id=user_id)
        log.info("Dispatched /blank-template command for user %s in channel %s", user_id, channel_id)
    except Exception as e:
        log.error("Failed to process /blank-template: %s", e)


@app.command("/roster-list")
def handle_roster_list_command(ack, body, respond):
    """Display registered members and vendor catalog list ephemerally."""
    ack()
    user_id = body.get("user_id")

    requesters_dict = roster.get_requesters() if hasattr(roster, "get_requesters") else {}
    vendors_list = roster.get_vendors() if hasattr(roster, "get_vendors") else []
    is_admin = admin.is_admin_user(user_id)

    lines = ["📋 *P-Bot Roster & Vendor List*\n"]

    lines.append("*Registered Lab Members:*")
    if requesters_dict:
        for uid, name in sorted(requesters_dict.items(), key=lambda x: x[1]):
            lines.append(f"• <@{uid}> → *{name}*")
    else:
        lines.append("No members registered yet. Use `/roster-set-name` to link your Slack account to your name.")
    lines.append("")

    if is_admin:
        admins_list = roster.get_admins() if hasattr(roster, "get_admins") else []
        approvers_list = roster.get_approvers() if hasattr(roster, "get_approvers") else []
        buyers_list = roster.get_buyers() if hasattr(roster, "get_buyers") else []
        lines.append("*Bot Administrators:*")
        lines.append(", ".join(f"<@{a}>" for a in admins_list) if admins_list else "None")
        lines.append("")
        lines.append("*Purchase Approvers:*")
        lines.append(", ".join(f"<@{a}>" for a in approvers_list) if approvers_list else "None")
        lines.append("")
        lines.append("*Purchase Buyers:*")
        lines.append(", ".join(f"<@{b}>" for b in buyers_list) if buyers_list else "None")
        lines.append("")

    count = len(vendors_list)
    lines.append(f"*Workday Punchout Vendors ({count}):*")
    lines.append(", ".join(vendors_list) if vendors_list else "None")

    msg_text = "\n".join(lines)
    try:
        respond(text=msg_text)
        log.info("Responded to /roster-list for user %s", user_id)
    except Exception as e:
        log.error("Failed to respond to /roster-list: %s", e)


@app.command("/roster-set-name")
def handle_roster_set_name_command(ack, body, client):
    """Open modal to link Slack account to a requester name in config.VALID_REQUESTERS."""
    ack()
    trigger_id = body.get("trigger_id")
    user_id = body.get("user_id")
    channel_id = body.get("channel_id")

    valid_list = ", ".join(sorted(config.VALID_REQUESTERS))
    modal = {
        "type": "modal",
        "callback_id": config.ROSTER_SET_NAME_CALLBACK_ID,
        "title": {"type": "plain_text", "text": "Set Roster Name"},
        "submit": {"type": "plain_text", "text": "Submit"},
        "close": {"type": "plain_text", "text": "Cancel"},
        "private_metadata": json.dumps({"user_id": user_id, "channel_id": channel_id}),
        "blocks": [
            {
                "type": "context",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": f"💡 *Note:* Your name must match one of the existing lab names:\n`{valid_list}`",
                    }
                ],
            },
            {
                "type": "input",
                "block_id": "block_proposed_name",
                "element": {
                    "type": "plain_text_input",
                    "action_id": "proposed_name",
                    "placeholder": {"type": "plain_text", "text": "e.g. Isaac, Dylan, Smeet"},
                },
                "label": {"type": "plain_text", "text": "Your Name in Lab Requester List"},
            },
        ],
    }

    try:
        client.views_open(trigger_id=trigger_id, view=modal)
    except Exception as e:
        log.error("Failed to open /roster-set-name modal: %s", e)


# --- View Submissions ---------------------------------------------------------

@app.view(config.ROSTER_SET_NAME_CALLBACK_ID)
def handle_roster_set_name_submit(ack, body, client, view):
    """Process submission of /roster-set-name modal."""
    values = view.get("state", {}).get("values", {})
    metadata = json.loads(view.get("private_metadata") or "{}")
    user_id = metadata.get("user_id") or body.get("user", {}).get("id")
    channel_id = metadata.get("channel_id")

    name_val = str(text_rules._extract_modal_field(values, "block_proposed_name", "proposed_name") or "").strip()
    if not name_val:
        ack(response_action="errors", errors={"block_proposed_name": "Please enter your name."})
        return

    # Validate against config.VALID_REQUESTERS
    valid_map = {r.lower(): r for r in config.VALID_REQUESTERS}
    if name_val.lower() not in valid_map:
        valid_list = ", ".join(sorted(config.VALID_REQUESTERS))
        ack(response_action="errors", errors={"block_proposed_name": f"Name '{name_val}' is not recognized. Must match one of: {valid_list}"})
        return

    matched_name = valid_map[name_val.lower()]

    # Check if user is ALREADY in the roster
    requesters = roster.get_requesters() if hasattr(roster, "get_requesters") else {}
    if user_id in requesters:
        current_name = requesters[user_id]
        ack()
        msg = f"You are already registered in the roster as *{current_name}*."
        if channel_id:
            try:
                client.chat_postEphemeral(channel=channel_id, user=user_id, text=msg)
            except Exception:
                slack_io.tell(client, user_id, msg)
        else:
            slack_io.tell(client, user_id, msg)
        return

    # User not in roster yet -> ack and post to ADMIN_ALERT_CHANNEL reusing approve_new_requester
    ack()

    if config.ADMIN_ALERT_CHANNEL:
        try:
            client.chat_postMessage(
                channel=config.ADMIN_ALERT_CHANNEL,
                text=f"⚠️ User <@{user_id}> requested to link their Slack account to '{matched_name}'.",
                blocks=[
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": (
                                f"⚠️ *New Lab Member Approval Needed:*\n"
                                f"User: <@{user_id}> (`{user_id}`)\n"
                                f"Proposed Requester Name: *{matched_name}*\n"
                                f"Approve adding them to `roster.json`?"
                            ),
                        },
                    },
                    {
                        "type": "actions",
                        "elements": [
                            {
                                "type": "button",
                                "text": {"type": "plain_text", "text": "Approve New Member"},
                                "style": "primary",
                                "action_id": "approve_new_requester",
                                "value": json.dumps({"slack_id": user_id, "name": matched_name}),
                            }
                        ],
                    },
                ],
            )
        except Exception as e:
            log.warning("Could not post new requester alert to admin channel: %s", e)

    slack_io.tell(client, user_id, f"Your request to link your Slack account as *{matched_name}* has been sent to admins for approval.")


@app.view(config.STAGE1_CALLBACK_ID)
def handle_stage1_submit(ack, body, client, view):
    """Validate Screen 1 (Which path?) and advance to Screen 2."""
    values = view.get("state", {}).get("values", {})
    metadata = json.loads(view.get("private_metadata") or "{}")
    user_id = metadata.get("user_id") or body.get("user", {}).get("id")
    resolved_name = metadata.get("resolved_name")

    proposed_name_val = text_rules._extract_modal_field(values, "block_proposed_name", "proposed_name")
    if proposed_name_val:
        requester = str(proposed_name_val).strip()
        is_pending_name = True
    else:
        requester = resolved_name
        is_pending_name = False

    vendor_choice = text_rules._extract_modal_field(values, "block_vendor", "vendor_select", field_type="selected_option") or ""
    vendor_custom = str(text_rules._extract_modal_field(values, "block_vendor_custom", "vendor_custom") or "").strip()

    errors = interview.validate_stage1(vendor_choice, vendor_custom)
    if not vendor_choice:
        errors["block_vendor"] = "Please select a vendor."

    if errors:
        ack(response_action="errors", errors=errors)
        return

    route = interview.route_vendor(vendor_choice)
    meta = {
        "resolved_name": requester,
        "user_id": user_id,
        "vendor_choice": vendor_choice,
        "vendor_custom": vendor_custom,
        "route": route,
        "is_pending_name": is_pending_name,
    }
    stage2_view = blocks.build_stage2_view(meta)
    ack(response_action="update", view=stage2_view)


@app.view(config.STAGE2_CALLBACK_ID)
def handle_stage2_submit(ack, body, client, view):
    """Process Screen 2 (Details) and either advance to Screen 3 or finalize."""
    values = view.get("state", {}).get("values", {})
    meta = json.loads(view.get("private_metadata") or "{}")
    route = meta.get("route", "workday")

    payment_method_val = (
        text_rules._extract_modal_field(values, "block_payment_method", "payment_method", field_type="selected_option")
        if route == "epif"
        else config.WORKDAY_PAYMENT_METHOD
    )

    stage2 = {
        "item_description": text_rules._extract_modal_field(values, "block_item_description", "item_description"),
        "purpose": text_rules._extract_modal_field(values, "block_purpose", "purpose"),
        "total_price": text_rules._extract_modal_field(values, "block_total_price", "total_price"),
        "vendor_contact_name": text_rules._extract_modal_field(values, "block_vendor_contact_name", "vendor_contact_name"),
        "vendor_contact_email": text_rules._extract_modal_field(values, "block_vendor_contact_email", "vendor_contact_email"),
        "date_of_purchase": text_rules._extract_modal_field(values, "block_date_of_purchase", "date_of_purchase", field_type="selected_date"),
        "delivery_room": text_rules._extract_modal_field(values, "block_delivery_room", "delivery_room", field_type="selected_option"),
        "project_id": text_rules._extract_modal_field(values, "block_project_id", "project_id", field_type="selected_option"),
        "fund": text_rules._extract_modal_field(values, "block_fund", "fund", field_type="selected_option"),
        "category": text_rules._extract_modal_field(values, "block_category", "category", field_type="selected_option"),
        "payment_method": payment_method_val,
    }

    category = stage2.get("category")
    if interview.needs_asset_details(category):
        meta["stage2"] = stage2
        stage3_view = blocks.build_stage3_view(meta)
        ack(response_action="update", view=stage3_view)
    else:
        lifecycle._process_interview_completion(ack, client, body, meta, stage2, stage3=None)


@app.view(config.STAGE3_CALLBACK_ID)
def handle_stage3_submit(ack, body, client, view):
    """Process Screen 3 (Fabrication details) and finalize purchase request."""
    values = view.get("state", {}).get("values", {})
    meta = json.loads(view.get("private_metadata") or "{}")
    stage2 = meta.get("stage2", {})

    stage3 = {
        "asset_id": text_rules._extract_modal_field(values, "block_asset_id", "asset_id"),
        "name_of_system": text_rules._extract_modal_field(values, "block_name_of_system", "name_of_system"),
    }
    lifecycle._process_interview_completion(ack, client, body, meta, stage2, stage3=stage3)


# --- Alerts-Channel Interactive Action Handlers (Phase 2) --------------------

@app.action("approve_new_requester")
def handle_approve_new_requester_action(ack, body, respond, client):
    """Handle admin clicking 'Approve New Member' in the alerts channel."""
    ack()
    approver_id = body.get("user", {}).get("id")
    channel_id = body.get("channel", {}).get("id")
    msg_ts = body.get("message", {}).get("ts")

    if not admin.is_admin_user(approver_id):
        log.warning("Non-admin %s attempted to approve new requester", approver_id)
        respond(text="🔒 Only bot administrators can approve new lab members.")
        return

    val_str = body.get("actions", [{}])[0].get("value", "{}")
    try:
        val_data = json.loads(val_str)
        slack_id = val_data["slack_id"]
        name = val_data["name"]
        roster.add_requester(slack_id, name)

        client.chat_update(
            channel=channel_id,
            ts=msg_ts,
            text=f"✅ Approved by <@{approver_id}>: <@{slack_id}> added as '{name}' (Takes effect on next `@p-bot restart`).",
            blocks=[
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"✅ *Approved by <@{approver_id}>:* <@{slack_id}> added as *{name}* in `roster.json`.\n_Note: Requires `@p-bot restart` to reload._",
                    },
                }
            ],
        )
        slack_io.tell(client, slack_id, f"🎉 You're approved as '{name}'! The next `@p-bot restart` will pick this up.")
        log.info("Admin %s approved new requester %s (%s)", approver_id, slack_id, name)
    except Exception as e:
        log.error("Failed to approve new requester: %s", e)


@app.action("approve_new_admin")
def handle_approve_new_admin_action(ack, body, respond, client):
    """Handle admin clicking 'Approve Admin Promotion' in the alerts channel."""
    ack()
    approver_id = body.get("user", {}).get("id")
    channel_id = body.get("channel", {}).get("id")
    msg_ts = body.get("message", {}).get("ts")

    if not admin.is_admin_user(approver_id):
        log.warning("Non-admin %s attempted to approve admin promotion", approver_id)
        respond(text="🔒 Only bot administrators can approve admin promotions.")
        return

    val_str = body.get("actions", [{}])[0].get("value", "{}")
    try:
        val_data = json.loads(val_str)
        slack_id = val_data["slack_id"]
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
    except Exception as e:
        log.error("Failed to approve admin promotion: %s", e)


@app.action("approve_new_vendor")
def handle_approve_new_vendor_action(ack, body, respond, client):
    """Handle admin clicking 'Approve Vendor' in the alerts channel."""
    ack()
    approver_id = body.get("user", {}).get("id")
    channel_id = body.get("channel", {}).get("id")
    msg_ts = body.get("message", {}).get("ts")

    if not admin.is_admin_user(approver_id):
        log.warning("Non-admin %s attempted to approve vendors", approver_id)
        respond(text="🔒 Only bot administrators can approve vendors.")
        return

    val_str = body.get("actions", [{}])[0].get("value", "{}")
    try:
        val_data = json.loads(val_str)
        vendor_name = val_data["vendor"]
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
    except Exception as e:
        log.error("Failed to approve vendor: %s", e)


# --- Lifecycle Interactive Action Handlers (T2) -------------------------------

@app.action("req_approve")
def handle_req_approve_action(ack, body, respond, client):
    """Handle clicking 'Approve' button on purchase request message."""
    ack()
    user_id = body.get("user", {}).get("id")
    channel_id = body.get("channel", {}).get("id")
    msg_ts = body.get("message", {}).get("ts")
    if not admin.is_approved_reviewer(user_id):
        log.warning("Unauthorized user %s attempted to approve purchase request", user_id)
        respond(text="🔒 Only authorized approvers can approve purchase requests.")
        return

    action = body.get("actions", [{}])[0]
    val_data = json.loads(action.get("value") or "{}")
    req_data = val_data.get("request", {})
    history = list(val_data.get("history", []))
    thread_ts = (
        body.get("container", {}).get("thread_ts")
        or val_data.get("thread_ts")
        or req_data.get("thread_ts")
        or msg_ts
    )

    now_str = datetime.now().strftime("%m/%d/%y %H:%M")
    user_name = slack_io.resolve_requester(client, user_id) or f"<@{user_id}>"
    history.append(f"Approved by {user_name} on {now_str}")

    def say(text, thread_ts=thread_ts, **kw):
        client.chat_postMessage(channel=channel_id, text=text, thread_ts=thread_ts, **kw)

    lifecycle.handle_epif_processing(
        client=client,
        say=say,
        channel=channel_id,
        thread_ts=thread_ts,
        approver=user_id,
        event_ts=msg_ts,
    )

    next_blocks = blocks.build_request_blocks("approved", req_data, history=history)
    try:
        client.chat_update(
            channel=channel_id,
            ts=msg_ts,
            text="🛒 Purchase Request (Approved)",
            blocks=next_blocks,
        )
        log.info("Purchase request message updated to 'approved' by %s in channel %s (ts: %s)", user_id, channel_id, msg_ts)
    except Exception as e:
        log.error("Failed to update message on req_approve: %s", e)


@app.action("req_processed")
def handle_req_processed_action(ack, body, respond, client):
    """Handle clicking 'Mark Processed' button on purchase request message."""
    ack()
    user_id = body.get("user", {}).get("id")
    channel_id = body.get("channel", {}).get("id")
    msg_ts = body.get("message", {}).get("ts")
    thread_ts = body.get("container", {}).get("thread_ts") or msg_ts

    action = body.get("actions", [{}])[0]
    val_data = json.loads(action.get("value") or "{}")
    req_data = val_data.get("request", {})
    history = list(val_data.get("history", []))

    assignee_id = req_data.get("assignee_id")
    if not assignee_id:
        log.warning("User %s clicked req_processed on unassigned request", user_id)
        respond(text="⚠️ This request must be assigned to a buyer before it can be marked processed. Use `@Purchasing assign @buyer`.")
        return

    if not (user_id == assignee_id or admin.is_admin_user(user_id)):
        log.warning("Unauthorized user %s (not assignee %s or admin) clicked req_processed", user_id, assignee_id)
        respond(text=f"🔒 Only the assigned buyer (<@{assignee_id}>) or an admin can mark this request processed.")
        return

    requester_name = slack_io.resolve_requester(client, user_id)
    if not requester_name:
        log.warning("Unregistered user %s clicked req_processed", user_id)
        respond(text="🔒 You must be registered in the lab roster to update requests. Use `/roster-set-name` first.")
        return

    now_str = datetime.now().strftime("%m/%d/%y %H:%M")
    history.append(f"Processed by {requester_name} on {now_str}")

    def say(text, thread_ts=thread_ts, **kw):
        client.chat_postMessage(channel=channel_id, text=text, thread_ts=thread_ts, **kw)

    lifecycle.handle_processed(
        client=client,
        say=say,
        channel=channel_id,
        thread_ts=thread_ts,
        user_id=user_id,
        event_ts=msg_ts,
        text="",
    )

    next_blocks = blocks.build_request_blocks("processed", req_data, history=history)
    try:
        client.chat_update(
            channel=channel_id,
            ts=msg_ts,
            text="🛒 Purchase Request (Processed)",
            blocks=next_blocks,
        )
        log.info("Purchase request message updated to 'processed' by %s in channel %s (ts: %s)", user_id, channel_id, msg_ts)
    except Exception as e:
        log.error("Failed to update message on req_processed: %s", e)


@app.action("req_decline")
def handle_req_decline_action(ack, body, respond, client):
    """Handle clicking 'Decline' button on a posted purchase request message."""
    ack()
    user_id = body.get("user", {}).get("id")
    channel_id = body.get("channel", {}).get("id")
    msg_ts = body.get("message", {}).get("ts")

    if not admin.is_approved_reviewer(user_id):
        log.warning("Unauthorized user %s attempted to decline purchase request", user_id)
        respond(text="🔒 Only authorized approvers can decline purchase requests.")
        return

    action = body.get("actions", [{}])[0]
    val_data = json.loads(action.get("value") or "{}")
    req_data = val_data.get("request", {})
    history = list(val_data.get("history", []))

    lifecycle.handle_decline(client, channel_id, msg_ts, user_id, req_data, history)


@app.action("req_cancel")
def handle_req_cancel_action(ack, body, respond, client):
    """Handle clicking 'Cancel' button on an approved or claimed purchase request message."""
    ack()
    user_id = body.get("user", {}).get("id")
    channel_id = body.get("channel", {}).get("id")
    msg_ts = body.get("message", {}).get("ts")
    thread_ts = body.get("container", {}).get("thread_ts") or msg_ts

    if not (admin.is_approved_reviewer(user_id) or admin.is_admin_user(user_id)):
        log.warning("Unauthorized user %s attempted to cancel purchase request", user_id)
        respond(text="🔒 Only approvers and admins can cancel purchase requests.")
        return

    action = body.get("actions", [{}])[0]
    val_data = json.loads(action.get("value") or "{}")
    req_data = val_data.get("request", {})
    state = val_data.get("state", "")
    history = list(val_data.get("history", []))

    def say(text, thread_ts=thread_ts, **kw):
        client.chat_postMessage(channel=channel_id, text=text, thread_ts=thread_ts, **kw)

    lifecycle.handle_cancel(client, say, channel_id, thread_ts, msg_ts, user_id, req_data, state, history)


@app.action("req_confirmed")
def handle_req_confirmed_action(ack, body, respond, client):
    """Handle clicking 'Mark Confirmed' button on purchase request message."""
    ack()
    user_id = body.get("user", {}).get("id")
    channel_id = body.get("channel", {}).get("id")
    msg_ts = body.get("message", {}).get("ts")
    thread_ts = body.get("container", {}).get("thread_ts") or msg_ts

    action = body.get("actions", [{}])[0]
    val_data = json.loads(action.get("value") or "{}")
    req_data = val_data.get("request", {})
    history = list(val_data.get("history", []))

    assignee_id = req_data.get("assignee_id")
    if not (user_id == assignee_id or admin.is_admin_user(user_id)):
        log.warning("Unauthorized user %s (not assignee %s or admin) clicked req_confirmed", user_id, assignee_id)
        respond(text="🔒 Only the assigned buyer or an admin can update this request.")
        return

    requester_name = slack_io.resolve_requester(client, user_id)
    if not requester_name:
        log.warning("Unregistered user %s clicked req_confirmed", user_id)
        respond(text="🔒 You must be registered in the lab roster to update requests. Use `/roster-set-name` first.")
        return

    now_str = datetime.now().strftime("%m/%d/%y %H:%M")
    history.append(f"Confirmed by {requester_name} on {now_str}")

    def say(text, thread_ts=thread_ts, **kw):
        client.chat_postMessage(channel=channel_id, text=text, thread_ts=thread_ts, **kw)

    lifecycle.handle_confirmation(
        client=client,
        say=say,
        channel=channel_id,
        thread_ts=thread_ts,
        user_id=user_id,
        event_ts=msg_ts,
        text="",
        files=None,
    )

    next_blocks = blocks.build_request_blocks("confirmed", req_data, history=history)
    try:
        client.chat_update(
            channel=channel_id,
            ts=msg_ts,
            text="🛒 Purchase Request (Confirmed)",
            blocks=next_blocks,
        )
        log.info("Purchase request message updated to 'confirmed' by %s in channel %s (ts: %s)", user_id, channel_id, msg_ts)
    except Exception as e:
        log.error("Failed to update message on req_confirmed: %s", e)


@app.action("req_delivered")
def handle_req_delivered_action(ack, body, respond, client):
    """Handle clicking 'Mark Delivered' button on purchase request message."""
    ack()
    user_id = body.get("user", {}).get("id")
    channel_id = body.get("channel", {}).get("id")
    msg_ts = body.get("message", {}).get("ts")
    thread_ts = body.get("container", {}).get("thread_ts") or msg_ts

    action = body.get("actions", [{}])[0]
    val_data = json.loads(action.get("value") or "{}")
    req_data = val_data.get("request", {})
    history = list(val_data.get("history", []))

    assignee_id = req_data.get("assignee_id")
    if not (user_id == assignee_id or admin.is_admin_user(user_id)):
        log.warning("Unauthorized user %s (not assignee %s or admin) clicked req_delivered", user_id, assignee_id)
        respond(text="🔒 Only the assigned buyer or an admin can update this request.")
        return

    requester_name = slack_io.resolve_requester(client, user_id)
    if not requester_name:
        log.warning("Unregistered user %s clicked req_delivered", user_id)
        respond(text="🔒 You must be registered in the lab roster to update requests. Use `/roster-set-name` first.")
        return

    now_str = datetime.now().strftime("%m/%d/%y %H:%M")
    history.append(f"Delivered to {requester_name} on {now_str}")

    def say(text, thread_ts=thread_ts, **kw):
        client.chat_postMessage(channel=channel_id, text=text, thread_ts=thread_ts, **kw)

    lifecycle.handle_delivery(
        client=client,
        say=say,
        channel=channel_id,
        thread_ts=thread_ts,
        user_id=user_id,
        event_ts=msg_ts,
        text="",
    )

    next_blocks = blocks.build_request_blocks("delivered", req_data, history=history)
    try:
        client.chat_update(
            channel=channel_id,
            ts=msg_ts,
            text="🛒 Purchase Request (Delivered)",
            blocks=next_blocks,
        )
        log.info("Purchase request message updated to 'delivered' by %s in channel %s (ts: %s)", user_id, channel_id, msg_ts)
    except Exception as e:
        log.error("Failed to update message on req_delivered: %s", e)


@app.action("start_purchase_interview")
def handle_start_purchase_interview(ack, body, client):
    """Open Screen 1 when user clicks 'New Purchase Request' in App Home."""
    ack()
    user_id = body.get("user", {}).get("id")
    requester = slack_io.resolve_requester(client, user_id)
    modal = blocks.build_stage1_view(prefill_name_field=(requester is None), resolved_name=requester, user_id=user_id)
    try:
        client.views_open(trigger_id=body["trigger_id"], view=modal)
        log.info("Opened interview modal (Screen 1) from App Home button for user %s", user_id)
    except Exception as e:
        log.error("Failed to open interview modal from button: %s", e)


# --- Dispatcher Helpers -------------------------------------------------------

_CACHED_BOT_USER_ID = None


def get_bot_user_id(client, context=None) -> str | None:
    """Resolve and cache the bot's own Slack user ID."""
    global _CACHED_BOT_USER_ID
    if context and context.get("bot_user_id"):
        _CACHED_BOT_USER_ID = context.get("bot_user_id")
        return _CACHED_BOT_USER_ID
    if _CACHED_BOT_USER_ID:
        return _CACHED_BOT_USER_ID
    if client:
        try:
            auth = client.auth_test()
            if isinstance(auth, dict) and auth.get("user_id"):
                _CACHED_BOT_USER_ID = auth.get("user_id")
                return _CACHED_BOT_USER_ID
        except Exception as e:
            log.warning("Failed to get bot_user_id from auth_test: %s", e)
    return None


def dispatch_command(
    client, say, channel: str, thread_ts: str, user: str, event_ts: str, text: str,
    files=None, direct_file=None, bot_user_id: str | None = None,
):
    """Single dispatch point for all app_mention and direct message commands."""
    if not bot_user_id:
        bot_user_id = get_bot_user_id(client)
    stripped_text, user_mentions, group_mentions = text_rules.parse_mentions(text, bot_user_id=bot_user_id)
    text_lower = stripped_text.lower()

    if any(kw in text_lower for kw in config.HELP_KEYWORDS):
        say(text=blocks.get_help_message(), thread_ts=thread_ts)
    elif any(kw in text_lower for kw in config.STATUS_KEYWORDS):
        ops.handle_health_status(client, say, channel, thread_ts)
    elif any(kw in text_lower for kw in config.QUEUE_KEYWORDS):
        ops.handle_queue_status(client, say, channel, thread_ts)
    elif any(kw in text_lower for kw in config.LOGS_KEYWORDS):
        ops.handle_logs(client, say, channel, thread_ts, user, text)
    elif any(kw in text_lower for kw in config.UPDATE_KEYWORDS):
        ops.handle_update(client, say, channel, thread_ts, user)
    elif any(kw in text_lower for kw in config.RESTART_KEYWORDS):
        ops.handle_restart(client, say, channel, thread_ts, user)
    elif any(kw in text_lower for kw in config.PROMOTE_ADMIN_KEYWORDS):
        ops.handle_promote_admin(client, say, channel, thread_ts, user, text)
    elif any(kw in text_lower for kw in config.ADD_APPROVER_KEYWORDS):
        ops.handle_add_approver(client, say, channel, thread_ts, user, text)
    elif any(kw in text_lower for kw in config.REMOVE_APPROVER_KEYWORDS):
        ops.handle_remove_approver(client, say, channel, thread_ts, user, text)
    elif any(kw in text_lower for kw in config.ADD_BUYER_KEYWORDS):
        ops.handle_add_buyer(client, say, channel, thread_ts, user, text)
    elif any(kw in text_lower for kw in config.REMOVE_BUYER_KEYWORDS):
        ops.handle_remove_buyer(client, say, channel, thread_ts, user, text)
    elif any(kw in text_lower for kw in config.REMOVE_VENDOR_KEYWORDS):
        ops.handle_remove_vendor(client, say, channel, thread_ts, user, text)
    elif any(kw in text_lower for kw in config.TEMPLATE_KEYWORDS):
        ops.handle_template_command(client, say, channel, thread_ts, user)
    elif any(kw in text_lower for kw in config.QUOTE_KEYWORDS):
        lifecycle.handle_quote(client, say, channel, thread_ts, event_ts, files)
    elif any(kw in text_lower for kw in config.ASSIGN_KEYWORDS):
        if group_mentions:
            say(text=f"⚠️ Cannot assign to a user group (<!subteam^{group_mentions[0]}>). Please name a specific person.", thread_ts=thread_ts)
            return
        if len(user_mentions) > 1:
            users_str = ", ".join(f"<@{u}>" for u in user_mentions)
            say(text=f"⚠️ Multiple buyers mentioned ({users_str}). Please name exactly one person to assign this order.", thread_ts=thread_ts)
            return
        target_uid = user_mentions[0] if user_mentions else user
        lifecycle.handle_assign(
            client=client,
            say=say,
            channel=channel,
            thread_ts=thread_ts,
            user_id=user,
            event_ts=event_ts,
            target_user_id=target_uid,
        )
    elif any(kw in text_lower for kw in config.PROCESSED_KEYWORDS):
        lifecycle.handle_processed(client, say, channel, thread_ts, user, event_ts, text)
    elif any(kw in text_lower for kw in config.CONFIRM_KEYWORDS):
        lifecycle.handle_confirmation(client, say, channel, thread_ts, user, event_ts, text, files)
    elif any(kw in text_lower for kw in config.DELIVERED_KEYWORDS):
        lifecycle.handle_delivery(client, say, channel, thread_ts, user, event_ts, text)
    elif config.TRIGGER_KEYWORD in text_lower or direct_file or any(w in text_lower for w in ("check", "test")):
        if not admin.is_approved_reviewer(user):
            log.warning("Unauthorized user %s attempted to approve purchase request", user)
            say(text="🔒 Only Charlie Hirst can approve purchase requests.", thread_ts=thread_ts)
            return

        row = slack_io.find_row_in_thread(client, channel, thread_ts)
        _, _, _, card_state = slack_io.find_card_in_thread(client, channel, thread_ts)
        if row is not None or card_state in ("approved", "processed", "confirmed", "delivered"):
            # Already approved thread: treat as reassignment, do not perform a second Excel write
            if group_mentions:
                say(text=f"⚠️ Cannot assign to a user group (<!subteam^{group_mentions[0]}>). Please name a specific person.", thread_ts=thread_ts)
                return
            if len(user_mentions) > 1:
                users_str = ", ".join(f"<@{u}>" for u in user_mentions)
                say(text=f"⚠️ Multiple buyers mentioned ({users_str}). Please name exactly one person to assign this order.", thread_ts=thread_ts)
                return
            target_uid = user_mentions[0] if user_mentions else None
            if target_uid:
                lifecycle.handle_assign(
                    client=client,
                    say=say,
                    channel=channel,
                    thread_ts=thread_ts,
                    user_id=user,
                    event_ts=event_ts,
                    target_user_id=target_uid,
                )
            else:
                say(text="⚠️ This request is already approved. To reassign it, mention a buyer: `@Purchasing assign @buyer`.", thread_ts=thread_ts)
            return

        # New approval
        if group_mentions:
            refusal_msg = f"⚠️ Cannot assign to a user group (<!subteam^{group_mentions[0]}>). Please name a specific person."
            assignee_id = None
            assignee_name = None
        elif len(user_mentions) > 1:
            users_str = ", ".join(f"<@{u}>" for u in user_mentions)
            refusal_msg = f"⚠️ Multiple buyers mentioned ({users_str}). Please name exactly one person to assign this order."
            assignee_id = None
            assignee_name = None
        elif len(user_mentions) == 1:
            cand_id = user_mentions[0]
            if not roster.is_buyer(cand_id):
                refusal_msg = f"⚠️ <@{cand_id}> isn't on the buyers list, so I can't assign this to them. An admin can add them: @Purchasing add-buyer <@{cand_id}>"
                assignee_id = None
                assignee_name = None
            else:
                cand_name = slack_io.resolve_requester(client, cand_id)
                if not cand_name:
                    refusal_msg = f"🔒 <@{cand_id}> must be registered in the lab roster to be assigned requests. Use `/roster-set-name` first."
                    assignee_id = None
                    assignee_name = None
                else:
                    assignee_id = cand_id
                    assignee_name = cand_name
                    refusal_msg = None
        else:
            assignee_id = None
            assignee_name = None
            refusal_msg = None

        lifecycle.handle_epif_processing(
            client, say, channel, thread_ts, user, event_ts,
            direct_file=direct_file, direct_poster=user if direct_file else None,
            assignee_id=assignee_id, assignee_name=assignee_name, refusal_msg=refusal_msg,
        )


@app.event("app_mention")
def on_mention(event, client, say, context=None):
    text = event.get("text", "")
    channel = event["channel"]
    thread_ts = event.get("thread_ts") or event["ts"]
    user = event.get("user")
    event_ts = event["ts"]
    files = event.get("files", [])
    bot_user_id = context.get("bot_user_id") if context else None

    log.info("Received app_mention from user %s in channel %s: '%s'", user, channel, text)
    dispatch_command(client, say, channel, thread_ts, user, event_ts, text, files=files, bot_user_id=bot_user_id)


@app.event("message")
def on_direct_message(event, client, say, context=None):
    # Ignore bot's own messages and messages with bot subtype
    if event.get("subtype") == "bot_message" or event.get("bot_id"):
        return

    user = event.get("user")
    channel = event.get("channel", "")
    thread_ts = event.get("thread_ts") or event.get("ts")
    event_ts = event.get("ts")
    text = event.get("text", "")
    channel_type = event.get("channel_type")
    bot_user_id = context.get("bot_user_id") if context else None

    # If it is a Direct Message (DM)
    if channel_type == "im":
        log.info("Received DM from user %s: '%s'", user, text)

        # 1. Check FAQ layer first
        faq_answer = interview.match_faq(text)
        if faq_answer:
            log.info("Matched FAQ query from user %s: '%s'", user, text)
            say(text=faq_answer, thread_ts=thread_ts)
            return

        # Look for files attached in this direct message
        files = event.get("files", [])
        pdf_files = [f for f in files if f.get("name", "").lower().endswith(".pdf")]
        direct_file = pdf_files[0] if pdf_files else None

        dispatch_command(
            client, say, channel, thread_ts, user, event_ts, text,
            files=files, direct_file=direct_file, bot_user_id=bot_user_id,
        )
        return

    # Non-DM (Channel / Thread):
    # Ignore ordinary channel chatter if no PDF files attached
    files = event.get("files", [])
    pdf_files = [f for f in files if f.get("name", "").lower().endswith(".pdf")]
    if not pdf_files:
        return

    text_lower = text.lower()
    if any(kw in text_lower for kw in config.QUOTE_KEYWORDS):
        return
    if config.TRIGGER_KEYWORD in text_lower:
        return

    log.info("Detected PDF file dropped in channel %s (thread: %s) by user %s", channel, thread_ts, user)
    lifecycle.handle_epif_drop(
        client=client,
        say=say,
        channel=channel,
        thread_ts=thread_ts,
        user_id=user,
        file_obj=pdf_files[0],
        event_ts=event_ts,
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
            view=blocks.build_app_home_view(),
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
