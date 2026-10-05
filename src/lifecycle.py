"""Purchase request lifecycle operations.

WHY THIS EXISTS:
----------------
Encapsulates all stage transitions for a purchase request: approval, assignment,
processing, confirmation, delivery, and quote archiving. Coordinates between
Slack client I/O, domain validation, storage write queue, and Block Kit messages.

Per ADR 0004:
- The approver names the responsible buyer in the approval message itself (@Dylan @Purchasing approved).
- Claim is deleted entirely. Requests without a valid buyer mention are approved and unassigned.
- Any buyer, approver, or admin can assign or reassign a request until it is Processed (ADR 0011).
- From Processed onward, assignment is refused with "Already Processed by ...".
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

Per Ticket 83 / ADR 0012 decision 5:
- finalize_purchase_request files an attached BOM byte-for-byte (never opened, no made BOM
  built for it, Notes 'BOM: <name> (attached)') and numbered quotes via bom.quote_filename;
  the approved card then carries quote_count instead of the attachment list. A file that
  will not download is skipped with an admin alert; approval never fails over it.
- _send_assignee_dm uploads the archived quotes to the buyer beside the BOM; handle_assign
  rebuilds their paths from quote_count + row + vendor.

Per Ticket 82 / ADR 0012 Decisions 1-4:
- An attachment with role 'bom' (the requester's own sheet, carried never read) adds a
  '📎 BOM attached: <name>' summary line and is posted to the thread like a quote; no
  made BOM (upload_draft_bom) is built for it.

Per Ticket 81 / ADR 0012:
- Adds post_attachments_to_thread to download attached quotes and re-post them
  to the thread right after card posting.
- _process_interview_completion copies stage2 attachments into req_payload
  and passes them to build_request_blocks.
- Attachment download failures alert both the thread and the requester via DM.

Per Ticket 33:
- handle_epif_drop supersedes any posted card in the same thread from the same
  requester and vendor before posting the new card (ADR 0006 decision 9).
  Approved or later cards are never touched.

Per Ticket 32:
- handle_request_edit updates a modal-born posted card in place after the requester,
  a buyer, or an admin submits the edit form (ADR 0006 decision 8).
- The submit handler in app.py validates fields, checks the card is still posted,
  then acks. handle_request_edit rebuilds parsed, calls describe_changes, updates
  the card (blocks + metadata), posts the edit line, and re-posts the draft BOM
  when items changed. No changes → nothing posted, no history line.

Per Ticket 41 (ADR 0007 decision 4):
- A bare-thread "This needs an EPIF" interview carries `bare_thread` context in its
  private metadata. _process_interview_completion hands that to
  _finalize_bare_thread_epif, which calls finalize_purchase_request against the
  existing waiting card; no new card (and no Approve button) is ever posted, because
  approval already happened.

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
Per Ticket 57 (ADR 0009 decision 6):
- finalize_purchase_request, handle_processed, and handle_delivery catch StorageLocationError
  in their on_failure callbacks and reply in-thread with text_rules.storage_problem_message.

Per Ticket 64 (ADR 0010 decision 1):
- Approval always leaves a card in the thread. When target_card_ts is not found,
  finalize_purchase_request posts an approved-state card with History and buttons
  via chat_postMessage instead of doing nothing. A failing post is logged at ERROR
  and does not undo the approval.

Per Ticket 65 (ADR 0010 decision 7):
- A missing card or a failed drop is reported loudly to config.ADMIN_ALERT_CHANNEL.
- In handle_epif_drop, parse failures (for EPIF-named PDFs), unexpected errors (for EPIF-named PDFs),
  and card post failures alert admins via slack_io.alert_admins and text_rules.format_card_failure_alert.
- handle_epif_drop logs each exit with 'drop exit: <reason>' at INFO level.
- In finalize_purchase_request, failed card updates and failed fallback card posts alert admins.

Per Ticket 67 (ADR 0010 decisions 2 & 3):
- The assigned buyer's DM carries a card with next-step button (DM card).
- _send_assignee_dm posts the DM card after draft and file uploads and returns (dm_channel, dm_ts).
- finalize_purchase_request updates or posts the thread card before sending the DM, then records
  dm_channel and dm_ts in the thread card payload and updates it.
- handle_assign posts the DM card upon later assignment and records dm_channel and dm_ts in the thread card.
- A failed DM card alerts admins and never reverses the approval.

Per Ticket 69 (ADR 0010 decision 3):
- Both cards move together: sync_dm_card updates the buyer's DM card across all stages
  (handle_processed, handle_confirmation, handle_delivery), cancel (handle_cancel),
  and reassignment (handle_assign).
- Retired states (cancelled, reassigned, delivered) remove buttons from the DM card.
- Reassignment retires the old buyer's DM card before posting to the new buyer.
- sync_dm_card is a no-op if no dm_channel/dm_ts, never raises, and alerts admins on failure.

Per Ticket 76 (ADR 0011 decision 3):
- Approval writes an entry into the request log (requests.json via store).
- Assignment in any state other than posted updates the buyer and appends history in the request log.
- All request log writes are wrapped in _request_log; errors alert config.ADMIN_ALERT_CHANNEL and never block.

Per Ticket 77 (ADR 0011 decision 3):
- Stage transitions (processed, confirmed, delivered) and cancel append history lines in the request log.
- Cancel sets cancelled=True in the request log without deleting the record.
- All request log writes are wrapped in _request_log; errors alert config.ADMIN_ALERT_CHANNEL and never block.

Per Ticket 93 (ADR 0013 decision 7):
- A card's request-log entry is created when the card is POSTED (modal or EPIF drop), not at approval.
  finalize_purchase_request then updates that entry, matched by card (store.find_id_by_card); the thread
  lookup is only a fallback for an entry that was never posted, because a thread can hold several cards.
- Decline sets declined=True and a superseding EPIF drop sets superseded=True on that card's entry.

Imports:
    - admin, blocks, bom, config, epif_parser, interview, log_writer, queue_worker, roster, slack_io, store, text_rules, validators
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
        store,
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
    import store  # type: ignore[no-redef]
    import text_rules
    import validators

log = logging.getLogger("p-bot")


def _request_log(client, fn, *args, **kwargs):
    """Execute a store function safely, alerting admins on error.

    Per ADR 0011 / Ticket 76:
    The request log sits beside the cards and workbook. A write failure must
    never block an approval, button click, or DM. On any exception, log at ERROR,
    alert config.ADMIN_ALERT_CHANNEL via slack_io.alert_admins, and return None.
    """
    try:
        return fn(*args, **kwargs)
    except Exception as e:
        log.error("Couldn't write the request log (requests.json): %s", e, exc_info=True)
        slack_io.alert_admins(client, f"⚠️ Couldn't write the request log (requests.json): {e}")
        return None


def _log_posted_card(client, channel: str, thread_ts: str, card_ts: str | None, requester: str, requester_id: str | None):
    """Create the request-log entry for a card the moment it is posted.

    WHY THIS EXISTS:
        ADR 0013 decision 7: the approved nudge must find requests nobody has approved yet, so
        the entry starts at posting and approval later updates it (one history per request).
        Goes through _request_log, so a log failure alerts and never blocks posting.
    """
    now = datetime.now()
    _request_log(
        client,
        store.create,
        channel=channel,
        thread_ts=thread_ts,
        card_ts=card_ts,
        requester=requester,
        requester_id=requester_id,
        posted_at=now.isoformat(timespec="seconds"),
        history=[f"Posted by {requester} on {now.strftime('%m/%d/%y %H:%M')}"],
    )


def _flag_card_entry(client, channel: str, card_ts: str, line: str, **flags):
    """Set flags (declined / superseded) and a history line on the entry for this card, if any."""
    req_id = _request_log(client, store.find_id_by_card, channel, card_ts)
    if req_id:
        _request_log(client, store.update, req_id, **flags)
        _request_log(client, store.append_history, req_id, line)


def _send_assignee_dm(
    client,
    assignee_id: str,
    assignee_name: str,
    email_draft: str,
    item_desc: str,
    row,
    bom_path: str | None = None,
    bom_fname: str | None = None,
    epif_path: str | None = None,
    epif_fname: str | None = None,
    route: str = "workday",
    parsed: dict | None = None,
    thread_channel: str | None = None,
    thread_ts: str | None = None,
    card_ts: str | None = None,
    request: dict | None = None,
    state: str | None = None,
    quote_paths: list[str] | None = None,
) -> tuple[str, str] | None:
    """Send the email-draft DM to the assigned buyer, optionally attaching the archived BOM,
    and post the linked DM card with the next-step button.

    WHY THIS EXISTS:
    ----------------
    Single implementation of the assignee DM (invariant 1).
    Called by finalize_purchase_request (at approval) and handle_assign (at post-approval assignment).
    Per ADR 0006 decision 6 and spec decision 4: the archived BOM is attached to this DM
    so the buyer forwards one EPIF and one sheet instead of pasting links.
    Ticket 83 / ADR 0012 decision 5: archived vendor quotes ride along the same way as the BOM.
    A failed BOM upload is logged and alerted to admin but never reverses the approval
    (same spirit as ADR 0004 decision 2 — the money decision already happened).
    Per ADR 0010 decisions 2 & 3 & Ticket 67:
    After the email draft and file uploads, posts a linked DM card as its own message
    and returns (dm_channel, dm_ts) so the thread card can record the location.
    """
    row_dm_str = f" in *Row {row}*" if row else ""
    if route == "workday":
        vendor = (parsed or {}).get("vendor") or "Vendor"
        price = (parsed or {}).get("total_price")
        if isinstance(price, (int, float)):
            price_str = f"${price:,.2f}"
        elif price:
            price_str = str(price)
            if not price_str.startswith("$"):
                price_str = f"${price_str}"
        else:
            price_str = "$0.00"
        link = (parsed or {}).get("link") or "No link"
        dm_text = (
            f"Place this in Workday:\n"
            f"• *Item:* {item_desc}\n"
            f"• *Vendor:* {vendor}\n"
            f"• *Price:* {price_str}\n"
            f"• *Link:* {link}\n"
            f"• *Row:* {row or 'None'}\n\n"
            f"Use the buttons on your purchase request in the purchasing channel to update its status when processed, confirmed, and delivered!"
        )
    else:
        dm_text = (
            f"Hi {assignee_name}! You've been assigned the purchase request for *{item_desc}*{row_dm_str}.\n\n"
            f"📋 *Next Steps:*\n"
            f"1. Submit via Workday or send this email to purchasing (Tina / Ally / Lisa):\n\n"
            f"```\n{email_draft}\n```\n\n"
            f"2. Use the buttons on your purchase request in the purchasing channel to update its status when processed, confirmed, and delivered!"
        )
        if epif_fname:
            dm_text += f"\n\n📄 The filled EPIF *{epif_fname}* is attached."
        if bom_fname:
            dm_text += f"\n\n📊 The BOM spreadsheet *{bom_fname}* is attached."
        if quote_paths:
            dm_text += f"\n\n📎 {len(quote_paths)} vendor quote(s) attached."
    try:
        slack_io.tell(client, assignee_id, dm_text)
    except Exception as e:
        log.warning("Could not DM assignee %s: %s", assignee_id, e)
        return None

    if route == "epif":
        files_to_upload = []
        if epif_path and epif_fname and os.path.exists(epif_path):
            files_to_upload.append((epif_path, epif_fname))
        if bom_path and bom_fname and os.path.exists(bom_path):
            files_to_upload.append((bom_path, bom_fname))
        for qpath in quote_paths or []:
            if qpath and os.path.exists(qpath):
                files_to_upload.append((qpath, os.path.basename(qpath)))

        if files_to_upload:
            try:
                resp = client.conversations_open(users=assignee_id)
                dm_channel = resp["channel"]["id"]
                for path, fname in files_to_upload:
                    try:
                        with open(path, "rb") as fh:
                            content = fh.read()
                        if hasattr(client, "files_upload_v2"):
                            client.files_upload_v2(
                                channel=dm_channel,
                                content=content,
                                filename=fname,
                                title=fname,
                            )
                        else:
                            client.files_upload(
                                channels=dm_channel,
                                content=content,
                                filename=fname,
                                title=fname,
                            )
                        log.info("Uploaded %s to DM for %s", fname, assignee_id)
                    except Exception as e:
                        log.warning("Could not upload %s to DM for %s: %s", fname, assignee_id, e)
                        if config.ADMIN_ALERT_CHANNEL:
                            try:
                                client.chat_postMessage(
                                    channel=config.ADMIN_ALERT_CHANNEL,
                                    text=f"⚠️ Failed to attach *{fname}* to {assignee_name}'s DM: {e}",
                                )
                            except Exception as alert_err:
                                log.warning("Could not alert admin about DM attachment failure: %s", alert_err)
            except Exception as e:
                log.warning("Could not open DM channel for assignee %s: %s", assignee_id, e)

    # Post the linked DM card (Ticket 67 / ADR 0010 decision 2)
    if not card_ts:
        log.warning("No card_ts provided to _send_assignee_dm; skipping DM card for %s", assignee_id)
        return None

    thread_link = None
    if thread_channel and card_ts:
        try:
            resp = client.chat_getPermalink(channel=thread_channel, message_ts=card_ts)
            if isinstance(resp, dict):
                thread_link = resp.get("permalink")
            elif hasattr(resp, "data") and isinstance(resp.data, dict):
                thread_link = resp.data.get("permalink")
            elif hasattr(resp, "get"):
                thread_link = resp.get("permalink")
        except Exception as e:
            log.warning("Could not get permalink for thread card (%s, %s): %s", thread_channel, card_ts, e)
            thread_link = None

    req_dict = dict(request or {})
    if row is not None and "row" not in req_dict:
        req_dict["row"] = row
    if parsed and "parsed" not in req_dict:
        req_dict["parsed"] = parsed
    dm_state = state or "approved"

    dm_blocks = blocks.build_dm_card_blocks(
        state=dm_state,
        request=req_dict,
        thread_channel=thread_channel or "",
        thread_ts=thread_ts or "",
        card_ts=card_ts,
        thread_link=thread_link,
    )

    dm_res = slack_io.post_dm_card(
        client=client,
        user_id=assignee_id,
        text=f"🛒 Purchase Request ({dm_state.capitalize()})",
        blocks=dm_blocks,
    )
    if not dm_res:
        slack_io.alert_admins(
            client,
            text_rules.format_card_failure_alert(
                step="post the buyer's DM card",
                channel=thread_channel or "",
                thread_ts=thread_ts or "",
                file_name=None,
                error="chat.postMessage failed",
            ),
        )
        return None

    return dm_res


def sync_dm_card(
    client,
    request: dict | None,
    state: str,
    channel: str,
    thread_ts: str,
    card_ts: str,
    history: list | None = None,
    note: str | None = None,
) -> bool:
    """Rebuild and update the buyer's linked DM card.

    WHY THIS EXISTS:
    ----------------
    ADR 0010 Decision 3 & Ticket 69:
    Whichever card is clicked — or the @Purchasing processed keyword is used — the thread card
    and the DM card end up at the same stage with the same next button. The DM card is a view
    rebuilt from the thread card's request (carrying dm_channel and dm_ts).
    Returns False when request has no dm_channel/dm_ts or on error; returns True on success.
    Never raises: on any failure it logs a WARNING and alerts the admin channel.
    """
    if not request or not isinstance(request, dict):
        return False
    dm_channel = request.get("dm_channel")
    dm_ts = request.get("dm_ts")
    if not dm_channel or not dm_ts:
        return False

    try:
        thread_link = None
        if channel and card_ts:
            try:
                resp = client.chat_getPermalink(channel=channel, message_ts=card_ts)
                if isinstance(resp, dict):
                    thread_link = resp.get("permalink")
                elif hasattr(resp, "data") and isinstance(resp.data, dict):
                    thread_link = resp.data.get("permalink")
                elif hasattr(resp, "get"):
                    thread_link = resp.get("permalink")
            except Exception as e:
                log.warning("Could not get permalink for thread card (%s, %s): %s", channel, card_ts, e)
                thread_link = None

        dm_blocks = blocks.build_dm_card_blocks(
            state=state,
            request=request,
            thread_channel=channel,
            thread_ts=thread_ts,
            card_ts=card_ts,
            thread_link=thread_link,
            note=note,
        )
        client.chat_update(
            channel=dm_channel,
            ts=dm_ts,
            text=f"🛒 Purchase Request ({state.capitalize()})",
            blocks=dm_blocks,
        )
        return True
    except Exception as e:
        log.warning("Could not sync DM card for %s at ts %s: %s", dm_channel, dm_ts, e)
        slack_io.alert_admins(
            client,
            text_rules.format_card_failure_alert(
                step="update the buyer's DM card",
                channel=channel,
                thread_ts=thread_ts,
                file_name=None,
                error=str(e),
            ),
        )
        return False


def _fetch_attachment(client, attachment: dict, row_num) -> bytes | None:
    """Fetch one attached file's bytes from Slack at approval; None (and an admin alert) on failure.

    WHY THIS EXISTS:
    ----------------
    Ticket 83 / ADR 0012 decision 5: the money decision has already happened by the time files
    are filed, so a file that will not download never fails the approval. It is skipped, and
    never silently: the admin channel is told which file and which log row.
    """
    fname = attachment.get("name") or "attachment"
    try:
        info = client.files_info(file=attachment.get("id"))
        file_obj = info.get("file", info) if isinstance(info, dict) else info["file"]
        return slack_io.download_file(file_obj)
    except Exception as e:
        log.warning("Could not fetch attachment '%s' for row %s: %s", fname, row_num, e)
        slack_io.alert_admins(
            client,
            f"⚠️ Couldn't fetch attached file `{fname}` for row {row_num}; it was not archived. "
            f"Approval went ahead. ({e})",
        )
        return None


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
    attachments: list[dict] | None = None,
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
        saved_quote_paths: list[str] = []
        try:
            route = interview.get_request_route(parsed, has_file=bool(pdf_bytes))
            if pdf_bytes and file_name:
                vendor = parsed.get("vendor") or "Vendor"
                total_price = parsed.get("total_price") or 0.0
                project_id = parsed.get("project_id") or "NoProject"
                existing_files = os.listdir(config.EPIFS_DIR) if os.path.exists(config.EPIFS_DIR) else []
                archive_name = log_writer.epif_archive_name(
                    vendor, total_price, project_id, existing_files
                )
                saved_epif_path = log_writer.save_epif(pdf_bytes, archive_name)
            elif not pdf_bytes and route == "epif":
                try:
                    from . import epif_filler
                except ImportError:
                    import epif_filler

                vendor = parsed.get("vendor") or "Vendor"
                total_price = parsed.get("total_price") or 0.0
                project_id = parsed.get("project_id") or "NoProject"
                existing_files = os.listdir(config.EPIFS_DIR) if os.path.exists(config.EPIFS_DIR) else []
                archive_name = log_writer.epif_archive_name(
                    vendor, total_price, project_id, existing_files
                )
                try:
                    with open(config.EPIF_TEMPLATE_PATH, "rb") as f:
                        template_bytes = f.read()
                    filled_bytes = epif_filler.fill_epif(template_bytes, parsed)
                    saved_epif_path = log_writer.save_epif(filled_bytes, archive_name)
                except FileNotFoundError:
                    # Reraise so blank_row executes as this is an all-or-nothing step
                    raise

            vendor = parsed.get("vendor") or "Vendor"
            attached_boms = [a for a in (attachments or []) if a.get("role") == "bom"]
            attached_quotes = [a for a in (attachments or []) if a.get("role") == "quote"]

            if attached_boms:
                # ADR 0012 decision 5: an attached BOM is filed byte-for-byte, never opened,
                # and no made BOM is built for the same request.
                a = attached_boms[0]
                content = _fetch_attachment(client, a, row_num)
                if content is not None:
                    ext = os.path.splitext(a.get("name") or "")[1].lstrip(".").lower() or "xlsx"
                    bom_fname = bom.bom_filename(row_num, vendor, ext=ext)
                    saved_bom_path = log_writer.save_bom(content, bom_fname)
                    log_writer.update_row(row_num, {config.COLUMN_NOTES: f"BOM: {bom_fname} (attached)"})
            elif items and bom.needs_bom(items):
                bom_fname = bom.bom_filename(row_num, vendor)
                req_for_bom = dict(parsed)
                if requester and not req_for_bom.get("requester"):
                    req_for_bom["requester"] = requester
                xlsx_bytes = bom.build_bom_workbook(req_for_bom, items)
                saved_bom_path = log_writer.save_bom(xlsx_bytes, bom_fname)
                notes_text = f"BOM: {bom_fname} ({len(items)} items)"
                log_writer.update_row(row_num, {config.COLUMN_NOTES: notes_text})

            for k, a in enumerate(attached_quotes, start=1):
                content = _fetch_attachment(client, a, row_num)
                if content is None:
                    continue
                saved_quote_paths.append(
                    log_writer.save_quote(content, bom.quote_filename(row_num, vendor, k))
                )
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
            for qp in saved_quote_paths:
                try:
                    os.remove(qp)
                except Exception:
                    pass
            raise

        # Result shape grows only as needed: (row, epif), (+bom name, path), (+quote paths).
        if saved_quote_paths:
            return row_num, saved_epif_path, bom_fname, saved_bom_path, saved_quote_paths
        if bom_fname and saved_bom_path:
            return row_num, saved_epif_path, bom_fname, saved_bom_path
        return row_num, saved_epif_path

    def on_success(result):
        row, saved_path = result[0], result[1]
        bom_fname, saved_bom_path = (result[2], result[3]) if len(result) >= 4 else (None, None)
        saved_quote_paths = list(result[4]) if len(result) >= 5 else []
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
            route = interview.get_request_route(parsed, bool(pdf_bytes))
            action_text = "to place in Workday." if route == "workday" else "to email to purchasing."
            say(
                text=(
                    f"Logged to row {row}: {parsed['item_description']} — "
                    f"${parsed['total_price']:,.2f} from {parsed['vendor']} "
                    f"({parsed['category']}).\n"
                    f"{saved_str}"
                    f"📢 {ping_user}'s request is approved!\n"
                    f"👤 Assigned to <@{assignee_id}> ({assignee_name}) {action_text}"
                    + (f" ({input_note})" if input_note else "")
                ),
                thread_ts=thread_ts,
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
            route = interview.get_request_route(parsed, bool(pdf_bytes))
            action_text = "to place in Workday." if route == "workday" else "to email to purchasing."
            say(
                text=(
                    f"Logged to row {row}: {parsed['item_description']} — "
                    f"${parsed['total_price']:,.2f} from {parsed['vendor']} "
                    f"({parsed['category']}).\n"
                    f"{saved_str}"
                    f"📢 {ping_user}'s request is approved!\n"
                    f"⚠️ *Needs a buyer {action_text}*\n"
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
        hist = list(target_hist)
        hist.append(f"Approved by {appr_name} on {now_str}")
        if assignee_id and assignee_name:
            hist.append(f"Assigned to {assignee_name} on {now_str}")

        if target_card_ts:
            req_payload = dict(target_req)
        else:
            parsed_date = parsed.get("date_of_purchase")
            iso_date = (
                parsed_date.isoformat()
                if hasattr(parsed_date, "isoformat")
                else (parsed_date or None)
            )
            req_payload = {
                "parsed": {
                    **parsed,
                    "date_of_purchase": iso_date,
                    "payment_method": parsed.get("payment_method") or "EPIF",
                },
                "requester": requester,
                "user_id": notify_target,
                "is_pending_name": is_pending_name,
                "thread_ts": thread_ts,
            }
            if pdf_bytes:
                req_payload["source"] = "epif"
            if items:
                req_payload["items"] = items
                req_payload["shipping"] = float(shipping or 0.0)

        req_payload["state"] = "approved"
        req_payload["assignee_id"] = assignee_id
        req_payload["assignee"] = assignee_name
        if saved_path:
            req_payload["epif_file"] = os.path.basename(saved_path.replace("\\", "/"))
        if bom_fname:
            req_payload["bom_file"] = bom_fname
        # After approval the card carries a count, not the attachment list (button values are
        # size-capped); archived names are derived with bom.quote_filename.
        req_payload.pop("attachments", None)
        quote_total = sum(1 for a in (attachments or []) if a.get("role") == "quote")
        if quote_total:
            req_payload["quote_count"] = quote_total
        if requester and not req_payload.get("requester"):
            req_payload["requester"] = requester

        next_blks = blocks.build_request_blocks("approved", req_payload, history=hist, items=items)

        actual_card_ts = target_card_ts
        if target_card_ts:
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
                slack_io.alert_admins(
                    client,
                    text_rules.format_card_failure_alert(
                        step="update the approval card",
                        channel=channel,
                        thread_ts=thread_ts,
                        file_name=file_name,
                        error=str(e),
                    ),
                )
        else:
            try:
                resp = client.chat_postMessage(
                    channel=channel,
                    thread_ts=thread_ts,
                    text="🛒 Purchase Request (Approved)",
                    blocks=next_blks,
                    metadata={
                        "event_type": "purchase_request",
                        "event_payload": req_payload,
                    },
                )
                if isinstance(resp, dict):
                    actual_card_ts = resp.get("ts")
                elif hasattr(resp, "data") and isinstance(resp.data, dict):
                    actual_card_ts = resp.data.get("ts")
                else:
                    actual_card_ts = None
                if not isinstance(actual_card_ts, str):
                    actual_card_ts = None
            except Exception as e:
                log.error("Failed to post purchase request card to channel %s: %s", channel, e)
                slack_io.alert_admins(
                    client,
                    text_rules.format_card_failure_alert(
                        step="post the approval card",
                        channel=channel,
                        thread_ts=thread_ts,
                        file_name=file_name,
                        error=str(e),
                    ),
                )

        # Write to request log (requests.json) per Ticket 76 / ADR 0011
        now_iso = datetime.now().isoformat(timespec="seconds")
        buyer_set_iso = now_iso if assignee_id else None
        existing_id = None
        try:
            # ADR 0013 decision 7: the card's entry was created at posting. Match by card;
            # fall back to the thread only for an entry that was never posted, so approving
            # one card of a batch never overwrites another card's entry.
            if actual_card_ts:
                existing_id = store.find_id_by_card(channel, actual_card_ts)
            if not existing_id:
                thread_id = store.find_id_by_thread(channel, thread_ts)
                thread_entry = store.get(thread_id) if thread_id else None
                if thread_entry is not None and not thread_entry.get("posted_at"):
                    existing_id = thread_id
        except Exception as read_err:
            log.warning("Could not check existing entry in request log: %s", read_err)

        if existing_id:
            # Keep the "Posted by" line the entry started with; add only the card's lines it lacks.
            prior = (store.get(existing_id) or {}).get("history") or []
            merged_history = list(prior) + [h for h in hist if h not in prior]
            _request_log(
                client,
                store.update,
                existing_id,
                channel=channel,
                thread_ts=thread_ts,
                card_ts=actual_card_ts,
                requester=requester,
                requester_id=notify_target,
                buyer=assignee_name,
                buyer_id=assignee_id,
                rows=[row] if row is not None else [],
                history=merged_history,
                approved_at=now_iso,
                buyer_set_at=buyer_set_iso,
                cancelled=False,
                last_nudged=None,
            )
        else:
            _request_log(
                client,
                store.create,
                channel=channel,
                thread_ts=thread_ts,
                card_ts=actual_card_ts,
                requester=requester or "Requester",
                requester_id=notify_target,
                buyer=assignee_name,
                buyer_id=assignee_id,
                rows=[row] if row is not None else [],
                history=list(hist),
                approved_at=now_iso,
                buyer_set_at=buyer_set_iso,
                cancelled=False,
                last_nudged=None,
            )

        if assignee_id and assignee_name:
            route = interview.get_request_route(parsed, bool(pdf_bytes))
            row_info = log_writer.get_row_info(row) if row else {}
            draft_data = dict(parsed)
            for k, v in row_info.items():
                if k not in draft_data or not draft_data[k]:
                    draft_data[k] = v
            email_draft = text_rules.generate_email_draft(draft_data, assignee_name, bom_filename=bom_fname)
            item_desc = draft_data.get("item_description") or "supplies"
            dm_ref = _send_assignee_dm(
                client=client,
                assignee_id=assignee_id,
                assignee_name=assignee_name,
                email_draft=email_draft,
                item_desc=item_desc,
                row=row,
                bom_path=saved_bom_path,
                bom_fname=bom_fname,
                quote_paths=saved_quote_paths,
                epif_path=saved_path,
                epif_fname=saved_name,
                route=route,
                parsed=parsed,
                thread_channel=channel,
                thread_ts=thread_ts,
                card_ts=actual_card_ts,
                request=req_payload,
                state="approved",
            )
            if dm_ref and actual_card_ts:
                dm_chan, dm_ts = dm_ref
                req_payload["dm_channel"] = dm_chan
                req_payload["dm_ts"] = dm_ts
                updated_blks = blocks.build_request_blocks("approved", req_payload, history=hist, items=items)
                try:
                    client.chat_update(
                        channel=channel,
                        ts=actual_card_ts,
                        text="🛒 Purchase Request (Approved)",
                        blocks=updated_blks,
                        metadata={
                            "event_type": "purchase_request",
                            "event_payload": req_payload,
                        },
                    )
                except Exception as e:
                    log.error("Failed to update thread card with DM reference: %s", e)

    def on_failure(error):
        if isinstance(error, log_writer.StorageLocationError):
            say(
                text=text_rules.storage_problem_message(
                    error.setting, error.path, error.reason
                ),
                thread_ts=thread_ts,
            )
            return
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
    attachments: list[dict] | None = None,
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
            if attachments is None and card_payload.get("attachments"):
                attachments = card_payload.get("attachments")
    elif posted_payload:
        if items is None and "items" in posted_payload:
            items = posted_payload.get("items")
            shipping = float(posted_payload.get("shipping") or 0.0)
        if attachments is None and posted_payload.get("attachments"):
            attachments = posted_payload.get("attachments")

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
                if card_pl and attachments is None and card_pl.get("attachments"):
                    attachments = card_pl.get("attachments")

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
            attachments=attachments,
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
            attachments=attachments,
        )
        return

    # Modal Purchase Request in Thread Path via Slack Metadata (for keyword approvals)
    parsed_req, modal_req_name, modal_user_id, is_pending = slack_io.find_request_metadata_in_thread(client, channel, thread_ts)
    if parsed_req:
        if items is None and "items" in parsed_req:
            items = parsed_req.get("items")
            shipping = float(parsed_req.get("shipping") or 0.0)
        if attachments is None and parsed_req.get("attachments"):
            attachments = parsed_req.get("attachments")

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
            attachments=attachments,
        )
        return


    # Bare thread approval (Ticket 40)
    # If no PDF, no posted payload, and no modal metadata is found, it's a bare thread.
    log.info("No PDF or purchase request found in thread %s, treating as bare thread approval", thread_ts)

    requester_id = slack_io.get_thread_parent_author(client, channel, thread_ts)
    requester_name = slack_io.resolve_requester(client, requester_id) if requester_id else None
    display_requester = f"<@{requester_id}>" if requester_id else "requester"

    # 1. Post exactly one thread reply
    reply_text = (
        f"✅ Approved by {approver}. No EPIF in this thread, so I'm treating this as a *Workday order*. "
        f"{display_requester}, please fill in the details so it can be logged. "
        f"If this vendor isn't on Workday, press *This needs an EPIF* instead."
    )
    say(text=reply_text, thread_ts=thread_ts)

    # 2. Post a waiting_for_details card
    req_data = {
        "user_id": requester_id,
        "requester": requester_name,
        "approver": approver,
        "assignee_id": assignee_id,
        "assignee": assignee_name,
        "thread_ts": thread_ts,
        "state": "waiting_for_details",
    }

    card_blocks = blocks.build_request_blocks(
        state="waiting_for_details",
        request=req_data,
        history=[],
        requester=requester_name,
    )

    client.chat_postMessage(
        channel=channel,
        text="Approved — waiting for details",
        blocks=card_blocks,
        thread_ts=thread_ts,
        metadata={
            "event_type": "purchase_request",
            "event_payload": req_data,
        },
    )
    # No row is written (absence asserted)



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
            slack_io.alert_admins(
                client,
                text_rules.format_card_failure_alert(
                    step="parse the dropped EPIF",
                    channel=channel,
                    thread_ts=thread_ts,
                    file_name=file_name,
                    error=str(error),
                ),
            )
            log.info("drop exit: parse failed")
        else:
            log.debug("Non-EPIF PDF %s failed form parsing; ignoring: %s", file_name, error)
            log.info("drop exit: parse failed (not an EPIF name, ignored)")
        return
    except Exception as e:
        log.error("Unexpected error parsing dropped PDF %s: %s", file_name, e)
        if "epif" in file_name.lower():
            slack_io.alert_admins(
                client,
                text_rules.format_card_failure_alert(
                    step="parse the dropped EPIF",
                    channel=channel,
                    thread_ts=thread_ts,
                    file_name=file_name,
                    error=str(e),
                ),
            )
        log.info("drop exit: unexpected error")
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

    # Supersede any posted card in this thread from the same requester and vendor
    # before posting the new card (ADR 0006 decision 9).  Approved or later cards
    # are never touched — a real purchase must not be hidden by a stray upload.
    now_str = datetime.now().strftime("%m/%d/%y %H:%M")
    vendor_for_scan = parsed.get("vendor", "").strip().lower()
    stale_cards = slack_io.find_posted_cards_in_thread(
        client, channel, thread_ts, user_id=user_id, vendor=vendor_for_scan,
    )
    for stale_ts, stale_req, stale_hist in stale_cards:
        new_hist = list(stale_hist) + [f"Superseded by a newer EPIF on {now_str}"]
        superseded_blks = blocks.build_request_blocks("superseded", stale_req, history=new_hist)
        try:
            client.chat_update(
                channel=channel,
                ts=stale_ts,
                text="Purchase Request (Superseded)",
                blocks=superseded_blks,
            )
            log.info("Superseded posted card at %s in %s (thread: %s)", stale_ts, channel, thread_ts)
            _flag_card_entry(client, channel, stale_ts, new_hist[-1], superseded=True)
        except Exception as e:
            log.warning("Failed to supersede card at %s: %s", stale_ts, e)

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
        post_resp = client.chat_postMessage(
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
        posted_ts = post_resp.get("ts") if hasattr(post_resp, "get") else None
        _log_posted_card(
            client, channel=channel, thread_ts=thread_ts,
            card_ts=posted_ts if isinstance(posted_ts, str) else None,
            requester=requester or f"<@{user_id}>", requester_id=user_id,
        )
        log.info("drop exit: card posted")
    except Exception as e:
        log.error("Failed to post purchase request card to channel %s: %s", channel, e)
        slack_io.alert_admins(
            client,
            text_rules.format_card_failure_alert(
                step="post the approval card",
                channel=channel,
                thread_ts=thread_ts,
                file_name=file_name,
                error=str(e),
            ),
        )
        log.info("drop exit: card post failed")


def handle_assign(
    client, say, channel: str, thread_ts: str, user_id: str, event_ts: str,
    target_user_id: str | None = None,
    req_data: dict | None = None,
    msg_ts: str | None = None,
    history: list | None = None,
    current_state: str | None = None,
    deny=None,
):
    """Assign or reassign a purchase request to a buyer.

    WHY THIS EXISTS:
    ----------------
    ADR 0004 & ADR 0005 & ADR 0011: Assignment replaces claim. Charlie names the responsible buyer when
    approving (via @-mention or the buyer picker on the posted card), or any buyer can move an
    approved order.
    Permission per ADR 0011 decision 1 (amends ADR 0004 decision 3):
    - Any buyer, approver, or admin may assign or change the assignee before Processed,
      regardless of whether the request is already assigned.
    - When current_state is processed, confirmed or delivered, assignment is refused in-thread
      with "Already Processed by ...".
    - On reassignment, the old buyer receives a DM notifying them that the request was moved.
    - `deny`: optional callable(text) for private refusals (picker path uses
      `lambda t: slack_io.deny(respond, t)`); keyword path falls back to say().
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

    # Stage cutoff (ADR 0011 decision 1 / Ticket 73): once processed, confirmed, or delivered,
    # the buyer cannot change. Refuse publicly in-thread before permission or target checks.
    if current_state in ("processed", "confirmed", "delivered"):
        processed_line = "Processed"
        for entry in history:
            if isinstance(entry, str) and entry.startswith("Processed by"):
                processed_line = entry
        say(text=f"🔒 Already {processed_line} — the buyer can't change after this point.", thread_ts=thread_ts)
        return False

    current_assignee = req_data.get("assignee_id")

    # If target_user_id is None, check if caller is assigning themselves
    if not target_user_id:
        if roster.is_buyer(user_id):
            target_user_id = user_id
        else:
            say(text="⚠️ Please specify a buyer to assign this order to, e.g. `@Purchasing assign @buyer`.", thread_ts=thread_ts)
            return False

    # Permission check (ADR 0011 decision 1): any buyer, approver or admin, whether the
    # request is assigned or not.
    if not (roster.is_buyer(user_id) or admin.is_approved_reviewer(user_id) or admin.is_admin_user(user_id)):
        log.warning("Unauthorized user %s attempted to assign/reassign request", user_id)
        _deny = deny if deny is not None else (lambda t: say(text=t, thread_ts=thread_ts))
        _deny("🔒 Only buyers, approvers or admins can assign purchase requests.")
        return False

    # Same-buyer no-op (ADR 0011 step 4): selecting the current assignee changes nothing
    if target_user_id == current_assignee:
        return True

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

    draft_data = dict(req_data.get("parsed", req_data))
    route = interview.get_request_route(req_data)
    action_text = "to place in Workday." if route == "workday" else "to email to purchasing."

    say(text=f"👤 Assigned to <@{target_user_id}> ({target_name}) {action_text}", thread_ts=thread_ts)

    # Email draft DM (with optional BOM) to assignee — single implementation via _send_assignee_dm
    row = slack_io.find_row_in_thread(client, channel, thread_ts)
    row_info = log_writer.get_row_info(row) if row else {}
    for k, v in row_info.items():
        if k not in draft_data or not draft_data[k]:
            draft_data[k] = v
    bom_fname = req_data.get("bom_file")
    bom_path = os.path.join(config.BOMS_DIR, bom_fname) if bom_fname else None
    quote_paths: list[str] = []
    if req_data.get("quote_count") and row:
        quote_vendor = draft_data.get("vendor") or "Vendor"
        quote_paths = [
            os.path.join(config.QUOTES_DIR, bom.quote_filename(row, quote_vendor, k))
            for k in range(1, int(req_data["quote_count"]) + 1)
        ]
    email_draft = text_rules.generate_email_draft(draft_data, target_name, bom_filename=bom_fname)
    item_desc = draft_data.get("item_description") or "supplies"
    epif_fname = req_data.get("epif_file")
    epif_path = os.path.join(config.EPIFS_DIR, epif_fname) if epif_fname else None

    # Retire the old buyer's DM card before new DM card replaces it (Ticket 69)
    if current_assignee and req_data.get("dm_channel") and req_data.get("dm_ts"):
        sync_dm_card(
            client=client,
            request=req_data,
            state="reassigned",
            channel=channel,
            thread_ts=thread_ts,
            card_ts=msg_ts or "",
            history=history,
            note=f"Reassigned to {target_name}",
        )

    # Notify old buyer by DM that the request was moved (Ticket 73 / ADR 0011)
    if current_assignee:
        req = req_data if req_data is not None else {}
        parsed_raw = req.get("parsed")
        parsed_dict: dict = {}
        if isinstance(parsed_raw, dict):
            parsed_dict = parsed_raw
        item_name = parsed_dict.get("item_description") or req.get("item_description") or "Item"
        try:
            client.chat_postMessage(
                channel=current_assignee,
                text=f"↪️ {item_name} was moved to {target_name} by {actor_name}. You don't need to do anything on it.",
            )
        except Exception as e:
            log.warning("Could not send reassignment notification DM to old buyer %s: %s", current_assignee, e)

    dm_ref = _send_assignee_dm(
        client=client,
        assignee_id=target_user_id,
        assignee_name=target_name,
        email_draft=email_draft,
        item_desc=item_desc,
        row=row,
        bom_path=bom_path,
        bom_fname=bom_fname,
        quote_paths=quote_paths,
        epif_path=epif_path,
        epif_fname=epif_fname,
        route=route,
        parsed=draft_data,
        thread_channel=channel,
        thread_ts=thread_ts,
        card_ts=msg_ts,
        request=req_data,
        state=current_state,
    )
    if dm_ref and msg_ts:
        dm_chan, dm_ts = dm_ref
        req_data["dm_channel"] = dm_chan
        req_data["dm_ts"] = dm_ts
        card_blocks = blocks.build_request_blocks(current_state, req_data, history=history)
        try:
            client.chat_update(
                channel=channel,
                ts=msg_ts,
                text=f"🛒 Purchase Request ({current_state.capitalize()})",
                blocks=card_blocks,
                metadata={
                    "event_type": "purchase_request",
                    "event_payload": req_data,
                },
            )
        except Exception as e:
            log.error("Failed to update message on assign with DM reference: %s", e)

    # Update request log (requests.json) per Ticket 76 / ADR 0011
    if current_state != "posted":
        req_id = None
        try:
            req_id = store.find_id_by_thread(channel, thread_ts)
        except Exception as read_err:
            log.warning("Could not find request in log: %s", read_err)

        if req_id:
            now_iso = datetime.now().isoformat(timespec="seconds")
            _request_log(
                client,
                store.update,
                req_id,
                buyer=target_name,
                buyer_id=target_user_id,
                buyer_set_at=now_iso,
            )
            if history:
                _request_log(
                    client,
                    store.append_history,
                    req_id,
                    history[-1],
                )

    return True


