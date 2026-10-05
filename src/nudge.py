"""Reminders and nudges for stalled purchase requests.

WHY THIS EXISTS:
----------------
Orders stall silently when no one pokes the bot, leaving approved purchases
unprocessed with no reminder to anyone. The workbook knows a row is unprocessed
and how old it is, but not who the buyer is or which Slack thread the request lives in;
that information lives in the request log (requests.json) and on Slack cards.

Ticket 88 adds the confirmed nudge: once a request has a Date Processed (and no Date
Confirmed / Delivered) it is nudged every N working days from that date to mark it
Confirmed, by DM (re-posting the DM card via _repost_dm_card) and/or a broadcast thread
reply. Date Processed is read as the raw cell text, so parse_sheet_date accepts Excel
serials (what the bot writes) and typed dates; an unparseable one skips the entry with a
warning. The processed nudge still skips any entry with a Date Processed.

Ticket 90 adds the delivered nudge: once Date Confirmed is present (and Date Delivered is
not) and the thread card is still `confirmed`, every N working days from Date Confirmed
the buyer and the requester are asked "Has this been delivered?" on a nudge card (thread
reply broadcast to the channel and/or DM to both). Posting one first retires every earlier
nudge card listed in the entry's `nudge_cards`, so only one is live. The card's Delivered
button is a view over lifecycle.handle_delivery (app.handle_nudge_delivered_action).

Per ADR 0011 Decision 4 (amended by ADR 0013 decisions 2-3) & Tickets 78, 79, 80 & 87:
- Weekdays at 9:00 Central, check every logged request not yet Processed.
- The schedule is no longer hardcoded: nudge_settings.json (loaded once per run)
  says whether the processed nudge is on, every N working days, and whether it goes
  by DM, by a thread reply also sent to the channel, or both. Shipped default:
  every 3 working days, DM only. is_due(n, every) is the pure schedule rule.
- For assigned requests, count working days (Mon-Fri) elapsed since the buyer was set.
  When due: `dm` re-posts the buyer's DM card (retiring the old one with
  state="replaced") carrying Mark Processed and the buyer picker; `channel` posts a
  thread reply broadcast to the channel mentioning the buyer.
- For unassigned requests, count working days (Mon-Fri) elapsed since approval
  (approved_at). When due, one thread line mentioning all buyers from
  roster.get_buyers(), repeated every N days with no upper limit until someone is
  assigned; reply_broadcast only when `channel` is set.
- The date is passed as an explicit argument to run_nudges(client, today: date)
  rather than reading the system clock, allowing the schedule to be tested honestly
  without waiting days.
- Skips entries with no approved_at (ADR 0013 decision 7: the log now also holds posted,
  declined and superseded cards; this nudge covers approved requests only).
- The approved nudge (ticket 94, ships off) is the one stage that acts on exactly those
  unapproved entries: _nudge_approved reminds the approvers every N working days from
  posting while the thread card is still `posted`, and stops on approval, decline or
  supersede. It runs even when the processed nudge is disabled.
- Skips Saturday/Sunday, cancelled requests, requests already nudged today, and
  requests where any row in the workbook already has Date Processed filled in.
- Each request entry is processed in its own try/except block so one failure
  never blocks the remaining requests.
- The 9:00 weekday timer: run_if_due checks whether the run is due on weekdays
  at or after 9:00, records the run in nudge_run.json atomically, and catches up
  if started late. start_nudge_scheduler runs as a background daemon thread beside
  heartbeat.
"""
import json
import logging
import os
import tempfile
import threading
from datetime import date, datetime, time, timedelta
from typing import Any, Optional

try:
    from . import blocks, config, lifecycle, log_writer, nudge_settings, roster, slack_io, store
except ImportError:
    import blocks  # type: ignore[no-redef]
    import config  # type: ignore[no-redef]
    import lifecycle  # type: ignore[no-redef]
    import log_writer  # type: ignore[no-redef]
    import nudge_settings  # type: ignore[no-redef]
    import roster  # type: ignore[no-redef]
    import slack_io  # type: ignore[no-redef]
    import store  # type: ignore[no-redef]

log = logging.getLogger("p-bot.nudge")

NUDGE_RUN_PATH = os.path.join(config.BASE_DIR, "nudge_run.json")


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


def is_due(n: int, every: int) -> bool:
    """True on working day n when a nudge repeating every `every` days is due."""
    return n >= every and n % every == 0


