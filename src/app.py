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
from logging.handlers import RotatingFileHandler

from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler

try:
    from . import (
        admin,
        blocks,
        bom,
        config,
        heartbeat,
        interview,
        lifecycle,
        ops,
        path_validator,
        queue_worker,
        roster,
        slack_io,
        text_rules,
    )
except ImportError:
    import admin
    import blocks
    import bom
    import config
    import heartbeat
    import interview
    import lifecycle
    import ops
    import path_validator
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
        slack_io.deny(respond, blocks.get_help_message())
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
        slack_io.deny(respond, msg_text)
        log.info("Responded to /roster-list for user %s", user_id)
    except Exception as e:
        log.error("Failed to respond to /roster-list: %s", e)


@app.command("/roster-set-name")
def handle_roster_set_name_command(ack, body, client):
    """Open modal to link Slack account to a requester name."""
    ack()
    trigger_id = body.get("trigger_id")
    user_id = body.get("user_id")
    channel_id = body.get("channel_id")
    current_name = roster.get_requesters().get(user_id) if hasattr(roster, "get_requesters") else None

    modal = blocks.build_roster_set_name_view(user_id, current_name, channel_id=channel_id)
    try:
        client.views_open(trigger_id=trigger_id, view=modal)
    except Exception as e:
        log.error("Failed to open /roster-set-name modal: %s", e)


# --- View Submissions ---------------------------------------------------------

@app.view(config.ROSTER_SET_NAME_CALLBACK_ID)
def handle_roster_set_name_submit(ack, body, client, view):
    """Process submission of /roster-set-name modal.

    WHY THIS EXISTS:
    ----------------
    Ticket 19: One command covering register, correct and rename.
    Four outcomes in strict order:
    1. Name another member holds -> field error in modal, nothing to alert channel (impersonation guard).
    2. Normalization-only change to own name -> applied immediately, nothing to alert channel.
    3. Different name for registered user (rename) -> alert channel for admin approval.
    4. Any name for unregistered user (registration) -> alert channel for admin approval.
    """
    values = view.get("state", {}).get("values", {})
    metadata = json.loads(view.get("private_metadata") or "{}")
    user_id = metadata.get("user_id") or body.get("user", {}).get("id")

    name_val = str(text_rules._extract_modal_field(values, "block_proposed_name", "proposed_name") or "").strip()
    if not name_val:
        ack(response_action="errors", errors={"block_proposed_name": "Please enter your name."})
        return

    requesters = roster.get_requesters() if hasattr(roster, "get_requesters") else {}
    norm_proposed = text_rules.normalize_requester_name(name_val)

    # 1. Impersonation guard: Name another member already holds
    for other_id, other_name in requesters.items():
        if other_id != user_id and other_id != other_name and text_rules.normalize_requester_name(other_name) == norm_proposed:
            ack(
                response_action="errors",
                errors={"block_proposed_name": f"The name '{name_val}' is already held by another lab member."},
            )
            return


    # 2. Normalization-only change to submitter's own name
    if user_id in requesters:
        current_name = requesters[user_id]
        if text_rules.normalize_requester_name(current_name) == norm_proposed:
            roster.add_requester(user_id, name_val)
            ack()
            slack_io.tell(client, user_id, f"✅ Your name has been updated to *{name_val}*.")
            log.info("User %s updated name normalization from '%s' to '%s'", user_id, current_name, name_val)
            return

    # 3. Different name for user already registered (Rename)
    if user_id in requesters:
        current_name = requesters[user_id]
        ack()
        if config.ADMIN_ALERT_CHANNEL:
            try:
                client.chat_postMessage(
                    channel=config.ADMIN_ALERT_CHANNEL,
                    text=f"⚠️ User <@{user_id}> requested to change their roster name from '{current_name}' to '{name_val}'.",
                    blocks=[
                        {
                            "type": "section",
                            "text": {
                                "type": "mrkdwn",
                                "text": (
                                    f"⚠️ *Lab Member Rename Approval Needed:*\n"
                                    f"User: <@{user_id}> (`{user_id}`)\n"
                                    f"Current Name: *{current_name}*\n"
                                    f"Proposed New Name: *{name_val}*\n"
                                    f"Approve renaming in `roster.json`?"
                                ),
                            },
                        },
                        {
                            "type": "actions",
                            "elements": [
                                {
                                    "type": "button",
                                    "text": {"type": "plain_text", "text": "Approve Rename"},
                                    "style": "primary",
                                    "action_id": "approve_new_requester",
                                    "value": json.dumps({"slack_id": user_id, "old_name": current_name, "new_name": name_val}),
                                }
                            ],
                        },
                    ],
                )
            except Exception as e:
                log.warning("Could not post rename alert to admin channel: %s", e)
        slack_io.tell(
            client,
            user_id,
            f"Your request to change your roster name from *{current_name}* to *{name_val}* has been sent to admins for approval.",
        )
        log.info("User %s requested rename from '%s' to '%s'", user_id, current_name, name_val)
        return

    # 4. Any name for user not in roster (Registration)
    ack()
    if config.ADMIN_ALERT_CHANNEL:
        try:
            client.chat_postMessage(
                channel=config.ADMIN_ALERT_CHANNEL,
                text=f"⚠️ User <@{user_id}> requested to link their Slack account to '{name_val}'.",
                blocks=[
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": (
                                f"⚠️ *New Lab Member Approval Needed:*\n"
                                f"User: <@{user_id}> (`{user_id}`)\n"
                                f"Proposed Requester Name: *{name_val}*\n"
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
                                "value": json.dumps({"slack_id": user_id, "name": name_val}),
                            }
                        ],
                    },
                ],
            )
        except Exception as e:
            log.warning("Could not post new requester alert to admin channel: %s", e)

    slack_io.tell(
        client,
        user_id,
        f"Your request to link your Slack account as *{name_val}* is waiting on an admin for approval.",
    )
    log.info("User %s requested new member registration as '%s'", user_id, name_val)



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
        "link": text_rules._extract_modal_field(values, "block_link", "link"),
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