def handle_processed(
    client, say, channel: str, thread_ts: str, user_id: str, event_ts: str, text: str,
    card_ts: str | None = None, req_data: dict | None = None, history: list | None = None,
):
    """Mark an order as Processed in Workday (Col U) and optionally update Total Price (Col H)."""
    user_name = slack_io.resolve_requester(client, user_id) or "Buyer"
    row = text_rules.extract_row_from_text(text)
    if not row and req_data and req_data.get("row"):
        try:
            row = int(req_data["row"])
        except (ValueError, TypeError):
            row = None
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

        if row and "row" not in target_req:
            target_req["row"] = row

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

        sync_dm_card(
            client=client,
            request=target_req,
            state="processed",
            channel=channel,
            thread_ts=thread_ts,
            card_ts=target_card_ts or "",
            history=target_hist,
        )

        # Update request log (requests.json) per Ticket 77 / ADR 0011
        req_id = _request_log(client, store.find_id_by_thread, channel, thread_ts)
        if req_id and target_hist:
            _request_log(client, store.append_history, req_id, target_hist[-1])

    def on_failure(error):
        if isinstance(error, log_writer.StorageLocationError):
            say(
                text=text_rules.storage_problem_message(
                    error.setting, error.path, error.reason
                ),
                thread_ts=thread_ts,
            )
            return
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
    if not row and req_data and req_data.get("row"):
        try:
            row = int(req_data["row"])
        except (ValueError, TypeError):
            row = None
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
                except log_writer.StorageLocationError:
                    raise
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

        if row and "row" not in target_req:
            target_req["row"] = row

        now_str = datetime.now().strftime("%m/%d/%y %H:%M")
        actor_name = requester_name or slack_io.resolve_requester(client, user_id) or f"<@{user_id}>"
        target_hist.append(f"Confirmed by {actor_name} on {now_str}")

        if target_card_ts:
            next_blocks = blocks.build_request_blocks(
                "confirmed", target_req, history=target_hist, thread_channel=channel, card_ts=target_card_ts
            )
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

        sync_dm_card(
            client=client,
            request=target_req,
            state="confirmed",
            channel=channel,
            thread_ts=thread_ts,
            card_ts=target_card_ts or "",
            history=target_hist,
        )

        # Update request log (requests.json) per Ticket 77 / ADR 0011
        req_id = _request_log(client, store.find_id_by_thread, channel, thread_ts)
        if req_id and target_hist:
            _request_log(client, store.append_history, req_id, target_hist[-1])

    def on_failure(error):
        if isinstance(error, log_writer.StorageLocationError):
            say(
                text=text_rules.storage_problem_message(
                    error.setting, error.path, error.reason
                ),
                thread_ts=thread_ts,
            )
            return
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


