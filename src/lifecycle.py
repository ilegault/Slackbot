"""Purchase request lifecycle operations.

WHY THIS EXISTS:
----------------
Encapsulates all stage transitions for a purchase request: approval, assignment,
processing, confirmation, delivery, and quote archiving. Coordinates between
Slack client I/O, domain validation, storage write queue, and Block Kit messages.

Per ADR 0004:
- The approver names the responsible buyer in the approval message itself (@Dylan @Purchasing approved).
- Claim is deleted entirely. Requests without a valid buyer mention are approved and unassigned.
- Any buyer, approver, or admin can assign an unassigned request (@Purchasing assign).
- Only the current assignee, an approver, or an admin may reassign an already assigned request.
- The pre-filled email draft is generated once, at assignment time, and DM'd to the assignee.

Per Ticket 13:
- The card follows the write, not the click. handle_processed, handle_confirmation,
  and handle_delivery each render the card and append history inside on_success.
  Write failures and refusal branches never advance the card.

Per Ticket 14:
- The Approve button uses posted_payload directly instead of re-reading Slack.
  Resolution order in handle_epif_processing: direct_file -> PDF in thread -> posted_payload -> metadata lookup.
  Regex prose parsing is removed; the thread search is replaced by find_request_metadata_in_thread.

Per Ticket 15:
- PURCHASING_CHANNEL is read from config.py; silent fallback to ADMIN_ALERT_CHANNEL or DM is removed.

Per Ticket 27:
- Adds handle_items_update to save line items in card metadata, update card blocks,
  post edit notices, and upload draft BOM spreadsheets when needs_bom is True.
- Records source='epif' on dropped EPIF cards.

Per Ticket 28:
- _process_interview_completion stores line items and shipping on modal-born cards
  and uploads draft BOM spreadsheets when needs_bom is True.
- Extracts upload_draft_bom as single implementation for uploading draft BOM spreadsheets (invariant 1).

Per Ticket 29:
- Approval archives the BOM and the log points at it.
- In finalize_purchase_request, when needs_bom is True, the row append, BOM spreadsheet
  generation with row NNNN, save to BOMS_DIR, and Notes column update (BOM: <filename> (N items))
  all occur inside the single queued write task (invariant 2).
- All-or-nothing: if BOM generation, save, or Notes update raises, the row is blanked
  before re-raising so no orphan row remains.
- On success, the archived BOM is uploaded to the thread, and bom_file is recorded on the approved card.
- Totals mismatch between line items and request total refuses approval like a validation rejection.
- upload_archived_bom provides the single implementation for uploading archived BOM spreadsheets.

Per Ticket 30:
- The buyer's DM carries the archived BOM when one exists.
- _send_assignee_dm is the single implementation of the assignee email-draft DM (invariant 1),
  called from both finalize_purchase_request (at approval) and handle_assign (after unassigned approval).
- text_rules.generate_email_draft gains bom_filename: the email body lists the attached file.
- The archived BOM is uploaded to the assignee's DM via conversations_open + files_upload_v2.
- A failed upload is logged and alerted to admin; it never reverses the approval.

Per Ticket 31:
- Cancel moves the archived BOM to BOMS_DIR/Cancelled/, keeping its row-numbered filename (ADR 0006 decision 7).
- The move happens inside the same queued write task as the row blanking.
- A missing BOM file is logged as a warning; the cancellation still completes — a file that was never
  saved must not leave a cancelled purchase sitting in the log (ticket 31 note).

Imports:
    - admin, blocks, bom, config, epif_parser, interview, log_writer, queue_worker, roster, validators, slack_io, text_rules
May NOT import:
    - app.py
"""
import json
import logging
import os
import shutil
from datetime import datetime

try:
    from . import (
        admin,
        blocks,
        bom,
        config,
        epif_parser,
        interview,
        log_writer,
        queue_worker,
        roster,
        slack_io,
        text_rules,
        validators,
    )
except ImportError:
    import admin
    import blocks
    import bom
    import config
    import epif_parser
    import interview
    import log_writer
    import queue_worker
    import roster
    import slack_io
    import text_rules
    import validators

log = logging.getLogger("p-bot")


def _send_assignee_dm(
    client,
    assignee_id: str,
    assignee_name: str,
    email_draft: str,
    item_desc: str,
    row,
    bom_path: str | None = None,
    bom_fname: str | None = None,
) -> None:
    """Send the email-draft DM to the assigned buyer, optionally attaching the archived BOM.

    WHY THIS EXISTS:
    ----------------
    Single implementation of the assignee DM (invariant 1).
    Called by finalize_purchase_request (at approval) and handle_assign (at post-approval assignment).
    Per ADR 0006 decision 6 and spec decision 4: the archived BOM is attached to this DM
    so the buyer forwards one EPIF and one sheet instead of pasting links.
    A failed BOM upload is logged and alerted to admin but never reverses the approval
    (same spirit as ADR 0004 decision 2 — the money decision already happened).
    """
    row_dm_str = f" in *Row {row}*" if row else ""
    dm_text = (
        f"Hi {assignee_name}! You've been assigned the purchase request for *{item_desc}*{row_dm_str}.\n\n"
        f"📋 *Next Steps:*\n"
        f"1. Submit via Workday or send this email to purchasing (Tina / Ally / Lisa):\n\n"
        f"```\n{email_draft}\n```\n\n"
        f"2. Use the buttons on your purchase request in the purchasing channel to update its status when processed, confirmed, and delivered!"
    )
    if bom_fname:
        dm_text += f"\n\n📊 The BOM spreadsheet *{bom_fname}* is attached."
    try:
        slack_io.tell(client, assignee_id, dm_text)
    except Exception as e:
        log.warning("Could not DM assignee %s: %s", assignee_id, e)
        return

    if bom_path and bom_fname and os.path.exists(bom_path):
        try:
            resp = client.conversations_open(users=assignee_id)
            dm_channel = resp["channel"]["id"]
            with open(bom_path, "rb") as fh:
                content = fh.read()
            if hasattr(client, "files_upload_v2"):
                client.files_upload_v2(
                    channel=dm_channel,
                    content=content,
                    filename=bom_fname,
                    title=bom_fname,
                )
            else:
                client.files_upload(
                    channels=dm_channel,
                    content=content,
                    filename=bom_fname,
                    title=bom_fname,
                )
            log.info("Uploaded BOM %s to DM for %s", bom_fname, assignee_id)
        except Exception as e:
            log.warning("Could not upload BOM %s to DM for %s: %s", bom_fname, assignee_id, e)
            if config.ADMIN_ALERT_CHANNEL:
                try:
                    client.chat_postMessage(
                        channel=config.ADMIN_ALERT_CHANNEL,
                        text=f"⚠️ Failed to attach BOM *{bom_fname}* to {assignee_name}'s DM: {e}",
                    )
                except Exception as alert_err:
                    log.warning("Could not alert admin about BOM DM failure: %s", alert_err)