def parse_sheet_date(value) -> Optional[date]:
    """Parse a workbook date cell into a date, or None when it is empty or unreadable.

    The bot writes dates as Excel serial numbers (log_writer._to_serial, day 0 =
    1899-12-30) and get_row_info returns the raw cell text, so a serial (int, float or
    numeric string) is the normal case; ISO, M/D/YYYY and M/D/YY cover hand-typed cells.
    Pure function.
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, (int, float)):
        try:
            return date(1899, 12, 30) + timedelta(days=int(value))
        except (OverflowError, ValueError):
            return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return date(1899, 12, 30) + timedelta(days=int(float(text)))
    except (OverflowError, ValueError):
        pass
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        pass
    for fmt in ("%m/%d/%Y", "%m/%d/%y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def _item_of(req_data: dict) -> str:
    parsed = req_data.get("parsed")
    if isinstance(parsed, dict):
        return parsed.get("item_description") or req_data.get("item_description") or "Item"
    return req_data.get("item_description") or "Item"


def _repost_dm_card(client, entry, req_data, history, card_state, section_text):
    """Retire the buyer's DM card and post a fresh one headed by section_text.

    Shared by the processed nudge (card_state "approved") and the confirmed nudge
    ("processed"). Updates the thread card's DM pointers and returns the new
    (dm_channel, dm_ts).
    """
    channel = entry.get("channel")
    thread_ts = entry.get("thread_ts")
    card_ts = entry.get("card_ts")
    buyer_id = entry.get("buyer_id")

    # Ensure dm pointers exist in req_data if present in store entry
    if not req_data.get("dm_channel") and entry.get("dm_channel"):
        req_data["dm_channel"] = entry.get("dm_channel")
    if not req_data.get("dm_ts") and entry.get("dm_ts"):
        req_data["dm_ts"] = entry.get("dm_ts")

    lifecycle.sync_dm_card(
        client=client,
        request=req_data,
        state="replaced",
        channel=channel,
        thread_ts=thread_ts,
        card_ts=card_ts,
        note="Replaced by the reminder below.",
    )

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
        state=card_state,
        request=req_data,
        thread_channel=channel,
        thread_ts=thread_ts,
        card_ts=card_ts,
        thread_link=thread_link,
    )
    dm_blocks = [
        {"type": "section", "text": {"type": "mrkdwn", "text": section_text}}
    ] + dm_card_blocks

    resp = client.chat_postMessage(channel=buyer_id, text=section_text, blocks=dm_blocks)

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

    # Point the thread card at the new DM card so two-card sync follows it
    req_data["dm_channel"] = new_dm_channel
    req_data["dm_ts"] = new_dm_ts
    client.chat_update(
        channel=channel,
        ts=card_ts,
        text=f"🛒 Purchase Request ({card_state.capitalize()})",
        blocks=blocks.build_request_blocks(card_state, req_data, history=history),
    )
    return new_dm_channel, new_dm_ts


def _confirmed_nudge(client, req_id, entry, info, cfg, today) -> bool:
    """Confirmed nudge: processed, not yet confirmed. Returns True if a nudge went out."""
    if not cfg["enabled"] or info.get("date_confirmed") or info.get("date_delivered"):
        return False
    buyer_id = entry.get("buyer_id")
    channel = entry.get("channel")
    thread_ts = entry.get("thread_ts")
    card_ts = entry.get("card_ts")
    if not (buyer_id and channel and thread_ts and card_ts):
        return False
    processed_on = parse_sheet_date(info.get("date_processed"))
    if processed_on is None:
        log.warning("Unreadable Date Processed %r for request [%s]; skipping confirmed nudge",
                    info.get("date_processed"), req_id)
        return False
    n = working_days_between(processed_on, today)
    if not is_due(n, cfg["every"]):
        return False
    card = slack_io.get_card_by_ts(client, channel, thread_ts, card_ts)
    if not card:
        log.warning("Card not found for request [%s] (%s, %s, %s)", req_id, channel, thread_ts, card_ts)
        return False
    req_data, history, card_state = card
    if card_state != "processed":
        return False
    if not isinstance(req_data, dict):
        req_data = {}

    updates: dict[str, Any] = {"last_nudged": today.isoformat()}
    if cfg["dm"]:
        item = _item_of(req_data)
        dm_channel, dm_ts = _repost_dm_card(
            client, entry, req_data, history, "processed",
            f"⏰ {item} was processed {n} working days ago and isn't marked Confirmed yet.",
        )
        updates.update(dm_channel=dm_channel, dm_ts=dm_ts)
    if cfg["channel"]:
        client.chat_postMessage(
            channel=channel,
            thread_ts=thread_ts,
            reply_broadcast=True,
            text=f"⏰ <@{buyer_id}> — this request was processed {n} working days ago and isn't marked Confirmed yet.",
        )
    store.update(req_id, **updates)
    log.info("Confirmed-nudged request [%s] (day %d) for buyer %s", req_id, n, buyer_id)
    return True


def _delivered_nudge(client, req_id, entry, info, cfg, today) -> bool:
    """Delivered nudge (ADR 0013 decisions 1, 2, 4): confirmed, not yet delivered.

    Posts the nudge card to the thread (broadcast) and/or by DM to the buyer and the
    requester, and retires every earlier nudge card first so only one is ever live. Returns
    True if a nudge went out.
    """
    if not cfg["enabled"] or info.get("date_delivered"):
        return False
    buyer_id = entry.get("buyer_id")
    channel = entry.get("channel")
    thread_ts = entry.get("thread_ts")
    card_ts = entry.get("card_ts")
    if not (buyer_id and channel and thread_ts and card_ts):
        return False
    confirmed_on = parse_sheet_date(info.get("date_confirmed"))
    if confirmed_on is None:
        log.warning("Unreadable Date Confirmed %r for request [%s]; skipping delivered nudge",
                    info.get("date_confirmed"), req_id)
        return False
    n = working_days_between(confirmed_on, today)
    if not is_due(n, cfg["every"]):
        return False
    card = slack_io.get_card_by_ts(client, channel, thread_ts, card_ts)
    if not card:
        log.warning("Card not found for request [%s] (%s, %s, %s)", req_id, channel, thread_ts, card_ts)
        return False
    req_data, _history, card_state = card
    if card_state != "confirmed":
        return False
    if not isinstance(req_data, dict):
        req_data = {}

    requester_id = entry.get("requester_id") or req_data.get("user_id")
    mentions = f"<@{buyer_id}>"
    if requester_id and requester_id != buyer_id:
        mentions += f" <@{requester_id}>"
    item = _item_of(req_data)

    lifecycle.update_nudge_cards(
        client, entry.get("nudge_cards") or [], "replaced", mentions, item, n,
        channel, thread_ts, card_ts, note="Replaced by a newer reminder.")

    active = blocks.build_nudge_card_blocks("active", mentions, item, n, channel, thread_ts, card_ts)
    text = active[0]["text"]["text"]
    posted: list[list[str]] = []
    if cfg["channel"]:
        resp = client.chat_postMessage(
            channel=channel, thread_ts=thread_ts, reply_broadcast=True, blocks=active, text=text)
        posted.append([channel, _resp_get(resp, "ts")])
    if cfg["dm"]:
        for target in dict.fromkeys(t for t in (buyer_id, requester_id) if t):
            resp = client.chat_postMessage(channel=target, blocks=active, text=text)
            posted.append([_resp_get(resp, "channel") or target, _resp_get(resp, "ts")])
    store.update(req_id, last_nudged=today.isoformat(), nudge_cards=posted)
    log.info("Delivered-nudged request [%s] (day %d): %d card(s) posted", req_id, n, len(posted))
    return True


def _resp_get(resp, key):
    data = resp.data if hasattr(resp, "data") and isinstance(resp.data, dict) else resp
    return data.get(key) if hasattr(data, "get") else None


def _permalink(client, channel: str, card_ts: str) -> Optional[str]:
    """The card's permalink, or None when Slack will not give one."""
    try:
        resp = client.chat_getPermalink(channel=channel, message_ts=card_ts)
        data = resp.data if hasattr(resp, "data") and isinstance(resp.data, dict) else resp
        return data.get("permalink")
    except Exception as err:
        log.warning("Could not get permalink for card (%s, %s): %s", channel, card_ts, err)
        return None