def handle_set_expected_delivery(client, channel: str, thread_ts: str, card_ts: str, user_id: str, chosen_date) -> bool:
    """Record an expected delivery date on a Confirmed card (Ticket 91 / ADR 0013 decision 5).

    WHY THIS EXISTS:
    ----------------
    The date has to land in four places that must never disagree: the thread card (its button
    value is the store), the buyer's DM card, the request log (so ticket 92 can pause the
    delivered nudge until then), and a thread line. The form handler in app.py only validates and
    delegates; the card is re-read here so a stale form cannot overwrite newer card state.
    The date is optional and never touches the workbook. Returns False when the card is gone
    (admins are alerted); a request-log failure alerts but never blocks the card update.
    """
    card_info = slack_io.get_card_by_ts(client, channel=channel, thread_ts=thread_ts, card_ts=card_ts)
    if card_info is None:
        log.warning("Card %s not found in thread %s for expected delivery", card_ts, thread_ts)
        slack_io.alert_admins(
            client,
            text_rules.format_card_failure_alert(
                "set the expected delivery date", channel, thread_ts, None, "card not found"
            ),
        )
        return False
    req_data, history, _state = card_info
    req_data = dict(req_data)
    history = list(history)
    short = blocks.format_short_date(chosen_date.isoformat())
    actor = slack_io.resolve_requester(client, user_id) or f"<@{user_id}>"
    history.append(f"Expected delivery set to {short} by {actor} on {datetime.now().strftime('%m/%d/%y %H:%M')}")
    req_data["expected_delivery"] = chosen_date.isoformat()

    client.chat_update(
        channel=channel,
        ts=card_ts,
        text="🛒 Purchase Request (Confirmed)",
        blocks=blocks.build_request_blocks(
            "confirmed", req_data, history=history, thread_channel=channel, card_ts=card_ts
        ),
    )
    sync_dm_card(
        client=client,
        request=req_data,
        state="confirmed",
        channel=channel,
        thread_ts=thread_ts,
        card_ts=card_ts,
        history=history,
    )
    req_id = _request_log(client, store.find_id_by_card, channel, card_ts) or _request_log(
        client, store.find_id_by_thread, channel, thread_ts
    )
    if req_id:
        _request_log(client, store.update, req_id, expected_delivery=chosen_date.isoformat())
        _request_log(client, store.append_history, req_id, history[-1])
    client.chat_postMessage(
        channel=channel,
        thread_ts=thread_ts,
        text=f"📦 Expected delivery {short} — I'll check back then.",
    )
    log.info("Expected delivery for card %s set to %s by %s", card_ts, chosen_date.isoformat(), user_id)
    return True


