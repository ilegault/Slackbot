"""Purchase request lifecycle operations.

WHY THIS EXISTS:
----------------
Encapsulates all stage transitions for a purchase request: approval, claiming,
submission, confirmation, delivery, and quote archiving. Coordinates between
Slack client I/O, domain validation, storage write queue, and Block Kit messages.

Imports:
    - config, epif_parser, interview, log_writer, queue_worker, roster, validators, blocks, slack_io, text_rules
May NOT import:
    - app.py
"""
from datetime import datetime
import json
import logging
import os

try:
    from . import config
    from . import epif_parser
    from . import interview
    from . import log_writer
    from . import queue_worker
    from . import roster
    from . import validators
    from . import blocks
    from . import slack_io
    from . import text_rules
except ImportError:
    import config
    import epif_parser
    import interview
    import log_writer
    import queue_worker
    import roster
    import validators
    import blocks
    import slack_io
    import text_rules

log = logging.getLogger("p-bot")


def finalize_purchase_request(
    client, say, channel: str, thread_ts: str, event_ts: str,
    parsed: dict, requester: str | None, notify_target: str | None,
    pdf_bytes: bytes | None = None, file_name: str | None = None,
    is_pending_name: bool = False,
):
    """Validate, enqueue row write to Purchasing-Log.xlsx, archive PDF if present, and notify."""
    display_file = file_name or "Purchase Request"
    problems = validators.validate(parsed, requester_name=requester)
    if problems:
        slack_io.log_rejection(notify_target, display_file, problems, requester_name=requester)
        bullets = "\n".join(f"  • {p}" for p in problems)
        if notify_target:
            if pdf_bytes:
                fail_msg = (
                    f"I couldn't log *{display_file}* yet:\n{bullets}\n\n"
                    "Fix those in the EPIF, re-upload it to the thread, and ask for approval again."
                )
            else:
                fail_msg = (
                    f"I couldn't log this *{display_file}* yet:\n{bullets}\n\n"
                    "Please adjust your request and submit again."
                )
            slack_io.tell(client, notify_target, fail_msg)
        if channel != notify_target:
            say(text=f"Not logged - {len(problems)} problem(s), requester DM'd.", thread_ts=thread_ts)
        return

    # Define atomic write action for the queue
    def write_action():
        row_num = log_writer.append_row(log_writer.build_row(parsed, requester))
        if pdf_bytes and file_name:
            saved_epif_path = log_writer.save_epif(pdf_bytes, file_name)
        else:
            saved_epif_path = None
        return row_num, saved_epif_path

    def on_success(result):
        row, saved_path = result
        log.info("✅ Successfully logged order to Row %d (saved PDF: %s)", row, saved_path)

        try:
            client.reactions_add(channel=channel, timestamp=event_ts, name="white_check_mark")
        except Exception as e:
            log.debug("Could not add checkmark reaction: %s", e)

        is_grad_buyer = requester in config.GRAD_STUDENT_BUYERS
        display_requester = f"{requester} (pending name confirmation)" if is_pending_name else (requester or "Requester")
        ping_user = f"<@{notify_target}>" if notify_target else display_requester
        saved_str = f"Saved EPIF to `{saved_path}`.\n\n" if saved_path else ""

        if is_grad_buyer:
            log.info("Requester %s is a grad buyer; sending pre-drafted email", requester)
            say(
                text=(
                    f"Logged to row {row}: {parsed['item_description']} — "
                    f"${parsed['total_price']:,.2f} from {parsed['vendor']} "
                    f"({parsed['category']}).\n"
                    f"{saved_str}"
                    f"📢 {ping_user} Please submit this purchase (via Workday or by emailing Tina & Ally). "
                    f"Use the buttons on the request message to update its status when submitted, confirmed, and delivered!"
                ),
                thread_ts=thread_ts,
            )

            if notify_target:
                email_draft = text_rules.generate_email_draft(parsed, requester or "Grad Student")
                dm_text = (
                    f"Hi {requester or 'there'}! Your purchase request for *{parsed['item_description']}* "
                    f"has been approved and logged to *Row {row}* in the Purchasing Log.\n\n"
                    f"📋 *Next Steps:*\n"
                    f"1. Submit via Workday or send this email to purchasing (Tina / Ally / Lisa):\n\n"
                    f"```\n{email_draft}\n```\n\n"
                    f"2. Use the buttons on your purchase request in the purchasing channel to update its status when submitted, confirmed, and delivered!"
                )
                try:
                    slack_io.tell(client, notify_target, dm_text)
                except Exception as e:
                    log.warning("Could not DM requester %s: %s", notify_target, e)

        else:
            log.info("Requester %s is undergrad/non-buyer; broadcasting claim request to grad buyers", requester)
            buyers_list = ", ".join(sorted(config.GRAD_STUDENT_BUYERS))
            say(
                text=(
                    f"Logged to row {row}: {parsed['item_description']} — "
                    f"${parsed['total_price']:,.2f} from {parsed['vendor']} "
                    f"({parsed['category']}).\n"
                    f"{saved_str}"
                    f"📢 {ping_user}'s request is approved!\n"
                    f"⚠️ *Needs a Grad Student Buyer to process in Workday / ShopUW.*\n"
                    f"Grad students ({buyers_list}): please click Claim on the request above to take on this order."
                ),
                thread_ts=thread_ts,
            )

    def on_failure(error):
        log.error("Failed to write to workbook: %s", error)
        say(text=f"Error saving/logging purchase request: {error}", thread_ts=thread_ts)

    queue_worker.submit_write_task(
        action_fn=write_action,
        channel=channel,
        thread_ts=thread_ts,
        user_id=notify_target or "",
        task_type="append",
        description=f"Purchase for {requester or 'requester'}: {parsed.get('item_description', 'Order')}",
        success_callback=on_success,
        failure_callback=on_failure,
        client=client,
    )