def finalize_purchase_request(
    client, say, channel: str, thread_ts: str, event_ts: str,
    parsed: dict, requester: str | None, notify_target: str | None,
    pdf_bytes: bytes | None = None, file_name: str | None = None,
    is_pending_name: bool = False,
    assignee_id: str | None = None,
    assignee_name: str | None = None,
    refusal_msg: str | None = None,
    approver: str | None = None,
    input_note: str | None = None,
    card_ts: str | None = None,
    items: list[dict] | None = None,
    shipping: float = 0.0,
):
    """Validate, enqueue row write to Purchasing-Log.xlsx, archive PDF/BOM if present, and notify."""
    display_file = file_name or "Purchase Request"
    if items:
        total_error = bom.check_total(items, shipping, parsed.get("total_price"))
        if total_error:
            slack_io.log_rejection(notify_target, display_file, [total_error], requester_name=requester)
            fail_msg = (
                f"I couldn't log *{display_file}* yet:\n  • {total_error}\n\n"
                "Please adjust the line items or total price and ask for approval again."
            )
            if notify_target:
                slack_io.tell(client, notify_target, fail_msg)
            if channel != notify_target:
                say(text=f"Not logged - {total_error}, requester DM'd.", thread_ts=thread_ts)
            return

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

    # Define atomic write action for the queue (invariant 2)
    def write_action():
        row_num = log_writer.append_row(log_writer.build_row(parsed, requester))
        saved_epif_path = None
        bom_fname = None
        saved_bom_path = None
        try:
            if pdf_bytes and file_name:
                saved_epif_path = log_writer.save_epif(pdf_bytes, file_name)

            if items and bom.needs_bom(items):
                vendor = parsed.get("vendor") or "Vendor"
                bom_fname = bom.bom_filename(row_num, vendor)
                req_for_bom = dict(parsed)
                if requester and not req_for_bom.get("requester"):
                    req_for_bom["requester"] = requester
                xlsx_bytes = bom.build_bom_workbook(
                    req_for_bom,
                    items,
                    shipping=shipping,
                    row=row_num,
                )
                saved_bom_path = log_writer.save_bom(xlsx_bytes, bom_fname)
                notes_text = f"BOM: {bom_fname} ({len(items)} items)"
                log_writer.update_row(row_num, {config.COLUMN_NOTES: notes_text})
        except Exception:
            # All-or-nothing: blank the row just written before re-raising so no orphan row remains
            try:
                log_writer.blank_row(row_num)
            except Exception as blank_err:
                log.error("Failed to blank row %d after write failure: %s", row_num, blank_err)
            if saved_bom_path and os.path.exists(saved_bom_path):
                try:
                    os.remove(saved_bom_path)
                except Exception:
                    pass
            raise

        if bom_fname and saved_bom_path:
            return row_num, saved_epif_path, bom_fname, saved_bom_path
        return row_num, saved_epif_path

    def on_success(result):
        if len(result) == 4:
            row, saved_path, bom_fname, saved_bom_path = result
        else:
            row, saved_path = result
            bom_fname, saved_bom_path = None, None
        log.info("✅ Successfully logged order to Row %d (saved PDF: %s, saved BOM: %s)", row, saved_path, saved_bom_path)

        try:
            client.reactions_add(channel=channel, timestamp=event_ts, name="white_check_mark")
        except Exception as e:
            log.debug("Could not add checkmark reaction: %s", e)

        display_requester = f"{requester} (pending name confirmation)" if is_pending_name else (requester or "Requester")
        ping_user = f"<@{notify_target}>" if notify_target else display_requester
        saved_name = os.path.basename(saved_path.replace("\\", "/")) if saved_path else None
        saved_str = f"Saved EPIF to `{saved_name}`.\n\n" if saved_name else ""

        if bom_fname and saved_bom_path:
            upload_archived_bom(
                client=client,
                channel=channel,
                thread_ts=thread_ts,
                file_path=saved_bom_path,
                filename=bom_fname,
            )

        if assignee_id and assignee_name:
            say(
                text=(
                    f"Logged to row {row}: {parsed['item_description']} — "
                    f"${parsed['total_price']:,.2f} from {parsed['vendor']} "
                    f"({parsed['category']}).\n"
                    f"{saved_str}"
                    f"📢 {ping_user}'s request is approved!\n"
                    f"👤 Assigned to <@{assignee_id}> ({assignee_name}) to process in Workday / ShopUW."
                    + (f" ({input_note})" if input_note else "")
                ),
                thread_ts=thread_ts,
            )
            # DM email draft (with optional BOM) to assignee — single implementation via _send_assignee_dm
            row_info = log_writer.get_row_info(row) if row else {}
            draft_data = dict(parsed)
            for k, v in row_info.items():
                if k not in draft_data or not draft_data[k]:
                    draft_data[k] = v
            email_draft = text_rules.generate_email_draft(draft_data, assignee_name, bom_filename=bom_fname)
            item_desc = draft_data.get("item_description") or "supplies"
            _send_assignee_dm(
                client=client,
                assignee_id=assignee_id,
                assignee_name=assignee_name,
                email_draft=email_draft,
                item_desc=item_desc,
                row=row,
                bom_path=saved_bom_path,
                bom_fname=bom_fname,
            )
        elif refusal_msg:
            say(
                text=(
                    f"Logged to row {row}: {parsed['item_description']} — "
                    f"${parsed['total_price']:,.2f} from {parsed['vendor']} "
                    f"({parsed['category']}).\n"
                    f"{saved_str}"
                    f"📢 {ping_user}'s request is approved!\n"
                    f"{refusal_msg}"
                ),
                thread_ts=thread_ts,
            )
        else:
            say(
                text=(
                    f"Logged to row {row}: {parsed['item_description']} — "
                    f"${parsed['total_price']:,.2f} from {parsed['vendor']} "
                    f"({parsed['category']}).\n"
                    f"{saved_str}"
                    f"📢 {ping_user}'s request is approved!\n"
                    f"⚠️ *Needs a Grad Student Buyer to process in Workday / ShopUW.*\n"
                    f"Please assign a buyer: `@Purchasing assign @buyer`"
                ),
                thread_ts=thread_ts,
            )

        # Update or post card in thread
        found_req, found_ts, found_hist, _ = slack_io.find_card_in_thread(client, channel, thread_ts)
        target_card_ts = card_ts or found_ts
        target_req = found_req or parsed or {}
        target_hist = found_hist or []
        now_str = datetime.now().strftime("%m/%d/%y %H:%M")
        appr_name = slack_io.resolve_requester(client, approver) or (f"<@{approver}>" if approver else "Approver")
        if target_card_ts:
            req_payload = dict(target_req)
            req_payload["assignee_id"] = assignee_id
            req_payload["assignee"] = assignee_name
            if bom_fname:
                req_payload["bom_file"] = bom_fname
            if requester and not req_payload.get("requester"):
                req_payload["requester"] = requester
            hist = list(target_hist)
            hist.append(f"Approved by {appr_name} on {now_str}")
            if assignee_id and assignee_name:
                hist.append(f"Assigned to {assignee_name} on {now_str}")
            next_blks = blocks.build_request_blocks("approved", req_payload, history=hist, items=items)
            try:
                client.chat_update(
                    channel=channel,
                    ts=target_card_ts,
                    text="🛒 Purchase Request (Approved)",
                    blocks=next_blks,
                    metadata={
                        "event_type": "purchase_request",
                        "event_payload": req_payload,
                    },
                )
            except Exception as e:
                log.error("Failed to update card on approval: %s", e)

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