def _nudge_approved(client, today: date, store_data: dict, cfg: dict) -> list[str]:
    """The approved nudge (ADR 0013 decision 1): remind approvers about a posted card.

    Applies to entries with posted_at and no approved_at that are not declined,
    superseded or cancelled, counting working days from posting. The thread card must
    still be in state `posted`: a card approved by keyword before the log caught up is
    skipped. `dm` goes to each approver with a permalink and no buttons; `channel` is a
    thread reply also sent to the channel mentioning every approver.
    """
    nudged: list[str] = []
    for req_id, entry in store_data.items():
        try:
            if not entry.get("posted_at") or entry.get("approved_at"):
                continue
            if entry.get("declined") or entry.get("superseded") or entry.get("cancelled"):
                continue
            if entry.get("last_nudged") == today.isoformat():
                continue
            n = working_days_between(date.fromisoformat(entry["posted_at"][:10]), today)
            if not is_due(n, cfg["every"]):
                continue
            channel, thread_ts, card_ts = entry.get("channel"), entry.get("thread_ts"), entry.get("card_ts")
            if not channel or not thread_ts or not card_ts:
                continue
            card = slack_io.get_card_by_ts(client, channel, thread_ts, card_ts)
            if not card or card[2] != "posted":
                continue
            req_data = card[0] if isinstance(card[0], dict) else {}
            parsed = req_data.get("parsed")
            item = (parsed.get("item_description") if isinstance(parsed, dict) else None) \
                or req_data.get("item_description") or "Item"
            approvers = roster.get_approvers()
            if cfg["dm"]:
                link = _permalink(client, channel, card_ts)
                text = (f"⏰ *{item}* from {entry.get('requester') or 'a requester'} has been waiting "
                        f"for approval for {n} working days: {link or ''}").strip()
                for approver_id in approvers:
                    client.chat_postMessage(channel=approver_id, text=text)
            if cfg["channel"]:
                mentions = " ".join(f"<@{a}>" for a in approvers)
                client.chat_postMessage(
                    channel=channel, thread_ts=thread_ts, reply_broadcast=True,
                    text=f"⏰ {mentions} — this request has been waiting for approval for {n} working days.",
                )
            store.update(req_id, last_nudged=today.isoformat())
            nudged.append(req_id)
            log.info("Nudged approvers about unapproved request [%s] (day %d)", req_id, n)
        except Exception as e:
            log.error("Failed to approved-nudge request [%s]: %s", req_id, e)
    return nudged


