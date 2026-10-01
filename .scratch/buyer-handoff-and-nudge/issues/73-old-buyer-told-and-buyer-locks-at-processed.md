# 73: The old buyer is told, and the buyer locks at Processed

**Status:** done

**Runner:** any

**Auto-merge:** yes

**Blocked by:** 72

**Spec:** `.scratch/buyer-handoff-and-nudge/spec.md` (Hand-off; "Stage cutoff", "Old buyer DM")
**Binding:** `docs/adr/0011-buyers-hand-off-requests-and-the-request-log.md` decision 1, ADR 0001

## What to build

When a request moves from one buyer to another, the old buyer gets a new DM telling them who
has it and who moved it (a card edit alone does not notify in Slack). Once a request is
Processed, its buyer can no longer change: the picker is already absent (ticket 72) and any
assign attempt — picker or typed keyword — is refused publicly in the thread.

1. `lifecycle.handle_assign`: on a reassignment (there was a `current_assignee` and it differs
   from the target), after the old DM card is retired, send one `chat_postMessage` to the old
   assignee's Slack ID with text
   `↪️ <item> was moved to <new buyer name> by <actor name>. You don't need to do anything on it.`
   where `<item>` is the request's item description (as `blocks.build_dm_card_blocks` reads it).
   A failure to send is logged and never stops the assignment.
2. `lifecycle.handle_assign`: when `current_state` is `processed`, `confirmed` or `delivered`,
   refuse before any permission or target check, via `say` in the thread (public, so everyone
   sees why nothing changed), with
   `🔒 Already <line> — the buyer can't change after this point.`
   where `<line>` is the last history entry beginning `Processed by` (the line
   `handle_processed` appends, e.g. `Processed by Dylan on 09/24/26 14:02`), or `Processed`
   when no such line exists. Nothing else happens: no `chat_update`, no DM.

## Acceptance criteria

New test file `tests/test_73_old_buyer_told_and_processed_lock.py`, fixtures as ticket 72.

- [x] **The old buyer gets a DM.** Approver moves an `approved` request from buyer A to buyer B via
  `app.handle_req_assign_select_action`: exactly one `chat_postMessage` whose `channel` is
  `U_A` and whose text contains `was moved to` and buyer B's roster name and the approver's
  roster name.
- [x] **A first assignment sends no "moved" DM.** Assigning an unassigned approved request: no
  `chat_postMessage` text contains `was moved to`.
- [x] **The picker on a Processed card is refused.** A card in state `processed` with history
  `["Approved by …", "Processed by Dylan on 09/24/26 14:02"]`: a picker click posts one thread
  message containing `Already Processed by Dylan on 09/24/26 14:02` and there is no
  `chat_update` and no DM.
- [x] **The typed keyword on a Processed request is refused the same way** (through
  `app.dispatch_command` with `assign @B`), for each of `processed`, `confirmed`, `delivered`.
- [x] **A failed old-buyer DM never blocks.** With `chat_postMessage` raising only for
  `channel == "U_A"`, the thread card is still updated to buyer B and buyer B's DM card is posted.

**Tests may fake:** the Slack client. **Must be real:** `lifecycle.handle_assign`, the app handlers,
the roster on a temp file.

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

Landed on 2026-09-30:
- `lifecycle.handle_assign`: notifies old buyer via DM on reassignment (`↪️ <item> was moved to <new buyer> by <actor>. You don't need to do anything on it.`), catching failures non-blockingly.
- `lifecycle.handle_assign`: locks assignment once request state is `processed`, `confirmed`, or `delivered`, refusing via in-thread message `🔒 Already <line> — the buyer can't change after this point.` before any permission or target checks.
- Docstrings updated in `lifecycle.py` and `handle_assign`.
- Tests added in `tests/test_73_old_buyer_told_and_processed_lock.py` covering all 5 criteria.
