# 79: Nudge unassigned requests

**Status:** done

**Runner:** any

**Auto-merge:** yes

**Blocked by:** 78

**Spec:** `.scratch/buyer-handoff-and-nudge/spec.md` ("The nudge", unassigned row)
**Binding:** `docs/adr/0011-buyers-hand-off-requests-and-the-request-log.md` decision 4, ADR 0001

## What to build

An approved request with nobody assigned gets one thread line @-mentioning every buyer at 3
working days after approval, the same line also sent to the channel at 6, and nothing after.

1. `nudge.run_nudges`: entries with no `buyer_id` are no longer skipped. The same skip rules as
   ticket 78 apply (cancelled, already nudged today, weekend, any row processed). Then
   `n = working_days_between(date.fromisoformat(approved_at[:10]), today)`.
2. `n == 3`: `chat_postMessage(channel=<thread channel>, thread_ts=thread_ts, text=…)` with text
   `⏰ Approved <n> working days ago and nobody's assigned yet.` followed by a space-separated
   `<@id>` for every ID in `roster.get_buyers()`. No "pick yourself" wording.
3. `n == 6`: the same message with `reply_broadcast=True`.
4. Any other `n`: nothing. After acting, `last_nudged` is set as in ticket 78.
5. If the entry has gained a buyer since (`buyer_id` set), ticket 78's path handles it, not this one.

## Acceptance criteria

New test file `tests/test_79_nudge_unassigned.py`, fixtures as ticket 78 with a roster of three
buyers; entry `approved_at` Monday 2026-10-05, `buyer_id` None.

- [x] **Day 3.** `run_nudges(client, date(2026,10,8))`: exactly one `chat_postMessage` with
  `thread_ts` = the thread, no `reply_broadcast`, text containing `nobody's assigned` and
  `<@…>` for all three buyers, and not containing `yourself`. No message to any user ID (no DM).
- [x] **Day 6.** `date(2026,10,13)`: the same text with `reply_broadcast=True`.
- [x] **Nothing after.** `date(2026,10,16)` (day 9) and `date(2026,10,21)` (day 12): no `chat_postMessage`.
- [x] **Stops on processed, cancel, same day.** Day 3 with a row `date_processed`, with
  `cancelled=True`, or called twice on 2026-10-08: no message (the second call adds none).

**Tests may fake:** the Slack client, `log_writer.get_row_info`. **Must be real:** `nudge`, `store`
on the temp file, the roster on a temp file.

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
  - Handled unassigned requests (`not buyer_id`) in `run_nudges(client, today: date)`.
  - Calculates working days elapsed since `approved_at` using `working_days_between`.
  - Applies identical skip rules (weekend, cancelled, last_nudged == today, row date_processed).
  - On Day 3, posts single message to request thread mentioning all buyers from `roster.get_buyers()`.
  - On Day 6, posts identical message with `reply_broadcast=True`.
  - On any other day (Day 9, 12, etc.), takes no action.
  - Updates `last_nudged` date in `store` on action.
  - Entries with `buyer_id` set continue through the assigned request flow.
- `tests/test_79_nudge_unassigned.py`:
  - New test module covering Day 3 thread message with buyer mentions and no DM (`test_day_3_unassigned_nudge`), Day 6 thread broadcast (`test_day_6_broadcast`), no action on Day 9/12 (`test_nothing_after`), suppression when processed, cancelled, or run twice on the same day (`test_stops_on_processed_cancel_same_day`), and buyer assigned delegation (`test_entry_with_buyer_id_uses_assigned_path`).