def handle_epif_processing(
    client, say, channel: str, thread_ts: str, approver: str, event_ts: str,
    direct_file=None, direct_poster=None,
    assignee_id: str | None = None,
    assignee_name: str | None = None,
    refusal_msg: str | None = None,
    posted_payload: dict | None = None,
    input_note: str | None = None,
    card_ts: str | None = None,
    items: list[dict] | None = None,
    shipping: float = 0.0,
):
    """Core logic to inspect thread/file, parse, validate, and enqueue row write & PDF archiving.

    Per Ticket 14, resolution order is:
      1. direct_file
      2. PDF attachment in thread
      3. posted_payload (from Approve button value)
      4. Slack metadata lookup via find_request_metadata_in_thread
      5. Informational message that no request was found
    """
    log.info("Processing EPIF/purchase request from approver/poster: %s in channel: %s", approver or direct_poster, channel)
    if card_ts:
        card_payload = slack_io.get_card_payload(client, channel, thread_ts, card_ts)
        if card_payload:
            if items is None and "items" in card_payload:
                items = card_payload.get("items")
                shipping = float(card_payload.get("shipping") or 0.0)
    elif posted_payload:
        if items is None and "items" in posted_payload:
            items = posted_payload.get("items")
            shipping = float(posted_payload.get("shipping") or 0.0)

    if direct_file:
        file_obj, poster = direct_file, direct_poster
    else:
        file_obj, poster = slack_io.find_epif_in_thread(client, channel, thread_ts)

    if file_obj is not None:
        # PDF Attachment Path
        if items is None:
            card_req, found_ts, _, _ = slack_io.find_card_in_thread(client, channel, thread_ts)
            if found_ts:
                if not card_ts:
                    card_ts = found_ts
                card_pl = slack_io.get_card_payload(client, channel, thread_ts, found_ts)
                if card_pl and "items" in card_pl:
                    items = card_pl.get("items")
                    shipping = float(card_pl.get("shipping") or 0.0)

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
            assignee_id=assignee_id,
            assignee_name=assignee_name,
            refusal_msg=refusal_msg,
            approver=approver,
            input_note=input_note,
            card_ts=card_ts,
            items=items,
            shipping=shipping,
        )
        return

    # Button Action Payload Path (Ticket 14)
    if posted_payload:
        if "parsed" in posted_payload:
            parsed_req = dict(posted_payload["parsed"])
            modal_req_name = posted_payload.get("requester")
            modal_user_id = posted_payload.get("user_id")
            is_pending = posted_payload.get("is_pending_name", False)
        else:
            parsed_req = dict(posted_payload)
            modal_req_name = posted_payload.get("requester")
            modal_user_id = posted_payload.get("user_id")
            is_pending = posted_payload.get("is_pending_name", False)

        if not assignee_id:
            assignee_id = posted_payload.get("assignee_id")
            assignee_name = posted_payload.get("assignee")

        if parsed_req.get("date_of_purchase") and isinstance(parsed_req["date_of_purchase"], str):
            parsed_req["date_of_purchase"] = epif_parser.parse_date(parsed_req["date_of_purchase"])

        log.info("Found posted payload for purchase request: %s from %s", parsed_req.get("item_description"), modal_req_name)
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
            assignee_id=assignee_id,
            assignee_name=assignee_name,
            refusal_msg=refusal_msg,
            approver=approver,
            input_note=input_note,
            card_ts=card_ts,
            items=items,
            shipping=shipping,
        )
        return

    # Modal Purchase Request in Thread Path via Slack Metadata (for keyword approvals)
    parsed_req, modal_req_name, modal_user_id, is_pending = slack_io.find_request_metadata_in_thread(client, channel, thread_ts)
    if parsed_req:
        if items is None and "items" in parsed_req:
            items = parsed_req.get("items")
            shipping = float(parsed_req.get("shipping") or 0.0)

        if not card_ts:
            _, found_ts, _, _ = slack_io.find_card_in_thread(client, channel, thread_ts)
            if found_ts:
                card_ts = found_ts

        log.info("Found modal purchase request metadata in thread: %s from %s", parsed_req.get("item_description"), modal_req_name)
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
            assignee_id=assignee_id,
            assignee_name=assignee_name,
            refusal_msg=refusal_msg,
            approver=approver,
            input_note=input_note,
            card_ts=card_ts,
            items=items,
            shipping=shipping,
        )
        return

    log.info("No PDF or purchase request found in thread/message %s", thread_ts)
    say(text="I couldn't find a PDF or purchase request in this thread/message.", thread_ts=thread_ts)