def run_nudges(client, today: date) -> list[str]:
    """Execute one day's nudging for assigned and unassigned requests.

    Walks store.load_store and sends reminders according to the working-day schedule.
    Returns the list of request IDs that were nudged.
    """
    if today.weekday() >= 5:
        # Weekend: no nudges on Saturday or Sunday
        return []

    store_data = store.load_store(alert_callback=lambda msg: slack_io.alert_admins(client, msg))
    settings = nudge_settings.load(alert_callback=lambda msg: slack_io.alert_admins(client, msg))
    nudged_ids: list[str] = []
    if settings["approved"]["enabled"]:
        nudged_ids.extend(_nudge_approved(client, today, store_data, settings["approved"]))
    processed_cfg = settings["processed"]
    every = processed_cfg["every"]
    want_dm = processed_cfg["dm"]
    want_channel = processed_cfg["channel"]

    for req_id, entry in store_data.items():
        try:
            if entry.get("cancelled"):
                continue

            # ADR 0013 decision 7: the log also holds posted cards nobody has approved
            # (and declined / superseded ones). This nudge covers approved requests only.
            if not entry.get("approved_at"):
                continue

            if entry.get("last_nudged") == today.isoformat():
                continue

            # Check if any row already has Date Processed filled in the workbook
            rows = entry.get("rows") or []
            has_date_processed = False
            first_info = None
            for r in rows:
                try:
                    info = log_writer.get_row_info(r)
                    if info and info.get("date_processed"):
                        has_date_processed = True
                        first_info = info
                        break
                except Exception as row_err:
                    log.warning("Could not read row info for row %s of request [%s]: %s", r, req_id, row_err)

            if has_date_processed:
                # Processed already: the confirmed nudge takes over (ticket 88), and once
                # Date Confirmed is present the delivered nudge does (ticket 90).
                info = first_info or {}
                if info.get("date_confirmed"):
                    if _delivered_nudge(client, req_id, entry, info, settings["delivered"], today):
                        nudged_ids.append(req_id)
                elif _confirmed_nudge(client, req_id, entry, info, settings["confirmed"], today):
                    nudged_ids.append(req_id)
                continue

            if not processed_cfg["enabled"]:
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
                if not is_due(n, every):
                    continue

                buyers = roster.get_buyers()
                mentions = " ".join(f"<@{bid}>" for bid in buyers) if buyers else ""
                msg_text = f"⏰ Approved {n} working days ago and nobody's assigned yet. {mentions}".strip()

                post_kwargs = {"channel": channel, "thread_ts": thread_ts, "text": msg_text}
                if want_channel:
                    post_kwargs["reply_broadcast"] = True
                client.chat_postMessage(**post_kwargs)

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

            if not is_due(n, every):
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

            new_dm_channel = None
            new_dm_ts = None
            if want_dm:
                item = _item_of(req_data)
                new_dm_channel, new_dm_ts = _repost_dm_card(
                    client, entry, req_data, history, "approved",
                    f"⏰ {item} has been assigned to you for {n} working days and isn't marked Processed yet.",
                )

            # `channel` setting: broadcast a thread reply to the channel
            if want_channel:
                broadcast_text = f"⏰ <@{buyer_id}> — this request was approved {n} working days ago and isn't marked Processed yet."
                client.chat_postMessage(
                    channel=channel,
                    thread_ts=thread_ts,
                    reply_broadcast=True,
                    text=broadcast_text,
                )

            # Update request log with last_nudged date and new DM coordinates
            updates: dict[str, Any] = {"last_nudged": today.isoformat()}
            if want_dm:
                updates.update(dm_channel=new_dm_channel, dm_ts=new_dm_ts)
            store.update(req_id, **updates)
            nudged_ids.append(req_id)
            log.info("Nudged request [%s] (day %d) for buyer %s", req_id, n, buyer_id)

        except Exception as e:
            log.error("Failed to nudge request [%s]: %s", req_id, e)

    return nudged_ids