@app.view(config.ITEMS_CALLBACK_ID)
def handle_items_modal_submit(ack, body, client, view):
    """Handle submission of line items modal."""
    values = view.get("state", {}).get("values", {})
    meta = json.loads(view.get("private_metadata") or "{}")
    channel = meta.get("channel")
    thread_ts = meta.get("thread_ts")
    card_ts = meta.get("card_ts")
    user_id = body.get("user", {}).get("id")

    raw_text = text_rules._extract_modal_field(values, "block_line_items", "action_line_items") or ""

    items, shipping, parse_errors = bom.parse_line_items(raw_text)
    if parse_errors:
        ack(response_action="errors", errors={"block_line_items": "\n".join(parse_errors)})
        return

    card_payload = slack_io.get_card_payload(client, channel, thread_ts, card_ts)
    if not card_payload:
        ack(response_action="errors", errors={"block_line_items": "Could not find request details for this card."})
        return

    card_state = card_payload.get("state", "posted")
    if card_state != "posted":
        ack(response_action="errors", errors={"block_line_items": "This purchase request has already been approved and line items can no longer be edited."})
        return

    parsed = card_payload.get("parsed") or {}
    total_price = parsed.get("total_price") if "total_price" in parsed else parsed.get("Amount of Purchase")

    total_error = bom.check_total(items, shipping, total_price)
    if total_error:
        ack(response_action="errors", errors={"block_line_items": total_error})
        return

    ack()

    lifecycle.handle_items_update(
        client=client,
        channel=channel,
        thread_ts=thread_ts,
        card_ts=card_ts,
        items=items,
        shipping=shipping,
        user_id=user_id,
    )



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
        slack_io.deny(respond, "🔒 Only bot administrators can approve new lab members.")
        return

    val_str = body.get("actions", [{}])[0].get("value", "{}")
    try:
        val_data = json.loads(val_str)
        slack_id = val_data["slack_id"]
        old_name = val_data.get("old_name")
        new_name = val_data.get("new_name") or val_data.get("name")
        if old_name:
            ops.handle_approve_rename_requester(client, approver_id, channel_id, msg_ts, slack_id, old_name, new_name)
        else:
            ops.handle_approve_new_requester(client, approver_id, channel_id, msg_ts, slack_id, new_name)
    except Exception as e:
        log.error("Failed to approve requester: %s", e)