def handle_epif_drop(client, say, channel: str, thread_ts: str, user_id: str, file_obj: dict, event_ts: str):
    """Handle an EPIF PDF dropped into a channel thread: parse and post with Approve button."""
    file_name = file_obj.get("name", "EPIF.pdf")
    log.info("Processing EPIF drop '%s' from user %s in channel %s (thread: %s)", file_name, user_id, channel, thread_ts)

    try:
        pdf_bytes = slack_io.download(file_obj)
        log.info("Downloaded %s (%d bytes)", file_name, len(pdf_bytes))
        parsed = epif_parser.parse_epif(pdf_bytes)
    except (epif_parser.FlattenedPdfError, RuntimeError) as error:
        requester = slack_io.resolve_requester(client, user_id)
        if "epif" in file_name.lower():
            slack_io.log_rejection(user_id, file_name, [str(error)], requester_name=requester)
            target_dm = user_id
            slack_io.tell(client, target_dm, str(error))
            if channel != target_dm:
                say(text=f"Error processing {file_name}: {str(error)}", thread_ts=thread_ts)
        else:
            log.debug("Non-EPIF PDF %s failed form parsing; ignoring: %s", file_name, error)
        return
    except Exception as e:
        log.error("Unexpected error parsing dropped PDF %s: %s", file_name, e)
        return

    requester = slack_io.resolve_requester(client, user_id)

    # Build the payload where the PDF is parsed (ticket 04 requirement)
    req_payload = {
        "parsed": {
            **parsed,
            "date_of_purchase": (
                parsed["date_of_purchase"].isoformat()
                if hasattr(parsed.get("date_of_purchase"), "isoformat")
                else (parsed.get("date_of_purchase") or None)
            ),
            "payment_method": parsed.get("payment_method") or "EPIF",
        },
        "requester": requester,
        "user_id": user_id,
        "is_pending_name": False,
        "thread_ts": thread_ts,
        "source": "epif",
    }

    req_blocks = blocks.build_request_blocks("posted", req_payload)

    display_name = requester or f"<@{user_id}>"
    price = parsed.get("total_price")
    if isinstance(price, (int, float)):
        price_str = f"${price:,.2f}"
    elif price:
        price_str = str(price)
        if not price_str.startswith("$"):
            price_str = f"${price_str}"
    else:
        price_str = "$0.00"

    pay_method = req_payload["parsed"].get("payment_method") or "EPIF"

    link_line = f"\n• *Link:* {parsed['link']}" if parsed.get("link") else ""
    summary_text = (
        f"🛒 *New Purchase Request from {display_name}:*\n"
        f"• *Item:* {parsed.get('item_description', '')}\n"
        f"• *Total:* {price_str}\n"
        f"• *Vendor:* {parsed.get('vendor', '')} ({pay_method})\n"
        f"• *Category:* {parsed.get('category', '')}\n"
        f"• *Project ID / Fund:* {parsed.get('project_id', '')} (Fund {parsed.get('fund', '')})\n"
        f"• *Delivery Room:* {parsed.get('delivery_room', '')}\n"
        f"• *Purpose:* {parsed.get('purpose', '')}"
        f"{link_line}\n\n"
        f"Use the buttons below to approve and track this request."
    )

    try:
        client.chat_postMessage(
            channel=channel,
            thread_ts=thread_ts,
            text=summary_text,
            blocks=req_blocks,
            metadata={
                "event_type": "purchase_request",
                "event_payload": req_payload,
            },
        )
        log.info(
            "Posted purchase request card with Approve button for %s in %s (thread: %s)",
            file_name, channel, thread_ts,
        )
    except Exception as e:
        log.error("Failed to post purchase request card to channel %s: %s", channel, e)


