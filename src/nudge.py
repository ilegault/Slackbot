"""Reminders and nudges for stalled purchase requests.

WHY THIS EXISTS:
----------------
Orders stall silently when no one pokes the bot, leaving approved purchases
unprocessed with no reminder to anyone. The workbook knows a row is unprocessed
and how old it is, but not who the buyer is or which Slack thread the request lives in;
that information lives in the request log (requests.json) and on Slack cards.

Per ADR 0011 Decision 4 & Spec ("The nudge") & Tickets 78 & 79:
- Weekdays at 9:00 Central, check every logged request not yet Processed.
- For assigned requests, count working days (Mon-Fri) elapsed since the buyer was set:
  - Day 3: private DM to the buyer re-posting their DM card (retiring the old one
    with state="replaced") carrying Mark Processed and the buyer picker.
  - Day 6: same DM plus a thread reply broadcast to the channel mentioning the buyer.
  - Day 9, 12, ...: DM only.
- For unassigned requests, count working days (Mon-Fri) elapsed since approval (approved_at):
  - Day 3: thread reply with text mentioning all buyers from roster.get_buyers().
  - Day 6: same message with reply_broadcast=True.
  - Day 9, 12, ...: nothing.
- The date is passed as an explicit argument to run_nudges(client, today: date)
  rather than reading the system clock, allowing the schedule to be tested honestly
  without waiting days.
- Skips Saturday/Sunday, cancelled requests, requests already nudged today, and
  requests where any row in the workbook already has Date Processed filled in.
- Each request entry is processed in its own try/except block so one failure
  never blocks the remaining requests.
"""
import logging
from datetime import date, timedelta

try:
    from . import blocks, lifecycle, log_writer, roster, slack_io, store
except ImportError:
    import blocks  # type: ignore[no-redef]
    import lifecycle  # type: ignore[no-redef]
    import log_writer  # type: ignore[no-redef]
    import roster  # type: ignore[no-redef]
    import slack_io  # type: ignore[no-redef]
    import store  # type: ignore[no-redef]

log = logging.getLogger("p-bot.nudge")


def working_days_between(start: date, end: date) -> int:
    """Calculate the number of Mon-Fri dates d with start < d <= end.

    Holidays are not skipped. Pure function.
    Returns 0 if end <= start.
    """
    if end <= start:
        return 0
    cur = start + timedelta(days=1)
    count = 0
    while cur <= end:
        if cur.weekday() < 5:  # Monday=0, ..., Friday=4
            count += 1
        cur += timedelta(days=1)
    return count


