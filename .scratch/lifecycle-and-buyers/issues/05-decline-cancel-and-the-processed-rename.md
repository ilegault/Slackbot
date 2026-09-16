# 05: Decline, Cancel, and the `processed` rename

**What to build:** Two new actions — Decline (pre-approval) and Cancel
(post-approval, before processing) — plus the one-shot rename of `submitted` to
`processed` across every surface.

**Blocked by:** 01

**Status:** done

**Read `docs/adr/0003-decline-and-cancel.md` before anything in this ticket**, and
`docs/adr/0002-request-lifecycle-and-surfaces.md` decision 4 for the rename.
`docs/adr/0001-tests-first-and-no-muted-failures.md` is binding.

## Why

There is no way to say no. A request Charlie does not want sits on the channel with
an Approve button forever, and an approved purchase that turns out to be wrong
stays in `Purchasing-Log.xlsx` as a live row with nothing marking it dead.

The rename rides along because both new actions add user-facing strings naming a
stage, and adding them under the old word would mean renaming them again a ticket
later.

## Requirements, stated as requirements

1. **Neither action takes a reason.** No modal, no justification field, no
   follow-up question. One click. An approver who has to explain themselves
   declines less, and a request nobody declines sits there misleading people.
2. **Decline is not logged.** No Excel row exists yet, no alert is posted, no audit
   entry is written. The message updates to show it was declined and by whom. That
   is the whole record.
3. **Cancel blanks the Excel row.** It does not mark it, strike it, or write
   "CANCELLED" anywhere in the workbook. The workbook is a log of live approved
   purchases and their stage, nothing else. A blanked row may be recycled — the
   cancellation is visible as text in the thread, and that is the record.
4. **Cancel is refused once a request is `processed`**, and refused *loudly*: the
   bot says clearly in-thread that the request has already gone to the purchasing
   team and cannot be cancelled here. Not a silent no-op, not a generic error.
5. **A batch cancels as a batch.** A request carrying multiple EPIFs is cancelled
   in one action and every row it wrote is blanked. No per-item control.
6. **The blank goes through the lock queue**, like every other workbook write.
   Nothing opens `Purchasing-Log.xlsx` outside `log_writer` + `queue_worker`.
7. **The rename is total and happens in this ticket only.** Every occurrence, at
   the same time: the action id, the button label, the history line, the help text,
   the App Home definitions, the `@p-bot` keyword alias, the test names, and the
   internal function name. `grep -rin "submitted" src/ tests/` returns nothing
   afterwards except an intentional backwards-compatible alias, if one is kept.

## Acceptance criteria

### Decline
- [x] The `posted` state renders a **Decline** button alongside Approve
- [x] Decline is restricted to approvers; a non-approver gets an ephemeral denial
      and the message is unchanged
- [x] Declining updates the message to show it was declined and by whom, and
      removes every action button
- [x] Declining writes nothing to Excel, posts no alert, and DMs nobody
- [x] A test asserts a decline writes no Excel row and posts no alert

### Cancel
- [x] The `approved` and `claimed` states render a **Cancel** button alongside the
      next-step button; `processed`, `confirmed` and `delivered` do not
- [x] Cancel is permitted to approvers **and** admins, and refused to buyers
- [x] `log_writer` gains a blank-row operation that clears every writable cell in
      the row, leaving the read-only columns (A, Z) alone, and it goes through the
      lock queue
- [x] Cancelling a request blanks its row and updates the message to show it was
      cancelled and by whom
- [x] Cancelling a **batch** blanks every row that request wrote
- [x] A cancel attempted on a `processed` request is refused with an explicit
      in-thread message naming the reason, and the row is untouched
- [x] A test asserts the blanked row's writable cells are empty and columns A and Z
      are unchanged
- [x] A test asserts a cancel after `processed` writes nothing and produces the
      refusal message — assert on the row being untouched, not only on the text
- [x] A test asserts a buyer's cancel click is refused
- [x] A test asserts a multi-EPIF cancel blanks every row, not just the first

### The rename
- [x] `grep -rin "submitted" src/ tests/` returns nothing but an intentional,
      commented alias
- [x] The button reads **Mark Processed**; the action id is `req_processed`
- [x] `@p-bot processed` works; `@p-bot submitted` still works as a silent alias
      and is taught nowhere
- [x] Help text, App Home and the channel post all use **processed**
- [x] App Home carries a definitions section stating the four stages plainly, and
      does **not** link the Purchasing Log

- [x] `ruff check .`, `python scripts/check_tests_first.py` and `pytest -q` all pass

## Comments

2026-09-16 — Implemented by agent session.

**Decline**: `handle_decline` added to `lifecycle.py` — updates message to "declined" state (no buttons), no workbook write. `@app.action("req_decline")` listener in `app.py` checks `is_approved_reviewer`. `posted` state block renders Approve + Decline.

**Cancel**: `handle_cancel` added to `lifecycle.py` — checks `_CANCEL_REFUSED_STATES` (processed/confirmed/delivered), finds all rows via `find_all_rows_in_thread` (new in `slack_io.py`), blanks each via queue_worker. `@app.action("req_cancel")` checks `is_approved_reviewer or is_admin_user`. `approved` and `claimed` states render primary button + Cancel. `log_writer.blank_row` was already present.

**The rename**: `SUBMIT_KEYWORDS` → `PROCESSED_KEYWORDS` in config.py ("submitted"/"submit" kept as silent aliases). Button label "Mark Submitted" → "Mark Processed", action id `req_submitted` → `req_processed`, handler renamed, state name "submitted" → "processed" throughout. `handle_submission` → `handle_processed`. App Home gains definitions section (Approved/Processed/Confirmed/Delivered). All 19 previous occurrences of "submitted" in src/ cleared; 2 intentional backwards-compat aliases remain.

**Tests**: 5 new tests in `tests/test_05_decline_cancel.py`. Existing tests in `test_onboarding_and_commands.py` updated to match new action IDs and button counts. Gate: 101 passed, 31 skipped, 0 failures. `ruff check .` clean.