def handle_assign(
    client, say, channel: str, thread_ts: str, user_id: str, event_ts: str,
    target_user_id: str | None = None,
    req_data: dict | None = None,
    msg_ts: str | None = None,
    history: list | None = None,
    current_state: str | None = None,
):
    """Assign or reassign a purchase request to a buyer.

    WHY THIS EXISTS:
    ----------------
    ADR 0004 & ADR 0005: Assignment replaces claim. Charlie names the responsible buyer when approving
    (via @-mention or the buyer picker on the posted card), or a buyer can assign an unassigned order.
    Permission per ADR 0004 decision 3:
    - Unassigned: any buyer, approver, or admin may assign (including buyer naming themselves).
    - Assigned: approver, admin, or the current assignee only.
    Selecting a buyer on the posted card (ADR 0005) re-renders the card with the assignee set,
    performing no Excel write, no premature Workday processing announcement, and no email draft DM.
    Once approved, the pre-filled email draft is generated once and DM'd to the assignee.
    """
    if req_data is None:
        card_req, card_ts, card_hist, card_state = slack_io.find_card_in_thread(client, channel, thread_ts)
        req_data = card_req or {}
        msg_ts = msg_ts or card_ts
        history = history if history is not None else list(card_hist)
        current_state = current_state or card_state or "approved"
    else:
        current_state = current_state or "posted"
        history = history if history is not None else []

    current_assignee = req_data.get("assignee_id")

    # If target_user_id is None, check if caller is assigning themselves
    if not target_user_id:
        if roster.is_buyer(user_id):
            target_user_id = user_id
        else:
            say(text="⚠️ Please specify a buyer to assign this order to, e.g. `@Purchasing assign @buyer`.", thread_ts=thread_ts)
            return False

    # Permission check (ADR 0004 decision 3)
    if current_assignee:
        # Assigned: approver, admin, or current assignee only
        if not (admin.is_approved_reviewer(user_id) or admin.is_admin_user(user_id) or user_id == current_assignee):
            log.warning("Unauthorized user %s attempted to reassign request assigned to %s", user_id, current_assignee)
            say(text=f"🔒 This request is already assigned to <@{current_assignee}>. Only the assignee, an approver, or an admin can reassign it.", thread_ts=thread_ts)
            return False
    else:
        # Unassigned: any buyer, approver, or admin may assign
        if not (roster.is_buyer(user_id) or admin.is_approved_reviewer(user_id) or admin.is_admin_user(user_id)):
            log.warning("Unauthorized user %s attempted to assign unassigned request", user_id)
            say(text="🔒 Only buyers, approvers, or admins can assign purchase requests.", thread_ts=thread_ts)
            return False

    # Target eligibility check (ADR 0004 decision 4)
    if not roster.is_buyer(target_user_id):
        log.warning("Target user %s is not on buyers list", target_user_id)
        say(text=f"⚠️ <@{target_user_id}> isn't on the buyers list, so I can't assign this to them. An admin can add them: @Purchasing add-buyer <@{target_user_id}>", thread_ts=thread_ts)
        return False

    target_name = slack_io.resolve_requester(client, target_user_id)
    if not target_name:
        log.warning("Target user %s not registered in roster", target_user_id)
        say(text=f"🔒 <@{target_user_id}> must be registered in the lab roster to be assigned requests. Use `/roster-set-name` first.", thread_ts=thread_ts)
        return False

    # Perform assignment
    now_str = datetime.now().strftime("%m/%d/%y %H:%M")
    actor_name = slack_io.resolve_requester(client, user_id) or f"<@{user_id}>"
    req_data["assignee_id"] = target_user_id
    req_data["assignee"] = target_name

    if current_state != "posted":
        if current_assignee:
            history.append(f"Reassigned to {target_name} by {actor_name} on {now_str}")
        else:
            history.append(f"Assigned to {target_name} on {now_str}")

    if msg_ts:
        card_blocks = blocks.build_request_blocks(current_state, req_data, history=history)
        try:
            client.chat_update(
                channel=channel,
                ts=msg_ts,
                text=f"🛒 Purchase Request ({current_state.capitalize()})",
                blocks=card_blocks,
            )
        except Exception as e:
            log.error("Failed to update message on assign: %s", e)

    if current_state == "posted":
        # Selecting a buyer on the posted card records the selection on the card; approval remains a second click.
        return True

    say(text=f"👤 Assigned to <@{target_user_id}> ({target_name}) to process in Workday / ShopUW.", thread_ts=thread_ts)

    # Email draft DM (with optional BOM) to assignee — single implementation via _send_assignee_dm
    row = slack_io.find_row_in_thread(client, channel, thread_ts)
    row_info = log_writer.get_row_info(row) if row else {}
    draft_data = dict(req_data.get("parsed", req_data))
    for k, v in row_info.items():
        if k not in draft_data or not draft_data[k]:
            draft_data[k] = v
    bom_fname = req_data.get("bom_file")
    bom_path = os.path.join(config.BOMS_DIR, bom_fname) if bom_fname else None
    email_draft = text_rules.generate_email_draft(draft_data, target_name, bom_filename=bom_fname)
    item_desc = draft_data.get("item_description") or "supplies"
    _send_assignee_dm(
        client=client,
        assignee_id=target_user_id,
        assignee_name=target_name,
        email_draft=email_draft,
        item_desc=item_desc,
        row=row,
        bom_path=bom_path,
        bom_fname=bom_fname,
    )

    return True


def handle_processed(
    client, say, channel: str, thread_ts: str, user_id: str, event_ts: str, text: str,
    card_ts: str | None = None, req_data: dict | None = None, history: list | None = None,
):
    """Mark an order as Processed in Workday (Col U) and optionally update Total Price (Col H)."""
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
                f"🛒 Order{item_str} (Row {row}) marked as *Processed* on {today.strftime('%m/%d/%y')}{price_str}.\n"
                f"Please use the buttons on the request message to mark it confirmed once confirmation arrives!"
            ),
            thread_ts=thread_ts,
        )

        target_card_ts = card_ts
        target_req = dict(req_data) if req_data else {}
        target_hist = list(history) if history is not None else []
        if not target_card_ts and thread_ts:
            found_req, found_ts, found_hist, _ = slack_io.find_card_in_thread(client, channel, thread_ts)
            if found_ts:
                target_card_ts = found_ts
                if not target_req and found_req:
                    target_req = found_req
                if not target_hist and found_hist:
                    target_hist = list(found_hist)

        now_str = datetime.now().strftime("%m/%d/%y %H:%M")
        actor_name = user_name or slack_io.resolve_requester(client, user_id) or f"<@{user_id}>"
        target_hist.append(f"Processed by {actor_name} on {now_str}")

        if target_card_ts:
            next_blocks = blocks.build_request_blocks("processed", target_req, history=target_hist)
            try:
                client.chat_update(
                    channel=channel,
                    ts=target_card_ts,
                    text="🛒 Purchase Request (Processed)",
                    blocks=next_blocks,
                )
                log.info("Purchase request message updated to 'processed' by %s in channel %s (ts: %s)", user_id, channel, target_card_ts)
            except Exception as e:
                log.error("Failed to update message on req_processed: %s", e)

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