@app.action("approve_new_admin")
def handle_approve_new_admin_action(ack, body, respond, client):
    """Handle admin clicking 'Approve Admin Promotion' in the alerts channel."""
    ack()
    approver_id = body.get("user", {}).get("id")
    channel_id = body.get("channel", {}).get("id")
    msg_ts = body.get("message", {}).get("ts")

    if not admin.is_admin_user(approver_id):
        log.warning("Non-admin %s attempted to approve admin promotion", approver_id)
        slack_io.deny(respond, "🔒 Only bot administrators can approve admin promotions.")
        return

    val_str = body.get("actions", [{}])[0].get("value", "{}")
    try:
        val_data = json.loads(val_str)
        slack_id = val_data["slack_id"]
        ops.handle_approve_new_admin(client, approver_id, channel_id, msg_ts, slack_id)
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
        slack_io.deny(respond, "🔒 Only bot administrators can approve vendors.")
        return

    val_str = body.get("actions", [{}])[0].get("value", "{}")
    try:
        val_data = json.loads(val_str)
        vendor_name = val_data["vendor"]
        ops.handle_approve_new_vendor(client, approver_id, channel_id, msg_ts, vendor_name)
    except Exception as e:
        log.error("Failed to approve new vendor: %s", e)
        log.error("Failed to approve vendor: %s", e)


# --- Lifecycle Interactive Action Handlers (T2) -------------------------------

@app.action("req_assign_select")
def handle_req_assign_select_action(ack, body, respond, client):
    """Handle selecting a buyer from the users_select picker on the posted card (ADR 0005).

    WHY THIS EXISTS:
    ----------------
    ADR 0005: A dropdown beside Approve on the posted card allows approvers to pick a buyer
    directly. Selecting a buyer does not approve anything; it re-renders the card with
    assignee_id set, updating the sibling Approve button's value so that when Approve is
    subsequently clicked, the assignment is carried into the row write and notification.
    The handler recovers the request payload from the sibling Approve button's value in
    body["message"]["blocks"], requiring no new state file.
    """
    ack()
    user_id = body.get("user", {}).get("id")
    channel_id = body.get("channel", {}).get("id")
    msg_ts = body.get("message", {}).get("ts")
    thread_ts = body.get("container", {}).get("thread_ts") or msg_ts

    action = body.get("actions", [{}])[0]
    selected_user = action.get("selected_user")

    # Recover the request payload from the sibling Approve button's value in body["message"]["blocks"]
    req_data = {}
    history = []
    current_state = "posted"
    for block in body.get("message", {}).get("blocks", []):
        for el in block.get("elements", []):
            if el.get("action_id") == "req_approve":
                val_data = json.loads(el.get("value") or "{}")
                req_data = val_data.get("request", {})
                history = list(val_data.get("history", []))
                current_state = val_data.get("state", "posted")
                break
        if req_data:
            break

    def say(text, thread_ts=thread_ts, **kw):
        client.chat_postMessage(channel=channel_id, text=text, thread_ts=thread_ts, **kw)

    lifecycle.handle_assign(
        client=client,
        say=say,
        channel=channel_id,
        thread_ts=thread_ts,
        user_id=user_id,
        event_ts=msg_ts,
        target_user_id=selected_user,
        req_data=req_data,
        msg_ts=msg_ts,
        history=history,
        current_state=current_state,
    )