def run_nudges(client, today: date) -> list[str]:
    """Execute one day's nudging for assigned and unassigned requests.

    Walks store.load_store and sends reminders according to the working-day schedule.
    Returns the list of request IDs that were nudged.
    """
    if today.weekday() >= 5:
        # Weekend: no nudges on Saturday or Sunday
        return []

    store_data = store.load_store(alert_callback=lambda msg: slack_io.alert_admins(client, msg))
    nudged_ids: list[str] = []

    for req_id, entry in store_data.items():
        try:
            if entry.get("cancelled"):
                continue

            if entry.get("last_nudged") == today.isoformat():
                continue

            # Check if any row already has Date Processed filled in the workbook
            rows = entry.get("rows") or []
            has_date_processed = False
            for r in rows:
                try:
                    info = log_writer.get_row_info(r)
                    if info and info.get("date_processed"):
                        has_date_processed = True
                        break
                except Exception as row_err:
                    log.warning("Could not read row info for row %s of request [%s]: %s", r, req_id, row_err)

            if has_date_processed:
                continue

            buyer_id = entry.get("buyer_id")
            channel = entry.get("channel")
            thread_ts = entry.get("thread_ts")
            card_ts = entry.get("card_ts")

            if not buyer_id:
                # Unassigned request path (Ticket 79)
                if not channel or not thread_ts:
                    continue

                approved_at = entry.get("approved_at")
                if not approved_at:
                    continue

                n = working_days_between(date.fromisoformat(approved_at[:10]), today)
                if n not in (3, 6):
                    continue

                buyers = roster.get_buyers()
                mentions = " ".join(f"<@{bid}>" for bid in buyers) if buyers else ""
                msg_text = f"⏰ Approved {n} working days ago and nobody's assigned yet. {mentions}".strip()

                if n == 3:
                    client.chat_postMessage(
                        channel=channel,
                        thread_ts=thread_ts,
                        text=msg_text,
                    )
                elif n == 6:
                    client.chat_postMessage(
                        channel=channel,
                        thread_ts=thread_ts,
                        reply_broadcast=True,
                        text=msg_text,
                    )

                store.update(req_id, last_nudged=today.isoformat())
                nudged_ids.append(req_id)
                log.info("Nudged unassigned request [%s] (day %d)", req_id, n)
                continue

            # Assigned request path (Ticket 78)
            buyer_set_at = entry.get("buyer_set_at")
            if not buyer_set_at:
                continue

            start_date = date.fromisoformat(buyer_set_at[:10])
            n = working_days_between(start_date, today)

            if not (n == 3 or n == 6 or (n > 6 and n % 3 == 0)):
                continue

            # Load the thread card to verify state is approved
            if not channel or not thread_ts or not card_ts:
                continue

            card = slack_io.get_card_by_ts(client, channel, thread_ts, card_ts)
            if not card:
                log.warning("Card not found for request [%s] (%s, %s, %s)", req_id, channel, thread_ts, card_ts)
                continue

            req_data, history, card_state = card
            if card_state != "approved":
                continue

            if not isinstance(req_data, dict):
                req_data = {}

            # Ensure dm pointers exist in req_data if present in store entry
            if not req_data.get("dm_channel") and entry.get("dm_channel"):
                req_data["dm_channel"] = entry.get("dm_channel")
            if not req_data.get("dm_ts") and entry.get("dm_ts"):
                req_data["dm_ts"] = entry.get("dm_ts")

            # Retire the buyer's current DM card
            lifecycle.sync_dm_card(
                client=client,
                request=req_data,
                state="replaced",
                channel=channel,
                thread_ts=thread_ts,
                card_ts=card_ts,
                note="Replaced by the reminder below.",
            )

            # Build and post the fresh DM card
            parsed = req_data.get("parsed")
            if isinstance(parsed, dict):
                item = parsed.get("item_description") or req_data.get("item_description") or "Item"
            else:
                item = req_data.get("item_description") or "Item"

            if not req_data.get("assignee_id"):
                req_data["assignee_id"] = buyer_id

            thread_link = None
            try:
                resp_link = client.chat_getPermalink(channel=channel, message_ts=card_ts)
                if isinstance(resp_link, dict):
                    thread_link = resp_link.get("permalink")
                elif hasattr(resp_link, "get"):
                    thread_link = resp_link.get("permalink")
                elif hasattr(resp_link, "data") and isinstance(resp_link.data, dict):
                    thread_link = resp_link.data.get("permalink")
            except Exception as link_err:
                log.warning("Could not get thread link for card (%s, %s): %s", channel, card_ts, link_err)
                thread_link = None

            dm_card_blocks = blocks.build_dm_card_blocks(
                state="approved",
                request=req_data,
                thread_channel=channel,
                thread_ts=thread_ts,
                card_ts=card_ts,
                thread_link=thread_link,
            )

            section_text = f"⏰ {item} has been assigned to you for {n} working days and isn't marked Processed yet."
            dm_blocks = [
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": section_text,
                    },
                }
            ] + dm_card_blocks

            resp = client.chat_postMessage(
                channel=buyer_id,
                text=section_text,
                blocks=dm_blocks,
            )

            new_dm_ts = None
            new_dm_channel = None
            if isinstance(resp, dict):
                new_dm_ts = resp.get("ts")
                new_dm_channel = resp.get("channel")
            elif hasattr(resp, "get"):
                new_dm_ts = resp.get("ts")
                new_dm_channel = resp.get("channel")
            elif hasattr(resp, "data") and isinstance(resp.data, dict):
                new_dm_ts = resp.data.get("ts")
                new_dm_channel = resp.data.get("channel")

            if not new_dm_channel:
                new_dm_channel = buyer_id

            # Update the thread card with the new DM references so two-card sync points at new DM card
            req_data["dm_channel"] = new_dm_channel
            req_data["dm_ts"] = new_dm_ts
            thread_card_blocks = blocks.build_request_blocks("approved", req_data, history=history)
            client.chat_update(
                channel=channel,
                ts=card_ts,
                text="🛒 Purchase Request (Approved)",
                blocks=thread_card_blocks,
            )

            # On day 6 only, broadcast a thread reply to the channel
            if n == 6:
                broadcast_text = f"⏰ <@{buyer_id}> — this request was approved {n} working days ago and isn't marked Processed yet."
                client.chat_postMessage(
                    channel=channel,
                    thread_ts=thread_ts,
                    reply_broadcast=True,
                    text=broadcast_text,
                )

            # Update request log with last_nudged date and new DM coordinates
            store.update(req_id, last_nudged=today.isoformat(), dm_channel=new_dm_channel, dm_ts=new_dm_ts)
            nudged_ids.append(req_id)
            log.info("Nudged request [%s] (day %d) for buyer %s", req_id, n, buyer_id)

        except Exception as e:
            log.error("Failed to nudge request [%s]: %s", req_id, e)

    return nudged_ids