def update_nudge_cards(
    client, cards, state: str, mentions: str, item: str, n, thread_channel: str,
    thread_ts: str, card_ts: str, note: str | None = None,
) -> None:
    """Re-render each delivered-nudge card (channel, ts) in `cards` in `state` (Ticket 90).

    The one place nudge cards are edited: retiring an old card (`replaced`), closing a stale
    click (`closed`) and finishing after Delivered (`delivered`) all come through here, so
    src/app.py never calls chat_update. A failed edit is logged and does not stop the rest.
    """
    rendered = blocks.build_nudge_card_blocks(
        state, mentions, item, n, thread_channel, thread_ts, card_ts, note=note)
    for card_channel, card_msg_ts in cards:
        try:
            client.chat_update(channel=card_channel, ts=card_msg_ts, text="⏰ Delivery reminder", blocks=rendered)
        except Exception as err:
            log.warning("Could not update nudge card (%s, %s): %s", card_channel, card_msg_ts, err)


def handle_delivery(
    client, say, channel: str, thread_ts: str, user_id: str, event_ts: str, text: str,
    card_ts: str | None = None, req_data: dict | None = None, history: list | None = None,
):
    """Mark an order as Delivered in Purchasing-Log.xlsx (Col W) and record Received By (Col X)."""
    requester_name = slack_io.resolve_requester(client, user_id) or "Lab Member"
    row = text_rules.extract_row_from_text(text)
    if not row and req_data and req_data.get("row"):
        try:
            row = int(req_data["row"])
        except (ValueError, TypeError):
            row = None
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

        if row and "row" not in target_req:
            target_req["row"] = row

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

        sync_dm_card(
            client=client,
            request=target_req,
            state="delivered",
            channel=channel,
            thread_ts=thread_ts,
            card_ts=target_card_ts or "",
            history=target_hist,
        )

        # Update request log (requests.json) per Ticket 77 / ADR 0011
        req_id = _request_log(client, store.find_id_by_thread, channel, thread_ts)
        if req_id and target_hist:
            _request_log(client, store.append_history, req_id, target_hist[-1])

    def on_failure(error):
        if isinstance(error, log_writer.StorageLocationError):
            say(
                text=text_rules.storage_problem_message(
                    error.setting, error.path, error.reason
                ),
                thread_ts=thread_ts,
            )
            return
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
    storage_error = None
    for f in files:
        fname = f.get("name", "Vendor_Quote.pdf")
        try:
            content = slack_io.download_file(f)
            saved = log_writer.save_quote(content, fname)
            saved_paths.append(saved)
            log.info("Saved quote file '%s' to %s", fname, saved)
        except log_writer.StorageLocationError as e:
            storage_error = e
            break
        except Exception as e:
            log.warning("Could not download/save quote %s: %s", fname, e)

    if storage_error:
        say(
            text=text_rules.storage_problem_message(
                storage_error.setting, storage_error.path, storage_error.reason
            ),
            thread_ts=thread_ts,
        )
        return

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