@app.action("req_approve")
def handle_req_approve_action(ack, body, respond, client):
    """Handle clicking 'Approve' button on purchase request message."""
    ack()
    user_id = body.get("user", {}).get("id")
    channel_id = body.get("channel", {}).get("id")
    msg_ts = body.get("message", {}).get("ts")
    if not admin.is_approved_reviewer(user_id):
        log.warning("Unauthorized user %s attempted to approve purchase request", user_id)
        slack_io.deny(respond, "🔒 Only authorized approvers can approve purchase requests.")
        return

    action = body.get("actions", [{}])[0]
    val_data = json.loads(action.get("value") or "{}")
    req_data = val_data.get("request", {})
    thread_ts = (
        body.get("container", {}).get("thread_ts")
        or val_data.get("thread_ts")
        or req_data.get("thread_ts")
        or msg_ts
    )

    def say(text, thread_ts=thread_ts, **kw):
        client.chat_postMessage(channel=channel_id, text=text, thread_ts=thread_ts, **kw)

    lifecycle.handle_epif_processing(
        client=client,
        say=say,
        channel=channel_id,
        thread_ts=thread_ts,
        approver=user_id,
        event_ts=msg_ts,
        posted_payload=req_data or None,
        card_ts=msg_ts,
    )


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
        slack_io.deny(respond, "⚠️ This request must be assigned to a buyer before it can be marked processed. Use `@Purchasing assign @buyer`.")
        return

    if not (user_id == assignee_id or admin.is_admin_user(user_id)):
        log.warning("Unauthorized user %s (not assignee %s or admin) clicked req_processed", user_id, assignee_id)
        slack_io.deny(respond, f"🔒 Only the assigned buyer (<@{assignee_id}>) or an admin can mark this request processed.")
        return

    requester_name = slack_io.resolve_requester(client, user_id)
    if not requester_name:
        log.warning("Unregistered user %s clicked req_processed", user_id)
        slack_io.deny(respond, "🔒 You must be registered in the lab roster to update requests. Use `/roster-set-name` first.")
        return

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
        card_ts=msg_ts,
        req_data=req_data,
        history=history,
    )


@app.action("req_decline")
def handle_req_decline_action(ack, body, respond, client):
    """Handle clicking 'Decline' on a posted request. Allowed for approvers and buyers."""
    ack()
    user_id = body.get("user", {}).get("id")
    channel_id = body.get("channel", {}).get("id")
    msg_ts = body.get("message", {}).get("ts")

    # Approvers and buyers may both decline a posted request.
    if not (admin.is_approved_reviewer(user_id) or roster.is_buyer(user_id)):
        log.warning("Unauthorized user %s attempted to decline purchase request", user_id)
        slack_io.deny(respond, "🔒 Only approvers and buyers can decline purchase requests.")
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
        slack_io.deny(respond, "🔒 Only approvers and admins can cancel purchase requests.")
        return

    action = body.get("actions", [{}])[0]
    val_data = json.loads(action.get("value") or "{}")
    req_data = val_data.get("request", {})
    state = val_data.get("state", "")
    history = list(val_data.get("history", []))

    def say(text, thread_ts=thread_ts, **kw):
        client.chat_postMessage(channel=channel_id, text=text, thread_ts=thread_ts, **kw)

    lifecycle.handle_cancel(client, say, channel_id, thread_ts, msg_ts, user_id, req_data, state, history)


@app.action(config.ACTION_REQ_ITEMS)
def handle_req_items_action(ack, body, respond, client):
    """Handle clicking 'Add items' or 'Edit items' on a posted request card."""
    ack()
    user_id = body.get("user", {}).get("id")
    channel_id = body.get("channel", {}).get("id")
    container = body.get("container", {})
    card_ts = container.get("message_ts") or body.get("message", {}).get("ts")
    thread_ts = container.get("thread_ts") or body.get("message", {}).get("thread_ts") or card_ts

    card_payload = slack_io.get_card_payload(client, channel_id, thread_ts, card_ts)
    if not card_payload:
        slack_io.deny(respond, "⚠️ Could not find request details for this card.")
        return

    # Permissions: requester, any buyer, or an admin (ADR 0006 decision 8)
    card_user_id = card_payload.get("user_id")
    card_requester = card_payload.get("requester")
    user_name = slack_io.resolve_requester(client, user_id)
    is_requester = (user_id and user_id == card_user_id) or (user_name and user_name == card_requester)
    is_buyer = roster.is_buyer(user_id)
    is_admin = admin.is_admin_user(user_id)

    if not (is_requester or is_buyer or is_admin):
        log.warning("User %s denied editing items on card %s", user_id, card_ts)
        slack_io.deny(respond, "🔒 Only the requester, a buyer, or an admin can edit line items on this request.")
        return

    card_state = card_payload.get("state", "posted")
    if card_state != "posted":
        slack_io.deny(respond, "⚠️ Items can only be added or edited while the request is in posted state.")
        return

    items = card_payload.get("items")
    shipping = float(card_payload.get("shipping") or 0.0)
    view = blocks.build_items_view(
        channel=channel_id,
        thread_ts=thread_ts,
        card_ts=card_ts,
        items=items,
        shipping=shipping,
    )
    try:
        client.views_open(trigger_id=body["trigger_id"], view=view)
    except Exception as e:
        log.error("Failed to open items modal for user %s: %s", user_id, e)



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
        slack_io.deny(respond, "🔒 Only the assigned buyer or an admin can update this request.")
        return

    requester_name = slack_io.resolve_requester(client, user_id)
    if not requester_name:
        log.warning("Unregistered user %s clicked req_confirmed", user_id)
        slack_io.deny(respond, "🔒 You must be registered in the lab roster to update requests. Use `/roster-set-name` first.")
        return

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
        card_ts=msg_ts,
        req_data=req_data,
        history=history,
    )


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
        slack_io.deny(respond, "🔒 Only the assigned buyer or an admin can update this request.")
        return

    requester_name = slack_io.resolve_requester(client, user_id)
    if not requester_name:
        log.warning("Unregistered user %s clicked req_delivered", user_id)
        slack_io.deny(respond, "🔒 You must be registered in the lab roster to update requests. Use `/roster-set-name` first.")
        return

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
        card_ts=msg_ts,
        req_data=req_data,
        history=history,
    )


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