def handle_confirmation(
    client, say, channel: str, thread_ts: str, user_id: str, event_ts: str, text: str, files=None,
    card_ts: str | None = None, req_data: dict | None = None, history: list | None = None,
):
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

        target_card_ts = card_ts
        target_req = dict(req_data) if req_data else {}
        target_hist = list(history) if history is not None else []
        if not target_card_ts and thread_ts:
            found_req, found_ts, found_hist, _ = slack_io.find_card_in_thread(client, channel, thread_ts)
            if found_ts:
                target_card_ts = found_ts
                if not target_req and found_req:
                    target_req = found_req
                if not target_hist and found_hist:
                    target_hist = list(found_hist)

        now_str = datetime.now().strftime("%m/%d/%y %H:%M")
        actor_name = requester_name or slack_io.resolve_requester(client, user_id) or f"<@{user_id}>"
        target_hist.append(f"Confirmed by {actor_name} on {now_str}")

        if target_card_ts:
            next_blocks = blocks.build_request_blocks("confirmed", target_req, history=target_hist)
            try:
                client.chat_update(
                    channel=channel,
                    ts=target_card_ts,
                    text="🛒 Purchase Request (Confirmed)",
                    blocks=next_blocks,
                )
                log.info("Purchase request message updated to 'confirmed' by %s in channel %s (ts: %s)", user_id, channel, target_card_ts)
            except Exception as e:
                log.error("Failed to update message on req_confirmed: %s", e)

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