def _finalize_bare_thread_epif(ack, client, bare: dict, parsed: dict,
                               requester: str | None, user_id: str | None, stage2: dict):
    """Finish a bare-thread "This needs an EPIF" interview against the existing card.

    WHY THIS EXISTS:
    ----------------
    Approval already happened (ADR 0007 decision 5: approval is never asked twice), so
    this must not post a new posted card with an Approve button. It hands the finished
    request to finalize_purchase_request (invariant 1) with the waiting card's ts; that
    one queued task appends the row, generates and archives the EPIF, and only then turns
    the card into `approved`. If the task fails the row is blanked and the card is left in
    `waiting_for_details` so the buyer can try again.
    """
    channel = bare["channel"]
    thread_ts = bare["thread_ts"]
    card_ts = bare["card_ts"]

    card_payload = slack_io.get_card_payload(client, channel, thread_ts, card_ts)
    if not card_payload or card_payload.get("state") != "waiting_for_details":
        ack(response_action="errors", errors={"block_item_description": "This request is no longer waiting for details."})
        return

    ack()

    items = stage2.get("items")
    shipping = float(stage2.get("shipping") or 0.0)
    line_items_text = stage2.get("line_items") or ""
    if items is None and line_items_text.strip():
        items, shipping, _ = bom.parse_line_items(line_items_text)

    parsed = dict(parsed)
    parsed["route"] = "epif"

    def say(text, thread_ts=thread_ts, **kw):
        client.chat_postMessage(channel=channel, text=text, thread_ts=thread_ts, **kw)

    finalize_purchase_request(
        client=client,
        say=say,
        channel=channel,
        thread_ts=thread_ts,
        event_ts=card_ts,
        parsed=parsed,
        requester=requester,
        notify_target=user_id,
        is_pending_name=False,
        assignee_id=bare.get("assignee_id"),
        assignee_name=bare.get("assignee_name"),
        approver=bare.get("approver"),
        card_ts=card_ts,
        items=items,
        shipping=shipping,
    )


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

    bare = meta.get("bare_thread")
    if bare:
        _finalize_bare_thread_epif(ack, client, bare, parsed, requester, user_id, stage2)
        return

    ack()

    # Determine posting channel (Ticket 15: reads from config, no silent fallback)
    post_channel = config.PURCHASING_CHANNEL
    if not post_channel:
        log.error("PURCHASING_CHANNEL is not configured; refusing to post purchase request.")
        return
    display_name = f"{requester} (pending name confirmation)" if is_pending_name else (requester or f"<@{user_id}>")

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
        "source": "modal",
    }
    if items:
        req_payload["items"] = items
        req_payload["shipping"] = float(shipping or 0.0)
    attachments = stage2.get("attachments")
    if attachments:
        req_payload["attachments"] = attachments

    req_blocks = blocks.build_request_blocks("posted", req_payload, items=items, attachments=attachments)

    link_line = f"\n• *Link:* {parsed['link']}" if parsed.get("link") else ""
    items_line = f"\n📋 {len(items)} line items (BOM attached in thread)" if (items and bom.needs_bom(items)) else ""
    quote_count = sum(1 for a in (attachments or []) if a.get("role") == "quote")
    quotes_line = f"\n📎 Quotes: {quote_count}" if quote_count > 0 else ""
    bom_names = [a.get("name") or "BOM" for a in (attachments or []) if a.get("role") == "bom"]
    bom_line = "".join(f"\n📎 BOM attached: {n}" for n in bom_names)
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
        f"{bom_line}"
        f"{quotes_line}\n\n"
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

    _log_posted_card(
        client, channel=post_channel, thread_ts=card_ts, card_ts=card_ts,
        requester=requester or "Requester", requester_id=user_id,
    )

    if attachments:
        post_attachments_to_thread(
            client=client,
            channel=post_channel,
            thread_ts=card_ts,
            attachments=attachments,
            requester_id=user_id,
        )

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