@app.action(config.ACTION_OPEN_ROSTER_SET_NAME)
def handle_open_roster_set_name_action(ack, body, client):
    """Open /roster-set-name modal when clicked from App Home."""
    ack()
    user_id = body.get("user", {}).get("id")
    trigger_id = body.get("trigger_id")
    current_name = roster.get_requesters().get(user_id) if hasattr(roster, "get_requesters") else None

    modal = blocks.build_roster_set_name_view(user_id, current_name)
    try:
        client.views_open(trigger_id=trigger_id, view=modal)
        log.info("Opened roster-set-name modal from App Home button for user %s", user_id)
    except Exception as e:
        log.error("Failed to open /roster-set-name modal from button: %s", e)


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
    files=None, direct_file=None, bot_user_id: str | None = None, respond=None,
):
    """Single dispatch point for all app_mention and direct message commands."""
    if not bot_user_id:
        bot_user_id = get_bot_user_id(client)
    stripped_text, user_mentions, group_mentions = text_rules.parse_mentions(text, bot_user_id=bot_user_id)
    cmd = text_rules.parse_keyword(stripped_text)

    if cmd in config.HELP_KEYWORDS:
        say(text=blocks.get_help_message(), thread_ts=thread_ts)
    elif cmd in config.STATUS_KEYWORDS:
        ops.handle_health_status(client, say, channel, thread_ts)
    elif cmd in config.QUEUE_KEYWORDS:
        ops.handle_queue_status(client, say, channel, thread_ts)
    elif cmd in config.LOGS_KEYWORDS:
        ops.handle_logs(client, say, channel, thread_ts, user, text)
    elif cmd in config.UPDATE_KEYWORDS:
        ops.handle_update(client, say, channel, thread_ts, user)
    elif cmd in config.RESTART_KEYWORDS:
        ops.handle_restart(client, say, channel, thread_ts, user)
    elif cmd in config.PROMOTE_ADMIN_KEYWORDS:
        ops.handle_promote_admin(client, say, channel, thread_ts, user, text)
    elif cmd in config.ADD_APPROVER_KEYWORDS:
        ops.handle_add_approver(client, say, channel, thread_ts, user, text)
    elif cmd in config.REMOVE_APPROVER_KEYWORDS:
        ops.handle_remove_approver(client, say, channel, thread_ts, user, text)
    elif cmd in config.ADD_BUYER_KEYWORDS:
        ops.handle_add_buyer(client, say, channel, thread_ts, user, text)
    elif cmd in config.REMOVE_BUYER_KEYWORDS:
        ops.handle_remove_buyer(client, say, channel, thread_ts, user, text)
    elif cmd in config.REMOVE_MEMBER_KEYWORDS:
        ops.handle_remove_member(
            client,
            say,
            channel,
            thread_ts,
            user,
            text,
            target_user_id=user_mentions[0] if user_mentions else None,
            respond=respond,
        )
    elif cmd in config.REMOVE_VENDOR_KEYWORDS:
        ops.handle_remove_vendor(client, say, channel, thread_ts, user, text)
    elif cmd in config.TEMPLATE_KEYWORDS:
        ops.handle_template_command(client, say, channel, thread_ts, user)
    elif cmd in config.QUOTE_KEYWORDS:
        lifecycle.handle_quote(client, say, channel, thread_ts, event_ts, files)
    elif cmd in config.ASSIGN_KEYWORDS:
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
    elif cmd in config.PROCESSED_KEYWORDS:
        lifecycle.handle_processed(client, say, channel, thread_ts, user, event_ts, text)
    elif cmd in config.CONFIRM_KEYWORDS:
        lifecycle.handle_confirmation(client, say, channel, thread_ts, user, event_ts, text, files)
    elif cmd in config.DELIVERED_KEYWORDS:
        lifecycle.handle_delivery(client, say, channel, thread_ts, user, event_ts, text)
    elif cmd in config.APPROVAL_KEYWORDS or (direct_file and cmd is None):
        if not admin.is_approved_reviewer(user):
            log.warning("Unauthorized user %s attempted to approve purchase request", user)
            say(text="🔒 Only Charlie Hirst can approve purchase requests.", thread_ts=thread_ts)
            return

        row = slack_io.find_row_in_thread(client, channel, thread_ts)
        card_req, card_ts, card_hist, card_state = slack_io.find_card_in_thread(client, channel, thread_ts)
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
        picked_buyer_id = card_req.get("assignee_id") if card_req else None
        picked_buyer_name = card_req.get("assignee") if card_req else None

        input_note = None
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
                    if picked_buyer_id:
                        input_note = "Using mentioned buyer instead of dropdown selection."
        elif picked_buyer_id:
            if not roster.is_buyer(picked_buyer_id):
                refusal_msg = f"⚠️ <@{picked_buyer_id}> isn't on the buyers list, so I can't assign this to them. An admin can add them: @Purchasing add-buyer <@{picked_buyer_id}>"
                assignee_id = None
                assignee_name = None
            else:
                cand_name = picked_buyer_name or slack_io.resolve_requester(client, picked_buyer_id)
                if not cand_name:
                    refusal_msg = f"🔒 <@{picked_buyer_id}> must be registered in the lab roster to be assigned requests. Use `/roster-set-name` first."
                    assignee_id = None
                    assignee_name = None
                else:
                    assignee_id = picked_buyer_id
                    assignee_name = cand_name
                    refusal_msg = None
                    input_note = "Assigned via dropdown selection."
        else:
            assignee_id = None
            assignee_name = None
            refusal_msg = None

        lifecycle.handle_epif_processing(
            client, say, channel, thread_ts, user, event_ts,
            direct_file=direct_file, direct_poster=user if direct_file else None,
            assignee_id=assignee_id, assignee_name=assignee_name, refusal_msg=refusal_msg,
            input_note=input_note,
        )
    else:
        # Unknown word
        import string
        tokens = stripped_text.strip().split()
        punct = string.punctuation + "“”‘’…"
        first_token = tokens[0].strip(punct) if tokens else None
        reply_text = text_rules.format_unknown_keyword_message(first_token)
        if respond and callable(respond):
            slack_io.deny(respond, reply_text)
        else:
            say(text=reply_text, thread_ts=thread_ts)


@app.event("app_mention")
def on_mention(event, client, say, context=None):
    text = event.get("text", "")
    channel = event["channel"]
    thread_ts = event.get("thread_ts") or event["ts"]
    user = event.get("user")
    event_ts = event["ts"]
    files = event.get("files", [])
    bot_user_id = context.get("bot_user_id") if context else None
    respond = context.get("respond") if context else None

    log.info("Received app_mention from user %s in channel %s: '%s'", user, channel, text)
    dispatch_command(
        client, say, channel, thread_ts, user, event_ts, text,
        files=files, bot_user_id=bot_user_id, respond=respond,
    )


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
    respond = context.get("respond") if context else None

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
            files=files, direct_file=direct_file, bot_user_id=bot_user_id, respond=respond,
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
            view=blocks.build_app_home_view(user_id=user_id),
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
    log.info("Purchasing Channel: %s", config.PURCHASING_CHANNEL or "Not configured")
    log.info("Heartbeat URL: %s", config.HEALTHCHECK_URL or "Not configured")
    log.info("=" * 70)

    # Validate channel configuration (Ticket 15: loud startup check)
    path_validator.check_purchasing_channel()

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
