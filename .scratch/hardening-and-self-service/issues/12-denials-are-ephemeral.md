# 12: Denials are ephemeral and never replace anything

**What to build:** A refusal stops eating the thing it refused. When someone
clicks a button they are not allowed to click, they get a message only they can
see, and the request message stays exactly where it was for everyone else.

**Blocked by:** None (can start immediately)

**Status:** done

**Read before starting:** `CONTEXT.md` for the vocabulary,
`docs/adr/0001-tests-first-and-no-muted-failures.md` (binding), and invariant 5
in `AGENTS.md` — this ticket keeps `respond(...)` as the denial channel and does
not move anything onto `chat.postEphemeral`.

## Why

A lab member posts a purchase request. Somebody who is not Charlie clicks
Approve. The request message **disappears** — replaced by a padlock line only
that person can see. The requester is never told. There is nothing left in the
channel to click. The purchase goes dark.

This has been observed in the lab. The cause is one line that was never written:
a block action's reply through `response_url` **replaces the message it was
clicked on** unless told otherwise. `replace_original` and `response_type` appear
nowhere in `src/` today, and there are exactly **15** bare `respond(text=…)`
calls waiting to do this again.

This ticket and ticket 13 together are worth deploying on their own.

## Requirements, stated as requirements

1. **One helper, in `slack_io`.** Add:

   ```python
   def deny(respond, text: str) -> None:
       """Reply privately to whoever acted, leaving the original message intact."""
   ```

   It calls `respond(text=…, response_type="ephemeral", replace_original=False)`
   and nothing else. It holds no Slack client and makes no API call, so it stays
   inside `slack_io`'s remit under the layering rule.

2. **Every refusal path in `src/app.py` goes through it.** That is all fifteen
   current `respond(text=…)` call sites: the eleven padlock denials, the
   unassigned-request warning on `req_processed`, and the three non-denial
   informational replies. The informational ones get the same treatment for the
   same reason — an FYI that deletes the request is still deleting the request.

3. **The refusal says which role can do the thing.** Wording is not invented per
   call site: a denial names the action and the role that holds it, so the reader
   knows who to ask. Keep the existing padlock prefix.

4. **A source scan makes a sixteenth impossible.** Add a test asserting that no
   bare `respond(text=…)` remains in `src/app.py` — every `respond` call in the
   listener layer either goes through `slack_io.deny` or passes
   `replace_original` explicitly. Model it on
   `tests/test_regression_guards.py::test_only_log_writer_opens_workbook_path`.

5. **The `chat_postEphemeral` guard test is updated, not weakened.** Invariant 5
   permits exactly one `chat_postEphemeral` call site today, in
   `handle_roster_set_name_submit`. Ticket 19 rewrites that path and removes it.
   This ticket leaves the call site alone and leaves the guard asserting one.

## Acceptance criteria

- [x] `slack_io.deny` exists with the signature above, passes
      `response_type="ephemeral"` and `replace_original=False`, and holds no client
- [x] Every one of the fifteen `respond(text=…)` call sites in `src/app.py` now
      goes through `deny`
- [x] A test parametrised over **every** button listener asserts that, for a user
      without the required role: the denial text is produced, `replace_original=False`
      was passed, the lifecycle handler was **not** called, and `chat_update` was
      **not** called. All four, every listener — not a sample
- [x] A non-approver clicking Approve produces an ephemeral denial and
      `handle_epif_processing` is not called — asserted on the handler, not on a log line
- [x] A test asserts the denial text names the role that can perform the action
- [x] A source scan test fails if a bare `respond(text=…)` is added back to `src/app.py`
- [x] `ruff check .`, `python scripts/check_tests_first.py` and `pytest -q` all pass

## Out of scope

- Removing `chat_update` from the listeners. That is ticket 13.
- The full four-audience `notify()` helper from
  `.scratch/lifecycle-and-buyers/spec.md` §3.7. This is the denial half only —
  the half that is losing messages in production.
- The `chat_postEphemeral` call in `handle_roster_set_name_submit`. Ticket 19.
- `src/store.py`. Still imported by nothing. Leave it alone.

## Comments

### 2026-09-16

- Implemented `slack_io.deny(respond, text: str) -> None`:
  - Enforces `response_type="ephemeral"` and `replace_original=False` on `respond()`.
  - Holds no Slack client and executes no API calls, preserving downward layering.
  - Documented rationale in `src/slack_io.py` module docstring.
- Updated all 15 `respond(...)` call sites in `src/app.py` to route through `slack_io.deny`:
  - 2 slash command informational responses (`/purchasing-help`, `/roster-list`).
  - 3 admin alerts approvals (`approve_new_requester`, `approve_new_admin`, `approve_new_vendor`).
  - 1 purchase request approval button (`req_approve`).
  - 3 processed button checks (unassigned request warning, unauthorized user, unregistered requester).
  - 1 decline button check (`req_decline`).
  - 1 cancel button check (`req_cancel`).
  - 2 confirmation button checks (unauthorized user, unregistered requester).
  - 2 delivery button checks (unauthorized user, unregistered requester).
- Tests:
  - Added `tests/test_12_denials.py` containing 20 tests:
    - Verifies `slack_io.deny` signature and behaviour.
    - Parametrized tests covering all 13 button denial scenarios asserting denial text role naming, `replace_original=False`, `response_type='ephemeral'`, `chat_update` not called, and target handlers not called.
    - Specific test asserting `lifecycle.handle_epif_processing` is not called on non-approver click.
    - AST source scan asserting all 15 calls in `src/app.py` route through `deny` and detecting any bare `respond(...)` call.
    - Slash commands `/purchasing-help` and `/roster-list` verify `replace_original=False`.
  - Added AST invariant `test_no_bare_respond_in_app` to `tests/test_regression_guards.py`.
  - Strengthened `test_permission_denial_*` in `tests/test_regression_guards.py` to assert `replace_original=False` and `response_type="ephemeral"`, and added `mock_handle_epif.assert_not_called()`.
- Verified test gate:
  - `ruff check .` passed with no errors.
  - `python scripts/check_tests_first.py` passed.
  - `pytest -q` passed with 190 passed, 31 skipped.

