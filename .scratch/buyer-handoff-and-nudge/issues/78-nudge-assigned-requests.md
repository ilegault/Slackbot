# 78: Nudge assigned requests

**Status:** done

**Runner:** any

**Auto-merge:** yes

**Blocked by:** 74, 77

**Spec:** `.scratch/buyer-handoff-and-nudge/spec.md` ("The nudge")
**Binding:** `docs/adr/0011-buyers-hand-off-requests-and-the-request-log.md` decision 4, `docs/adr/0010-linked-cards-and-direct-message-help.md` decisions 2–3, ADR 0001

## What to build

A function that does one day's nudging for **assigned** requests. It takes today's date as an
argument — it never reads the clock — so tests can pick any day. Ticket 80 calls it on a timer;
ticket 79 adds unassigned requests. **The date parameter is a requirement, not a preference:**
without it the schedule can't be tested without waiting days.

1. New module `src/nudge.py` with:
   - `working_days_between(start: date, end: date) -> int` — the number of Mon–Fri dates `d`
     with `start < d <= end`. Holidays are not skipped. Pure function.
   - `run_nudges(client, today: date) -> list[str]` — returns the request IDs it nudged.
2. `run_nudges` walks `store.load_store(alert_callback=…)` and, for each entry with a
   `buyer_id` (unassigned entries are skipped here), skips it when any of:
   `cancelled` is true; `last_nudged == today.isoformat()`; `today` is Saturday or Sunday;
   any of its `rows` has a non-empty `date_processed` from `log_writer.get_row_info(row)`
   (so a date typed into the workbook by hand stops nudges).
   Otherwise `n = working_days_between(date.fromisoformat(buyer_set_at[:10]), today)` and it
   acts when `n == 3`, `n == 6`, or `n > 6 and n % 3 == 0`.
3. **To act** (the DM re-post): load the thread card with
   `slack_io.get_card_by_ts(client, channel, thread_ts, card_ts)`; if it is missing or its state
   is not `approved`, skip. Retire the buyer's current DM card with `lifecycle.sync_dm_card(...,
   state="replaced", note="Replaced by the reminder below.")` — add `replaced` as a retired state
   in `blocks.build_dm_card_blocks` (note shown, no `actions` block), as ticket 69 did for
   `reassigned`. Then one `chat_postMessage(channel=buyer_id, …)` whose blocks are a section
   `⏰ <item> has been assigned to you for <n> working days and isn't marked Processed yet.`
   followed by `blocks.build_dm_card_blocks("approved", …)` (which carries Mark Processed and,
   after ticket 74, the buyer picker). Store the response's `channel` and `ts` as the request's
   `dm_channel` / `dm_ts` and `chat_update` the thread card with
   `blocks.build_request_blocks("approved", req_data, history=history)` so the two-card sync
   points at the new DM card.
4. **On day 6 only**, also `chat_postMessage(channel=<thread channel>, thread_ts=thread_ts,
   reply_broadcast=True, text="⏰ <@buyer_id> — this request was approved <n> working days ago and isn't marked Processed yet.")`.
5. After acting, `store.update(id, last_nudged=today.isoformat())`. Every entry is wrapped in
   `try/except`: a failure is logged at ERROR and the loop moves to the next entry.

## Acceptance criteria

New test file `tests/test_78_nudge_assigned.py`. Temp `requests.json` via `store.STORE_PATH`;
`log_writer.get_row_info` monkeypatched to return `{"date_processed": ""}` or a date per row;
fake client whose `conversations_replies` returns an `approved` thread card for the entry (helper as
`tests/test_69_cards_move_together.py`). Entry: `buyer_set_at` = Monday 2026-10-05.

- [x] **`working_days_between`** (2026-10-05, 2026-10-08) == 3; (Fri 2026-10-09, Mon 2026-10-12) == 1;
  (2026-10-05, 2026-10-05) == 0.
- [x] **Day 2 nothing, day 3 DM only.** `run_nudges(client, date(2026,10,7))` → no
  `chat_postMessage`. `date(2026,10,8)` → exactly one `chat_postMessage` to the buyer's ID whose
  blocks contain `3 working days` and a `Mark Processed` button, the old DM card is updated with
  `Replaced by the reminder below` and no `actions` block, the thread card's `chat_update`
  carries the new DM `ts`, no message has `reply_broadcast`, and the entry's `last_nudged` is
  `2026-10-08`.
- [x] **Day 6 adds one channel post; day 9 is DM only.** 2026-10-13 → the DM plus exactly one post
  with `reply_broadcast=True`, `thread_ts` = the thread, text containing `<@U_A>`.
  2026-10-16 → DM, no `reply_broadcast`. 2026-10-14 (day 7) → nothing.
- [x] **It stops when it should.** Each of these on day 3 → no `chat_postMessage`: a row with a
  `date_processed`; `cancelled=True`; `last_nudged == "2026-10-08"` (a second call the same day);
  a Saturday date; `buyer_set_at` moved to 2026-10-07 by a reassignment (day 1).
- [x] **One failure doesn't stop the rest.** Two due entries, `chat_postMessage` raising for the
  first buyer's ID: the second buyer still gets the DM and only the second entry's `last_nudged`
  is set.

**Tests may fake:** the Slack client, `log_writer.get_row_info`. **Must be real:** `nudge`, `store`
on the temp file, `blocks`, `lifecycle.sync_dm_card`.

## Gate

Run in this order, exactly as CI does (`.github/workflows/tests.yml`). Zero failures before
you push. If `tools/type_gate.py` exists on `master` when you start, also run
`python tools/type_gate.py` after `check_tests_first.py`, and use
`pytest --tb=short -q -n auto --dist loadfile` in place of the last line.

```
ruff check .
python scripts/check_tests_first.py
pytest -q --tb=short --durations=25
```

## Comments

### Landed 2026-10-01
- `src/nudge.py`:
  - New module implementing `working_days_between(start, end)` (pure Mon-Fri working days calculation) and `run_nudges(client, today)` for assigned requests.
  - Checks requests from `store.load_store`, skips cancelled, weekend, already-nudged-today, and requests with `date_processed` in workbook rows.
  - On schedule (days 3, 6, 9+), retires buyer's old DM card with `state="replaced"` and note `"Replaced by the reminder below."`, posts fresh DM card with Mark Processed button and buyer picker, updates thread card with new DM references, sends channel broadcast on day 6, and updates `last_nudged` in store.
  - Error isolation: each entry is processed in a separate `try/except` block so failure on one request does not block others.
- `src/blocks.py`:
  - Added `replaced` as a retired DM card state in `build_dm_card_blocks` displaying note without action buttons.
- `tests/test_78_nudge_assigned.py`:
  - Added 5 unit tests covering all acceptance criteria.
- `tests/test_69_cards_move_together.py`:
  - Added test case verifying `replaced` retired state in `test_retired_states_have_no_buttons`.
- Gate: ruff check passed, check_tests_first passed, type_gate passed (0 hard, 0 soft), full pytest suite passed (586 passed, 31 skipped).

