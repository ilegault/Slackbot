# 06: Regression guards for the whole lifecycle surface

**What to build:** The tests that were never written for T1–T4, plus the
cross-cutting guards that no single ticket in this set owns.

**Blocked by:** 02, 03, 04, 05

**Status:** done

`docs/adr/0001-tests-first-and-no-muted-failures.md` is binding, and this ticket is
the one place where it is being applied retroactively: T1–T4 shipped before the
tests-first rule existed. Every ticket after this one carries its own tests.

## Why

Four behavioural changes shipped with no guards. The `channel_not_found` bug is
the shape of what that costs: the handler ran, built its text correctly, and failed
at the last step, and nothing caught it because nothing asserted that a command
actually replies.

## Requirements

- **Behaviour, not shape.** A test that breaks on a rename but not on a wrong Excel
  column is testing the wrong thing.
- **Assert on absence where absence is the point.** That no DM was sent, that
  `chat_update` was not called, that no alert was posted, that the row is
  unchanged. A permission test that only checks the denial text passes when the
  action also went through.
- **Find the real Bolt listener registry.** Do not monkeypatch something that
  always passes. If the registry cannot be reached, that is an escalation, not a
  reason to assert on a stand-in.
- Existing fake-client style. Nothing touches the real workbook, the real roster,
  or the network.

## Acceptance criteria

- [x] All five slash commands are registered — asserted against Bolt's real
      listener registry
- [x] **No slash-command handler calls `chat_postEphemeral`** — assert the fake
      client's `chat_postEphemeral` was never called. This is the T1 guard
- [x] Exactly one `chat_postEphemeral` call site remains in `src/`, on the
      message-event path, and a test pins that count
- [x] Every command acks before any client call
- [x] The `log_request` middleware produces a start record and a completion record,
      and a handler that raises still produces the completion record plus the
      exception. This is the T2 guard
- [x] A request through the middleware taking over 2 000 ms is logged at WARNING
- [x] `build_request_blocks` returns exactly one next-step button per non-final
      state and none for `delivered`, with the expected `action_id`
- [x] Every lifecycle button's permission denial leaves the message unchanged and
      writes nothing — one test per button, not one test for the set
- [x] `/roster-set-name` with a name outside `VALID_REQUESTERS` returns a modal
      error and posts **no** alert
- [x] A test asserts no module under `src/` other than the root entry point imports
      `app` — the layering guard from ticket 01, kept
- [x] A test asserts `log_writer` is the only module that opens `WORKBOOK_PATH`
- [x] `ruff check .`, `python scripts/check_tests_first.py` and `pytest -q` all pass
      with **zero** failures

## Comments

- 2026-09-16: Implemented comprehensive regression guard suite in `tests/test_regression_guards.py`.
  - Introspects Bolt's real listener registry (`app.app._listeners`) to ensure all 5 slash commands are registered.
  - Verifies all 5 slash command handlers call `ack()` strictly prior to any client operations and never call `chat_postEphemeral`.
  - AST check pins exactly 1 `chat_postEphemeral` call site across all of `src/` (in `src/app.py` line 329 on view/message submission path).
  - Verifies `log_request` middleware start, completion, and exception records, and tests WARNING emission for requests > 2000 ms.
  - Verifies `build_request_blocks` returns exactly one primary next-step button for all non-final states (`posted`, `approved`, `claimed`, `processed`, `confirmed`) and zero buttons for `delivered`.
  - Adds 7 distinct permission denial tests (one per button: `req_approve`, `req_claim`, `req_processed`, `req_confirmed`, `req_delivered`, `req_decline`, `req_cancel`), confirming `chat_update` is not called, no writes occur, and ephemeral responses are sent.
  - Confirms `/roster-set-name` returns modal validation error and posts zero alerts for unlisted names.
  - Confirms downward layering invariant (no module in `src/` imports `app`).
  - Confirms only `log_writer.py` opens `WORKBOOK_PATH` via `zipfile.ZipFile`.
  - Full test suite passing cleanly (118 passed, 31 skipped).