def handle_delivery(
    client, say, channel: str, thread_ts: str, user_id: str, event_ts: str, text: str,
    card_ts: str | None = None, req_data: dict | None = None, history: list | None = None,
):
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

        target_card_ts = card_ts
        target_req = dict(req_data) if req_data else {}
        target_hist = list(history) if history is not None else []
        if not target_card_ts and thread_ts:
            found_req, found_ts, found_hist, _ = slack_io.find_card_in_thread(client, channel, thread_ts)
            if found_ts:
                target_card_ts = found_ts
                if not target_req and found_req:
                    target_req = found_req
                if not target_hist and found_hist:
                    target_hist = list(found_hist)

        now_str = datetime.now().strftime("%m/%d/%y %H:%M")
        actor_name = requester_name or slack_io.resolve_requester(client, user_id) or f"<@{user_id}>"
        target_hist.append(f"Delivered to {actor_name} on {now_str}")

        if target_card_ts:
            next_blocks = blocks.build_request_blocks("delivered", target_req, history=target_hist)
            try:
                client.chat_update(
                    channel=channel,
                    ts=target_card_ts,
                    text="🛒 Purchase Request (Delivered)",
                    blocks=next_blocks,
                )
                log.info("Purchase request message updated to 'delivered' by %s in channel %s (ts: %s)", user_id, channel, target_card_ts)
            except Exception as e:
                log.error("Failed to update message on req_delivered: %s", e)

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

    # Determine posting channel (Ticket 15: reads from config, no silent fallback)
    post_channel = config.PURCHASING_CHANNEL
    if not post_channel:
        log.error("PURCHASING_CHANNEL is not configured; refusing to post purchase request.")
        return
    display_name = f"{requester} (pending name confirmation)" if is_pending_name else (requester or f"<@{user_id}>")
    suggest_note = f"\n💡 *Note:* Suggested new vendor: `{custom_vendor}`" if (vendor_choice == config.VENDOR_SUGGEST_OPTION and custom_vendor) else ""

    items = stage2.get("items")
    shipping = float(stage2.get("shipping") or 0.0)
    line_items_text = stage2.get("line_items") or ""
    if items is None and line_items_text.strip():
        items, shipping, _ = bom.parse_line_items(line_items_text)

    req_payload = {
        "parsed": {
            **parsed,
            "date_of_purchase": parsed["date_of_purchase"].isoformat() if parsed["date_of_purchase"] else None,
        },
        "requester": requester,
        "user_id": user_id,
        "is_pending_name": is_pending_name,
        "suggest_note": suggest_note,
        "source": "modal",
    }
    if items:
        req_payload["items"] = items
        req_payload["shipping"] = float(shipping or 0.0)

    req_blocks = blocks.build_request_blocks("posted", req_payload, items=items)

    link_line = f"\n• *Link:* {parsed['link']}" if parsed.get("link") else ""
    items_line = f"\n📋 {len(items)} line items (BOM attached in thread)" if (items and bom.needs_bom(items)) else ""
    summary_text = (
        f"🛒 *New Purchase Request from {display_name}:*\n"
        f"• *Item:* {parsed['item_description']}\n"
        f"• *Total:* ${parsed['total_price']:,.2f}\n"
        f"• *Vendor:* {parsed['vendor']} ({parsed['payment_method']})\n"
        f"• *Category:* {parsed['category']}\n"
        f"• *Project ID / Fund:* {parsed['project_id']} (Fund {parsed['fund']})\n"
        f"• *Delivery Room:* {parsed['delivery_room']}\n"
        f"• *Purpose:* {parsed['purpose']}"
        f"{link_line}"
        f"{items_line}"
        f"{suggest_note}\n\n"
        f"Use the buttons below to approve and track this request."
    )

    try:
        resp = client.chat_postMessage(
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
        return

    card_ts = None
    if isinstance(resp, dict):
        card_ts = resp.get("ts")
    elif hasattr(resp, "data") and isinstance(resp.data, dict):
        card_ts = resp.data.get("ts")
    elif hasattr(resp, "get"):
        card_ts = resp.get("ts")

    if not card_ts or not isinstance(card_ts, str):
        card_ts = "1000.1000"

    if items and bom.needs_bom(items):
        upload_draft_bom(
            client=client,
            channel=post_channel,
            thread_ts=card_ts,
            parsed=parsed,
            items=items,
            shipping=shipping,
        )

    # DM user confirmation
    try:
        slack_io.tell(client, user_id, f"✅ Your purchase request for *{parsed['item_description']}* has been sent to the purchasing channel awaiting approval.")
    except Exception as e:
        log.warning("Could not DM user confirmation: %s", e)

    # If pending name confirmation, post alert with approve button to ADMIN_ALERT_CHANNEL (Phase 2 Ticket 2.3)
    if is_pending_name and config.ADMIN_ALERT_CHANNEL:
        try:
            client.chat_postMessage(
                channel=config.ADMIN_ALERT_CHANNEL,
                text=f"⚠️ New unrecognized user <@{user_id}> opened a purchase request and proposed display name '{requester}'.",
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


# States where cancel is refused — the request has already gone to purchasing (ADR 0003 decision 5).
_CANCEL_REFUSED_STATES = {"processed", "confirmed", "delivered"}


def handle_decline(client, channel: str, msg_ts: str, user_id: str, req_data: dict, history: list):
    """Decline a posted purchase request.

    WHY THIS EXISTS:
        Decline is an approver's or buyer's "no" on a request in the posted state.
        It updates the message to show it was declined and by whom, and removes
        every button.  Nothing is written to Excel (no row exists yet),
        no alert is posted, and no DM is sent (ADR 0003 decision 3).
    """
    user_name = slack_io.resolve_requester(client, user_id) or f"<@{user_id}>"
    now_str = datetime.now().strftime("%m/%d/%y %H:%M")
    history.append(f"Declined by {user_name} on {now_str}")
    declined_blocks = blocks.build_request_blocks("declined", req_data, history=history)
    try:
        client.chat_update(
            channel=channel,
            ts=msg_ts,
            text="Purchase Request (Declined)",
            blocks=declined_blocks,
        )
        log.info("Purchase request declined by %s in channel %s (ts: %s)", user_id, channel, msg_ts)
    except Exception as e:
        log.error("Failed to update message on decline: %s", e)


def _move_bom_to_cancelled(bom_fname: str) -> None:
    """Move the named BOM file from BOMS_DIR into BOMS_DIR/Cancelled/.

    WHY THIS EXISTS:
        ADR 0006 decision 7: when a request is cancelled the archived BOM must move
        into Cancelled/ so the live folder matches the live log, and a recycled row
        number cannot collide with a stale sheet.
        A missing file is logged as a warning and the function returns normally so
        the cancel can still complete — a file that was never saved must not leave a
        cancelled purchase sitting in the log (ticket 31).
    """
    src_path = os.path.join(config.BOMS_DIR, bom_fname)
    if not os.path.exists(src_path):
        log.warning(
            "Cancel: BOM %s not found at %s; cancellation continues without moving it",
            bom_fname,
            src_path,
        )
        return
    cancelled_dir = os.path.join(config.BOMS_DIR, "Cancelled")
    os.makedirs(cancelled_dir, exist_ok=True)
    dst_path = os.path.join(cancelled_dir, bom_fname)
    shutil.move(src_path, dst_path)
    log.info("Moved BOM %s to Cancelled/ on cancel", bom_fname)


def handle_cancel(client, say, channel: str, thread_ts: str, msg_ts: str, user_id: str, req_data: dict, state: str, history: list):
    """Cancel an approved purchase request, blanking its Excel row(s).

    WHY THIS EXISTS:
        Cancel un-writes the Excel row — the workbook is a log of live approved
        purchases and their stage, nothing else (ADR 0003 decision 4).
        Cancel is refused once a request is processed because a Workday
        requisition or ShopUW cart is already out in the world (ADR 0003 decision 5).
        Both approvers and admins can cancel; buyers cannot (ADR 0003 decision 6).
        A batch (multiple EPIFs in one thread) is cancelled as a batch — every
        row is blanked in a single queued write (ADR 0003 decision 7).
        At cancel, the archived BOM is moved to BOMS_DIR/Cancelled/ (ADR 0006
        decision 7, ticket 31), inside the same write task as the row blanking.
    """
    if state in _CANCEL_REFUSED_STATES:
        say(
            text=(
                "This request has already been sent to the purchasing team and cannot be cancelled here.\n"
                "To reverse it, contact the purchasing team (Tina / Ally / Lisa) directly."
            ),
            thread_ts=thread_ts,
        )
        log.info(
            "Cancel refused for state=%s by %s in channel %s (ts: %s)", state, user_id, channel, msg_ts
        )
        return False

    user_name = slack_io.resolve_requester(client, user_id) or f"<@{user_id}>"
    now_str = datetime.now().strftime("%m/%d/%y %H:%M")
    history.append(f"Cancelled by {user_name} on {now_str}")

    rows = slack_io.find_all_rows_in_thread(client, channel, thread_ts)
    bom_fname = req_data.get("bom_file")

    if rows:
        def write_action():
            for row in rows:
                log_writer.blank_row(row)
            if bom_fname:
                _move_bom_to_cancelled(bom_fname)
            return rows

        def on_success(res):
            log.info("Blanked row(s) %s for cancelled request by %s in channel %s", res, user_id, channel)

        def on_failure(error):
            log.error("Failed to blank row(s) %s on cancel: %s", rows, error)

        queue_worker.submit_write_task(
            action_fn=write_action,
            channel=channel,
            thread_ts=thread_ts,
            user_id=user_id,
            task_type="blank",
            description=f"Cancel rows {rows} by {user_name}",
            success_callback=on_success,
            failure_callback=on_failure,
            client=client,
        )
    else:
        if bom_fname:
            _move_bom_to_cancelled(bom_fname)
        log.warning("Cancel: no logged rows found in thread %s; nothing blanked", thread_ts)

    cancelled_blocks = blocks.build_request_blocks("cancelled", req_data, history=history)
    try:
        client.chat_update(
            channel=channel,
            ts=msg_ts,
            text="Purchase Request (Cancelled)",
            blocks=cancelled_blocks,
        )
        log.info("Purchase request cancelled by %s in channel %s (ts: %s)", user_id, channel, msg_ts)
    except Exception as e:
        log.error("Failed to update message on cancel: %s", e)

    return True


def upload_draft_bom(
    client,
    channel: str,
    thread_ts: str,
    parsed: dict,
    items: list[dict],
    shipping: float = 0.0,
) -> bool:
    """Upload an in-memory draft BOM spreadsheet to the thread using files_upload_v2.

    WHY THIS EXISTS:
    ----------------
    Single function for uploading draft BOM spreadsheets (invariant 1).
    Used by:
    1. handle_items_update (dropped EPIF path and Edit modal path)
    2. _process_interview_completion (interview /new-purchase path)
    The draft workbook is generated in-memory with row=None and uploaded directly
    to the thread without saving to BOMS_DIR (only approved requests are archived).
    """
    if not bom.needs_bom(items):
        return False

    vendor = (parsed or {}).get("vendor") or "Vendor"
    draft_filename = bom.bom_filename(None, vendor)
    xlsx_bytes = bom.build_bom_workbook(
        parsed or {},
        items,
        shipping=shipping,
        row=None,
    )
    try:
        if hasattr(client, "files_upload_v2"):
            client.files_upload_v2(
                channel=channel,
                thread_ts=thread_ts,
                content=xlsx_bytes,
                filename=draft_filename,
                title=draft_filename,
            )
        else:
            client.files_upload(
                channels=channel,
                thread_ts=thread_ts,
                content=xlsx_bytes,
                filename=draft_filename,
                title=draft_filename,
            )
        log.info("Uploaded draft BOM %s to thread %s in %s", draft_filename, thread_ts, channel)
        return True
    except Exception as e:
        log.warning("Could not upload draft BOM %s: %s", draft_filename, e)
        return False


def upload_archived_bom(
    client,
    channel: str,
    thread_ts: str,
    file_path: str,
    filename: str,
) -> bool:
    """Upload an archived BOM spreadsheet from disk to the thread using files_upload_v2 / files_upload.

    WHY THIS EXISTS:
    ----------------
    Per Ticket 29 / ADR 0006 decision 6: At approval, the archived BOM spreadsheet
    is saved to BOMS_DIR/NNNN_<Vendor>_BOM.xlsx, pointed at by the log row's Notes column,
    and uploaded to the purchasing thread so the itemised order sits beside the conversation
    that approved it.
    """
    try:
        with open(file_path, "rb") as f:
            content = f.read()
        if hasattr(client, "files_upload_v2"):
            kwargs = {
                "channel": channel,
                "file": file_path,
                "content": content,
                "filename": filename,
                "title": filename,
            }
            if thread_ts:
                kwargs["thread_ts"] = thread_ts
            client.files_upload_v2(**kwargs)
        else:
            kwargs = {
                "channels": channel,
                "file": file_path,
                "content": content,
                "filename": filename,
                "title": filename,
            }
            if thread_ts:
                kwargs["thread_ts"] = thread_ts
            client.files_upload(**kwargs)
        log.info("Uploaded archived BOM %s to thread %s in %s", filename, thread_ts, channel)
        return True
    except Exception as e:
        log.warning("Could not upload archived BOM %s: %s", filename, e)
        return False


def handle_items_update(
    client,
    channel: str,
    thread_ts: str,
    card_ts: str,
    items: list[dict],
    shipping: float,
    user_id: str,
) -> bool:
    """Save updated line items to card metadata, update card blocks, post edit notice, and upload draft BOM.

    WHY THIS EXISTS:
    ----------------
    Single handler for updating line items on a posted card (invariant 1).
    Called by both the EPIF path (Ticket 27), the interview modal path (Ticket 28),
    and Edit (Ticket 32).
    ADR 0006 decision 5: items are stored in message metadata, never button value.
    Draft BOM is uploaded to thread via files_upload_v2 and NEVER saved to BOMS_DIR (only approval archives).
    """
    card_payload = slack_io.get_card_payload(client, channel, thread_ts, card_ts)
    if not card_payload:
        log.warning("Could not find card payload for ts %s in channel %s", card_ts, channel)
        return False

    state = card_payload.get("state", "posted")
    if state != "posted":
        log.warning("Card %s in channel %s is in state '%s', not 'posted'", card_ts, channel, state)
        slack_io.tell(client, user_id, "⚠️ This purchase request has already been approved and line items can no longer be edited.")
        return False

    new_payload = dict(card_payload)
    new_payload["items"] = items
    new_payload["shipping"] = float(shipping or 0.0)
    if "source" not in new_payload:
        new_payload["source"] = "epif"

    change_fragments = bom.describe_changes(card_payload, new_payload)
    if not change_fragments:
        return True

    user_name = slack_io.resolve_requester(client, user_id) or f"<@{user_id}>"
    edit_line = f"✏️ Edited by {user_name}: {'; '.join(change_fragments)}"

    history = list(card_payload.get("history") or [])
    history.append(edit_line)
    new_payload["history"] = history

    new_blocks = blocks.build_request_blocks("posted", new_payload, history=history, items=items)
    summary_text = f"🛒 Purchase Request ({state.capitalize()})"

    try:
        client.chat_update(
            channel=channel,
            ts=card_ts,
            text=summary_text,
            blocks=new_blocks,
            metadata={
                "event_type": "purchase_request",
                "event_payload": new_payload,
            },
        )
        log.info("Updated line items on card %s in %s (thread: %s)", card_ts, channel, thread_ts)
    except Exception as e:
        log.error("Failed to chat_update card %s with new items: %s", card_ts, e)
        return False

    try:
        client.chat_postMessage(channel=channel, thread_ts=thread_ts, text=edit_line)
    except Exception as e:
        log.warning("Failed to post edit notice to thread %s: %s", thread_ts, e)

    upload_draft_bom(
        client=client,
        channel=channel,
        thread_ts=thread_ts,
        parsed=new_payload.get("parsed") or {},
        items=items,
        shipping=shipping,
    )

    return True