# States where cancel is refused — the request has already gone to purchasing (ADR 0003 decision 5).
_CANCEL_REFUSED_STATES = {"processed", "confirmed", "delivered"}


def handle_decline(client, channel: str, msg_ts: str, user_id: str, req_data: dict, history: list):
    """Decline a posted purchase request.

    WHY THIS EXISTS:
        The card's request-log entry is flagged declined=True (ADR 0013 decision 7).
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
    _flag_card_entry(client, channel, msg_ts, history[-1], declined=True)

def _move_epif_to_cancelled(epif_fname: str) -> None:
    """Move the named EPIF file from EPIFS_DIR into EPIFS_DIR/Cancelled/.

    WHY THIS EXISTS:
        Cancel must move the archived EPIF out of the live folder (ticket 39).
    """
    src_path = os.path.join(config.EPIFS_DIR, epif_fname)
    if not os.path.exists(src_path):
        log.warning(
            "Cancel: EPIF %s not found at %s; cancellation continues without moving it",
            epif_fname,
            src_path,
        )
        return
    cancelled_dir = os.path.join(config.EPIFS_DIR, "Cancelled")
    os.makedirs(cancelled_dir, exist_ok=True)
    dst_path = os.path.join(cancelled_dir, epif_fname)
    shutil.move(src_path, dst_path)
    log.info("Moved EPIF %s to Cancelled/ on cancel", epif_fname)


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


def _move_quotes_to_cancelled(names: list[str]) -> None:
    """Move the named archived quotes from QUOTES_DIR into QUOTES_DIR/Cancelled/.

    WHY THIS EXISTS:
        ADR 0012 decision 5: the quotes follow the BOM out of the live folder on cancel,
        so a recycled row number cannot collide with stale quotes. Same contract as
        _move_bom_to_cancelled: a missing file is a warning and is skipped, so one quote
        that never saved cannot stop the cancel or the other quotes (ticket 84).
    """
    for name in names:
        src_path = os.path.join(config.QUOTES_DIR, name)
        if not os.path.exists(src_path):
            log.warning(
                "Cancel: quote %s not found at %s; cancellation continues without moving it",
                name,
                src_path,
            )
            continue
        cancelled_dir = os.path.join(config.QUOTES_DIR, "Cancelled")
        os.makedirs(cancelled_dir, exist_ok=True)
        shutil.move(src_path, os.path.join(cancelled_dir, name))
        log.info("Moved quote %s to Cancelled/ on cancel", name)


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
        Archived quotes move the same way into QUOTES_DIR/Cancelled/ (ADR 0012
        decision 5, ticket 84); their names are derived from the row and vendor with
        bom.quote_filename because the card carries only a quote_count.
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
    epif_fname = req_data.get("epif_file")
    quote_names: list[str] = []
    quote_count = req_data.get("quote_count")
    if rows and isinstance(quote_count, int) and quote_count > 0:
        quote_vendor = req_data.get("parsed", req_data).get("vendor") or "Vendor"
        quote_names = [bom.quote_filename(rows[0], quote_vendor, k) for k in range(1, quote_count + 1)]

    if rows:
        def write_action():
            for row in rows:
                log_writer.blank_row(row)
            if bom_fname:
                _move_bom_to_cancelled(bom_fname)
            if quote_names:
                _move_quotes_to_cancelled(quote_names)
            if epif_fname:
                _move_epif_to_cancelled(epif_fname)
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
        if epif_fname:
            _move_epif_to_cancelled(epif_fname)
        if state == "waiting_for_details":
            log.info("Cancel: waiting_for_details request cancelled with no row written.")
        else:
            log.warning("Cancel: no logged rows found in thread %s; nothing blanked", thread_ts)

    if state == "waiting_for_details":
        say(text="🚫 Purchase request cancelled.", thread_ts=thread_ts)
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

    sync_dm_card(
        client=client,
        request=req_data,
        state="cancelled",
        channel=channel,
        thread_ts=thread_ts,
        card_ts=msg_ts,
        history=history,
    )

    # Update request log (requests.json) per Ticket 77 / ADR 0011
    req_id = _request_log(client, store.find_id_by_thread, channel, thread_ts)
    if req_id:
        if history:
            _request_log(client, store.append_history, req_id, history[-1])
        _request_log(client, store.update, req_id, cancelled=True)

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
    xlsx_bytes = bom.build_bom_workbook(parsed or {}, items)
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


def post_attachments_to_thread(
    client,
    channel: str,
    thread_ts: str,
    attachments: list[dict],
    requester_id: str,
) -> list[str]:
    """Download submitted attachments from Slack and re-post them into the request's thread.

    WHY THIS EXISTS:
    ----------------
    Ticket 81 / ADR 0012 Decision 5:
    Re-posts quotes into the card's thread so the approver sees them before approving.
    If a file fails to fetch, alerts both the thread and the requester via DM (spec user story 31),
    without blocking card posting. Returns a list of failed filenames.
    """
    failed: list[str] = []
    if not attachments:
        return failed

    for a in attachments:
        fname = a.get("name") or "attachment"
        try:
            file_id = a.get("id")
            info = client.files_info(file=file_id)
            file_obj = info.get("file", info) if isinstance(info, dict) else info["file"]
            content = slack_io.download_file(file_obj)

            if hasattr(client, "files_upload_v2"):
                client.files_upload_v2(
                    channel=channel,
                    thread_ts=thread_ts,
                    content=content,
                    filename=fname,
                    title=fname,
                )
            else:
                client.files_upload(
                    channels=channel,
                    thread_ts=thread_ts,
                    content=content,
                    filename=fname,
                    title=fname,
                )
            log.info("Uploaded attachment %s to thread %s in %s", fname, thread_ts, channel)
        except Exception as e:
            log.warning("Couldn't attach '%s' (id=%s) to thread %s: %s", fname, a.get("id"), thread_ts, e)
            msg = f"⚠️ Couldn't attach `{fname}` — drop it in the thread with `@Purchasing quote`."
            try:
                client.chat_postMessage(channel=channel, thread_ts=thread_ts, text=msg)
            except Exception as e_post:
                log.warning("Failed to post attachment failure warning to thread %s: %s", thread_ts, e_post)
            try:
                slack_io.tell(client, requester_id, msg)
            except Exception as e_tell:
                log.warning("Failed to DM attachment failure warning to %s: %s", requester_id, e_tell)
            failed.append(fname)

    return failed


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
    items: list[dict] | None,
    shipping: float,
    user_id: str,
    attachments: list[dict] | None = None,
) -> bool:
    """Save updated line items to card metadata, update card blocks, post edit notice, and upload draft BOM.

    WHY THIS EXISTS:
    ----------------
    Single handler for updating line items on a posted card (invariant 1).
    Called by both the EPIF path (Ticket 27), the interview modal path (Ticket 28),
    and Edit (Ticket 32).
    ADR 0006 decision 5: items are stored in message metadata, never button value.
    Draft BOM is uploaded to thread via files_upload_v2 and NEVER saved to BOMS_DIR (only approval archives).

    Ticket 85 / ADR 0012: Add items may also carry an attached BOM and quotes. They are
    appended to the card payload's `attachments` (a new BOM replaces an earlier one), written
    in the same chat_update as the items and re-posted to the thread; ticket 83 archives them
    at approval. items=None means the paste box was blank: the card's existing items are left
    exactly as they are and no draft BOM is rebuilt.
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
    items_given = items is not None
    if items_given:
        new_payload["items"] = items
        new_payload["shipping"] = float(shipping or 0.0)
    else:
        items = list(card_payload.get("items") or [])
        shipping = float(card_payload.get("shipping") or 0.0)
    if "source" not in new_payload:
        new_payload["source"] = "epif"

    change_fragments = bom.describe_changes(card_payload, new_payload) if items_given else []

    new_boms = [a for a in (attachments or []) if a.get("role") == "bom"]
    new_quotes = [a for a in (attachments or []) if a.get("role") == "quote"]
    if attachments:
        kept = [
            a for a in (card_payload.get("attachments") or [])
            if not (new_boms and a.get("role") == "bom")
        ]
        new_payload["attachments"] = kept + list(attachments)
    for a in new_boms:
        change_fragments.append(f"attached BOM {a.get('name') or 'BOM'}")
    if new_quotes:
        change_fragments.append(f"added {len(new_quotes)} quote(s)")
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

    if attachments:
        post_attachments_to_thread(
            client=client,
            channel=channel,
            thread_ts=thread_ts,
            attachments=attachments,
            requester_id=user_id,
        )

    if items is not None and items_given:
        upload_draft_bom(
            client=client,
            channel=channel,
            thread_ts=thread_ts,
            parsed=new_payload.get("parsed") or {},
            items=items,
            shipping=shipping,
        )

    return True