def _read_last_run() -> Optional[str]:
    """Read the last run date string from NUDGE_RUN_PATH.

    Returns None if missing, corrupt, or not containing a valid last_run string.
    """
    if not os.path.exists(NUDGE_RUN_PATH):
        return None
    try:
        with open(NUDGE_RUN_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            last_run = data.get("last_run")
            if isinstance(last_run, str):
                return last_run
    except Exception as e:
        log.warning("Could not read nudge run file %s (treating as never run): %s", NUDGE_RUN_PATH, e)
    return None


def _write_last_run(run_date_iso: str) -> None:
    """Atomically write {"last_run": run_date_iso} to NUDGE_RUN_PATH."""
    dir_name = os.path.dirname(os.path.abspath(NUDGE_RUN_PATH))
    os.makedirs(dir_name, exist_ok=True)

    with tempfile.NamedTemporaryFile("w", dir=dir_name, delete=False, encoding="utf-8") as tf:
        json.dump({"last_run": run_date_iso}, tf, indent=2)
        temp_path = tf.name

    try:
        os.replace(temp_path, NUDGE_RUN_PATH)
        log.debug("Wrote nudge last_run=%s to %s", run_date_iso, NUDGE_RUN_PATH)
    except Exception as e:
        log.error("Failed to replace nudge run file with %s: %s", temp_path, e)
        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except Exception:
                pass
        raise


def run_if_due(client, now: datetime) -> bool:
    """Check if the weekday 9:00 nudge is due and run it if so.

    Returns False without calling run_nudges when:
    - now is Saturday or Sunday (now.weekday() >= 5)
    - now.time() < time(9, 0)
    - the last_run in NUDGE_RUN_PATH matches today's date (now.date().isoformat())

    Otherwise, calls run_nudges(client, now.date()), writes today's date to NUDGE_RUN_PATH,
    and returns True. A missing or unreadable file counts as never run.
    """
    if now.weekday() >= 5:
        return False

    if now.time() < time(9, 0):
        return False

    today_iso = now.date().isoformat()
    last_run = _read_last_run()
    if last_run == today_iso:
        return False

    run_nudges(client, now.date())
    _write_last_run(today_iso)
    return True


def start_nudge_scheduler(
    client,
    interval_seconds: int = 60,
    stop_event: Optional[threading.Event] = None,
) -> threading.Thread:
    """Start the background daemon thread that runs run_if_due periodically."""
    if stop_event is None:
        stop_event = threading.Event()

    def _loop():
        log.info("NudgeSchedulerThread started (interval: %ds)", interval_seconds)
        while not stop_event.is_set():
            try:
                run_if_due(client, datetime.now())
            except Exception as e:
                log.error("Error in nudge scheduler loop: %s", e)
            if stop_event.wait(interval_seconds):
                break
        log.info("NudgeSchedulerThread stopped.")

    thread = threading.Thread(
        target=_loop,
        name="NudgeSchedulerThread",
        daemon=True,
    )
    thread.start()
    return thread