def handle_epif_processing(client, say, channel: str, thread_ts: str, approver: str, event_ts: str, direct_file=None, direct_poster=None):
    """Core logic to inspect thread/file, parse, validate, and enqueue row write & PDF archiving."""
    log.info("Processing EPIF/purchase request from approver/poster: %s in channel: %s", approver or direct_poster, channel)
    if direct_file:
        file_obj, poster = direct_file, direct_poster
    else:
        file_obj, poster = slack_io.find_epif_in_thread(client, channel, thread_ts)

    if file_obj is not None:
        # PDF Attachment Path
        requester = slack_io.resolve_requester(client, poster)
        file_name = file_obj.get("name", "EPIF.pdf")
        log.info("Found file '%s' posted by %s (resolved requester: %s)", file_name, poster, requester)

        try:
            pdf_bytes = slack_io.download(file_obj)
            log.info("Downloaded %s (%d bytes)", file_name, len(pdf_bytes))
            parsed = epif_parser.parse_epif(pdf_bytes)
            log.info("Parsed EPIF fields: Item='%s', Vendor='%s', Total=$%s, Project=%s, Fund=%s, Category='%s'",
                     parsed.get("item_description"), parsed.get("vendor"), parsed.get("total_price"),
                     parsed.get("project_id"), parsed.get("fund"), parsed.get("category"))
        except (epif_parser.FlattenedPdfError, RuntimeError) as error:
            slack_io.log_rejection(poster or approver, file_name, [str(error)], requester_name=requester)
            target_dm = poster or approver
            slack_io.tell(client, target_dm, str(error))
            if channel != target_dm:
                say(text=f"Error processing {file_name}: {str(error)}", thread_ts=thread_ts)
            return

        finalize_purchase_request(
            client=client,
            say=say,
            channel=channel,
            thread_ts=thread_ts,
            event_ts=event_ts,
            parsed=parsed,
            requester=requester,
            notify_target=poster or approver,
            pdf_bytes=pdf_bytes,
            file_name=file_name,
            is_pending_name=False,
        )
        return

    # Modal Purchase Request in Thread Path
    parsed_req, modal_req_name, modal_user_id, is_pending = slack_io.find_modal_request_in_thread(client, channel, thread_ts)
    if parsed_req:
        log.info("Found modal purchase request in thread: %s from %s", parsed_req.get("item_description"), modal_req_name)
        finalize_purchase_request(
            client=client,
            say=say,
            channel=channel,
            thread_ts=thread_ts,
            event_ts=event_ts,
            parsed=parsed_req,
            requester=modal_req_name,
            notify_target=modal_user_id or approver,
            pdf_bytes=None,
            file_name=None,
            is_pending_name=is_pending,
        )
        return

    log.info("No PDF or purchase request found in thread/message %s", thread_ts)
    say(text="I couldn't find a PDF or purchase request in this thread/message.", thread_ts=thread_ts)


def handle_claim(client, say, channel: str, thread_ts: str, user_id: str, event_ts: str):
    """Assign a grad student to an approved order thread."""
    grad_name = slack_io.resolve_requester(client, user_id) or "Grad Student"
    row = slack_io.find_row_in_thread(client, channel, thread_ts)
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
            f"Once placed in Workday, click the button on the request message above to mark it submitted."
        ),
        thread_ts=thread_ts,
    )