def handle_request_edit(
    client,
    channel: str,
    thread_ts: str,
    card_ts: str,
    stage2: dict,
    stage3: dict | None,
    items: list,
    shipping: float,
    user_id: str,
    card_payload: dict,
    meta: dict,
) -> None:
    """Update a modal-born posted card with edited values (Ticket 32, ADR 0006 decision 8).

    WHY THIS EXISTS:
    ----------------
    Called after ack() once the submit handler has validated all fields and confirmed
    the card is still in 'posted' state. This function:
    1. Rebuilds the parsed request from the submitted stage2/stage3 values.
    2. Calls bom.describe_changes to find what changed. No changes -> returns
       immediately; no thread post, no history line.
    3. Writes the updated blocks + metadata to the card via chat_update.
    4. Posts one thread line naming every changed field, appended to history.
    5. Re-posts the draft BOM when line items changed and needs_bom is True.

    Vendor and route come from the original card (via meta), not from the edit form,
    because vendor is not editable: to change vendor, Decline and resubmit.
    """
    stage1 = {
        "vendor_choice": meta.get("vendor_choice", ""),
        "vendor_custom": meta.get("vendor_custom", ""),
        "route": meta.get("route", "workday"),
    }

    new_parsed = interview.build_parsed_from_stages(
        stage1, stage2, stage3 if stage3 and any(stage3.values()) else None
    )

    # Serialize date for metadata storage
    new_parsed_stored = dict(new_parsed)
    if new_parsed_stored.get("date_of_purchase") and not isinstance(new_parsed_stored["date_of_purchase"], str):
        new_parsed_stored["date_of_purchase"] = new_parsed_stored["date_of_purchase"].isoformat()

    old_parsed = card_payload.get("parsed") or {}
    old_items = card_payload.get("items") or []
    old_shipping = float(card_payload.get("shipping") or 0.0)

    old_compare = {**old_parsed, "items": old_items, "shipping": old_shipping}
    new_compare = {**new_parsed_stored, "items": items, "shipping": float(shipping or 0.0)}

    fragments = bom.describe_changes(old_compare, new_compare)
    if not fragments:
        return  # Nothing changed — no thread post, no history update

    user_name = slack_io.resolve_requester(client, user_id) or f"<@{user_id}>"
    edit_line = f"✏️ Edited by {user_name}: {'; '.join(fragments)}"

    history = list(card_payload.get("history") or [])
    history.append(edit_line)

    new_payload = dict(card_payload)
    new_payload["parsed"] = new_parsed_stored
    new_payload["history"] = history
    new_payload["items"] = items
    new_payload["shipping"] = float(shipping or 0.0)

    new_blocks = blocks.build_request_blocks("posted", new_payload, history=history, items=items)

    try:
        client.chat_update(
            channel=channel,
            ts=card_ts,
            text="🛒 Purchase Request (Posted)",
            blocks=new_blocks,
            metadata={
                "event_type": "purchase_request",
                "event_payload": new_payload,
            },
        )
        log.info("Edited card %s in %s (user %s): %s", card_ts, channel, user_id, edit_line)
    except Exception as e:
        log.error("Failed to chat_update card %s with edits: %s", card_ts, e)
        return

    try:
        client.chat_postMessage(channel=channel, thread_ts=thread_ts, text=edit_line)
    except Exception as e:
        log.warning("Failed to post edit line to thread %s: %s", thread_ts, e)

    # Re-post draft BOM when items changed and there are enough items for a BOM
    items_changed = any(f.startswith("items") for f in fragments)
    if items_changed and bom.needs_bom(items):
        upload_draft_bom(
            client=client,
            channel=channel,
            thread_ts=thread_ts,
            parsed=new_parsed_stored,
            items=items,
            shipping=float(shipping or 0.0),
        )

