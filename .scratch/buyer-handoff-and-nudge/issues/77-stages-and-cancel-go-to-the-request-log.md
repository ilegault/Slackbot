# 77: Stages and cancel are written to the request log

**Status:** ready-for-agent

**Runner:** any

**Auto-merge:** yes

**Blocked by:** 76

**Spec:** `.scratch/buyer-handoff-and-nudge/spec.md` ("The request log")
**Binding:** `docs/adr/0011-buyers-hand-off-requests-and-the-request-log.md` decision 3, ADR 0001

## What to build

Processed, Confirmed, Delivered and Cancel each add a history line to the request's log
entry. A cancelled request stays in the log, marked cancelled. The log still never holds a
stage — the stage lines are history text only.

1. In each of `lifecycle.handle_processed`, `lifecycle.handle_confirmation`,
   `lifecycle.handle_delivery` → their `on_success`, after the card is updated: find the entry
   with `store.find_id_by_thread(channel, thread_ts)` (ticket 76) and
   `store.append_history` the same history line the card got (e.g. `Processed by … on …`),
   through the ticket-76 helper `lifecycle._request_log`. No entry → do nothing.
2. `lifecycle.handle_cancel`, after a successful cancel: `append_history` the
   `Cancelled by … on …` line and `store.update(..., cancelled=True)`. Never `store.delete`.
3. The keyword path (`@Purchasing processed`) and the thread-card and DM-card buttons already
   converge on these functions, so no handler in `app` changes.

## Acceptance criteria

New test file `tests/test_77_request_log_stages_and_cancel.py`, fixtures as ticket 76 plus
`tests/test_69_cards_move_together.py`'s thread-card helpers.

- [ ] **Each stage appends one line.** Starting from a logged approved request, click Mark
  Processed, Mark Confirmed, Mark Delivered through the app handlers (feeding each
  `chat_update` back as `test_69` does): after each, the entry's last history line starts
  `Processed by`, then `Confirmed by`, then `Delivered to` respectively (the lines `handle_processed`, `handle_confirmation` and `handle_delivery` already append), and the entry has no
  `state`/`stage` key.
- [ ] **The DM card click logs the same line.** `dm_req_processed` through
  `app.handle_dm_stage_action` appends exactly one `Processed by` line (not two).
- [ ] **Cancel keeps the entry.** `handle_cancel` on a logged approved request: the entry still
  exists, `cancelled is True`, last history line starts `Cancelled by`.
- [ ] **A log failure never blocks.** With `store.append_history` raising, Mark Processed still
  calls `update_row` once and updates the thread card, and one admin-channel message contains
  `request log`.

**Tests may fake:** the Slack client, `log_writer` I/O. **Must be real:** `store` on the temp
`requests.json`, the lifecycle handlers, the app handlers.

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
