# 12: Denials are ephemeral and never replace anything

**What to build:** A refusal stops eating the thing it refused. When someone
clicks a button they are not allowed to click, they get a message only they can
see, and the request message stays exactly where it was for everyone else.

**Blocked by:** None (can start immediately)

**Status:** in-progress

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

- [ ] `slack_io.deny` exists with the signature above, passes
      `response_type="ephemeral"` and `replace_original=False`, and holds no client
- [ ] Every one of the fifteen `respond(text=…)` call sites in `src/app.py` now
      goes through `deny`
- [ ] A test parametrised over **every** button listener asserts that, for a user
      without the required role: the denial text is produced, `replace_original=False`
      was passed, the lifecycle handler was **not** called, and `chat_update` was
      **not** called. All four, every listener — not a sample
- [ ] A non-approver clicking Approve produces an ephemeral denial and
      `handle_epif_processing` is not called — asserted on the handler, not on a log line
- [ ] A test asserts the denial text names the role that can perform the action
- [ ] A source scan test fails if a bare `respond(text=…)` is added back to `src/app.py`
- [ ] `ruff check .`, `python scripts/check_tests_first.py` and `pytest -q` all pass

## Out of scope

- Removing `chat_update` from the listeners. That is ticket 13.
- The full four-audience `notify()` helper from
  `.scratch/lifecycle-and-buyers/spec.md` §3.7. This is the denial half only —
  the half that is losing messages in production.
- The `chat_postEphemeral` call in `handle_roster_set_name_submit`. Ticket 19.
- `src/store.py`. Still imported by nothing. Leave it alone.