def handle_submission(client, say, channel: str, thread_ts: str, user_id: str, event_ts: str, text: str):
    """Mark an order as Submitted/Processed in Workday (Col U) and optionally update Total Price (Col H)."""
    user_name = slack_io.resolve_requester(client, user_id) or "Buyer"
    row = text_rules.extract_row_from_text(text)
    if not row and thread_ts:
        row = slack_io.find_row_in_thread(client, channel, thread_ts)
    if not row and user_name:
        row = log_writer.find_latest_unconfirmed_row_for_requester(user_name)

    if not row:
        log.warning("Could not identify row for submission by %s (%s). Text: %s", user_name, user_id, text)
        say(
            text="I couldn't figure out which order you're submitting. Please specify the row number or click the button on the request message.",
            thread_ts=thread_ts,
        )
        return

    today = datetime.now().date()
    update_vals = {config.COLUMN_DATE_PROCESSED: today}

    price = text_rules.extract_price_from_text(text)
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
                f"Please use the buttons on the request message to mark it confirmed once confirmation arrives!"
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
    requester_name = slack_io.resolve_requester(client, user_id)
    row = text_rules.extract_row_from_text(text)
    if not row and thread_ts:
        row = slack_io.find_row_in_thread(client, channel, thread_ts)
    if not row and requester_name:
        row = log_writer.find_latest_unconfirmed_row_for_requester(requester_name)

    if not row:
        log.warning("Could not identify row for confirmation by %s (%s). Text: %s", requester_name, user_id, text)
        say(
            text="I couldn't figure out which order you're confirming. Please specify the row number or click the button on the request message.",
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
                    content = slack_io.download_file(f)
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
    requester_name = slack_io.resolve_requester(client, user_id) or "Lab Member"
    row = text_rules.extract_row_from_text(text)
    if not row and thread_ts:
        row = slack_io.find_row_in_thread(client, channel, thread_ts)
    if not row and requester_name:
        row = log_writer.find_latest_unconfirmed_row_for_requester(requester_name)

    if not row:
        log.warning("Could not identify row for delivery by %s (%s). Text: %s", requester_name, user_id, text)
        say(
            text="I couldn't figure out which order was delivered. Please specify the row number or click the button on the request message.",
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
            content = slack_io.download_file(f)
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


def _process_interview_completion(ack, client, body, meta: dict, stage2: dict, stage3: dict | None = None):
    """Validate staged inputs, report errors or finalize and post to purchasing channel."""
    stage1 = {
        "resolved_name": meta.get("resolved_name"),
        "user_id": meta.get("user_id"),
        "vendor_choice": meta.get("vendor_choice"),
        "vendor_custom": meta.get("vendor_custom"),
        "route": meta.get("route"),
    }
    parsed = interview.build_parsed_from_stages(stage1, stage2, stage3)
    requester = meta.get("resolved_name")
    is_pending_name = meta.get("is_pending_name", False)
    user_id = meta.get("user_id") or body.get("user", {}).get("id")
    vendor_choice = meta.get("vendor_choice")
    custom_vendor = meta.get("vendor_custom")

    dummy_valid_name = list(roster.get_valid_requesters())[0] if (hasattr(roster, "get_valid_requesters") and roster.get_valid_requesters()) else "Isaac"
    problems = validators.validate(parsed, requester_name=requester if not is_pending_name else dummy_valid_name)

    if stage3 is not None:
        if not str(stage3.get("asset_id") or "").strip():
            problems.append("Asset ID is required for fabrication components")
        if not str(stage3.get("name_of_system") or "").strip():
            problems.append("Name of System is required for fabrication components")

    if problems:
        errors = {}
        for p in problems:
            p_lower = p.lower()
            if "asset" in p_lower:
                errors["block_asset_id"] = p
            elif "system" in p_lower or "name of system" in p_lower:
                errors["block_name_of_system"] = p
            elif "what" in p_lower or "item" in p_lower:
                errors["block_item_description"] = p
            elif "purpose" in p_lower or "why" in p_lower:
                errors["block_purpose"] = p
            elif "amt" in p_lower or "price" in p_lower or "number" in p_lower or "amount" in p_lower:
                errors["block_total_price"] = p
            elif "contact" in p_lower:
                errors["block_vendor_contact_name"] = p
            elif "email" in p_lower:
                errors["block_vendor_contact_email"] = p
            elif "vendor" in p_lower:
                errors["block_vendor"] = p
            elif "date" in p_lower:
                errors["block_date_of_purchase"] = p
            elif "project id" in p_lower:
                errors["block_project_id"] = p
            elif "fund" in p_lower:
                errors["block_fund"] = p
            elif "delivery" in p_lower or "room" in p_lower:
                errors["block_delivery_room"] = p
            elif "category" in p_lower:
                errors["block_category"] = p
            elif "p-card" in p_lower or "req" in p_lower:
                errors["block_payment_method"] = p
            else:
                errors.setdefault("block_item_description", p)

        ack(response_action="errors", errors=errors)
        return

    ack()

    # Determine posting channel
    post_channel = os.environ.get("PURCHASING_CHANNEL") or config.ADMIN_ALERT_CHANNEL or user_id
    display_name = f"{requester} (pending name confirmation)" if is_pending_name else (requester or f"<@{user_id}>")
    suggest_note = f"\n💡 *Note:* Suggested new vendor: `{custom_vendor}`" if (vendor_choice == config.VENDOR_SUGGEST_OPTION and custom_vendor) else ""

    req_payload = {
        "parsed": {
            **parsed,
            "date_of_purchase": parsed["date_of_purchase"].isoformat() if parsed["date_of_purchase"] else None,
        },
        "requester": requester,
        "user_id": user_id,
        "is_pending_name": is_pending_name,
        "suggest_note": suggest_note,
    }
    req_blocks = blocks.build_request_blocks("posted", req_payload)

    summary_text = (
        f"🛒 *New Purchase Request from {display_name}:*\n"
        f"• *Item:* {parsed['item_description']}\n"
        f"• *Total:* ${parsed['total_price']:,.2f}\n"
        f"• *Vendor:* {parsed['vendor']} ({parsed['payment_method']})\n"
        f"• *Category:* {parsed['category']}\n"
        f"• *Project ID / Fund:* {parsed['project_id']} (Fund {parsed['fund']})\n"
        f"• *Delivery Room:* {parsed['delivery_room']}\n"
        f"• *Purpose:* {parsed['purpose']}"
        f"{suggest_note}\n\n"
        f"Use the buttons below to approve and track this request."
    )

    try:
        client.chat_postMessage(
            channel=post_channel,
            text=summary_text,
            blocks=req_blocks,
            metadata={
                "event_type": "purchase_request",
                "event_payload": req_payload,
            },
        )
    except Exception as e:
        log.error("Failed to post purchase request summary to channel %s: %s", post_channel, e)

    # DM user confirmation
    try:
        slack_io.tell(client, user_id, f"✅ Your purchase request for *{parsed['item_description']}* has been submitted to the purchasing channel awaiting approval.")
    except Exception as e:
        log.warning("Could not DM user confirmation: %s", e)

    # If pending name confirmation, post alert with approve button to ADMIN_ALERT_CHANNEL (Phase 2 Ticket 2.3)
    if is_pending_name and config.ADMIN_ALERT_CHANNEL:
        try:
            client.chat_postMessage(
                channel=config.ADMIN_ALERT_CHANNEL,
                text=f"⚠️ New unrecognized user <@{user_id}> submitted a purchase request and proposed display name '{requester}'.",
                blocks=[
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": (
                                f"⚠️ *New Lab Member Approval Needed:*\n"
                                f"User: <@{user_id}> (`{user_id}`)\n"
                                f"Proposed Requester Name: *{requester}*\n"
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
                                "value": json.dumps({"slack_id": user_id, "name": requester}),
                            }
                        ],
                    },
                ],
            )
        except Exception as e:
            log.warning("Could not post new requester alert to admin channel: %s", e)

    # If suggested vendor, post alert with approve button to ADMIN_ALERT_CHANNEL (Phase 2 Ticket 2.4)
    if vendor_choice == config.VENDOR_SUGGEST_OPTION and custom_vendor and config.ADMIN_ALERT_CHANNEL:
        try:
            client.chat_postMessage(
                channel=config.ADMIN_ALERT_CHANNEL,
                text=f"💡 New vendor suggested by <@{user_id}>: '{custom_vendor}'.",
                blocks=[
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": (
                                f"💡 *Suggested Vendor Approval Needed:*\n"
                                f"Suggested Name: *{custom_vendor}*\n"
                                f"Suggested by: <@{user_id}>\n"
                                f"Add to Workday catalog vendor list in `roster.json`?"
                            ),
                        },
                    },
                    {
                        "type": "actions",
                        "elements": [
                            {
                                "type": "button",
                                "text": {"type": "plain_text", "text": "Approve Vendor"},
                                "style": "primary",
                                "action_id": "approve_new_vendor",
                                "value": json.dumps({"vendor": custom_vendor}),
                            }
                        ],
                    },
                ],
            )
        except Exception as e:
            log.warning("Could not post new vendor alert to admin channel: %s", e)
