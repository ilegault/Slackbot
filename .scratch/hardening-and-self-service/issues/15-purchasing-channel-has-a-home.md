# 15: `PURCHASING_CHANNEL` is a constant with a home, and has no silent fallback

**What to build:** `/new-purchase` requests land in the purchasing channel, or
the bot says so loudly at startup. The silent fallback chain that filed them in
the alert channel — and then in the requester's own DM — is removed.

**Blocked by:** None (can start immediately, in parallel with 12–14)

**Status:** done

**Read before starting:** invariant 4 in `AGENTS.md` (every constant has one
home) and `docs/adr/0001-tests-first-and-no-muted-failures.md`, which is binding.

## Why

`src/lifecycle.py` reads `os.environ.get("PURCHASING_CHANNEL")` inline. The name
appears in no other file, is not in `config.py`, and is unchecked at startup.
When it is unset, the code falls back to `config.ADMIN_ALERT_CHANNEL`, and then
to DMing the requester.

Isaac has since set the variable in the production server's `.env`, so the
symptom should be gone — but the fallback is still there, and a wrong channel is
worse than a loud failure. Nobody acts on a request they cannot see, and nobody
notices a request arrived in the wrong room.

## Requirements, stated as requirements

1. **Add `config.PURCHASING_CHANNEL`** beside `ADMIN_ALERT_CHANNEL`, read from
   the environment in `config.py` like every other constant. `lifecycle.py` reads
   it from `config`.

2. **Remove the fallback chain entirely.** No `ADMIN_ALERT_CHANNEL` fallback, no
   DM fallback.

3. **Unset is an operator-facing startup error.** Log it through
   `path_validator`'s existing operator-facing check, and refuse to post purchase
   requests. A missing setting must be loud.

4. **A source scan asserts `os.environ` is read nowhere in `src/` except
   `config.py`.** An AST scan, modelled on
   `tests/test_regression_guards.py::test_only_log_writer_opens_workbook_path`.

5. **No ticket touches the server.** Deploying is a human step: Isaac merges to
   `master`, then runs `@Purchasing update`.

## Acceptance criteria

- [x] `config.PURCHASING_CHANNEL` exists and is the only place the variable is read
- [x] A test asserts a `/new-purchase` submission posts to
      `config.PURCHASING_CHANNEL` — asserted on the channel argument reaching the
      client, for a value that is **not** `ADMIN_ALERT_CHANNEL`
- [x] With `PURCHASING_CHANNEL` unset, a test asserts the startup check reports the
      error **and** that no purchase request is posted to `ADMIN_ALERT_CHANNEL` or
      to the requester's DM — assert on the absence of both
- [x] An AST scan test asserts `os.environ` is read nowhere in `src/` outside
      `config.py`, and fails if a new inline read is added
- [x] `ruff check .`, `python scripts/check_tests_first.py` and `pytest -q` all pass

## Out of scope

- Any other environment variable's home. If the scan turns up a second inline
  read, note it in `## Comments` — do not widen the ticket.
- Changes to `path_validator`'s own behaviour beyond adding this check.
- Anything on the production server.

## Comments

### 2026-09-16 — Implementation notes (Ticket 15)

1. **`config.PURCHASING_CHANNEL` added**: Read from environment in `src/config.py` beside `ADMIN_ALERT_CHANNEL`.
2. **Fallback chain removed**: In `src/lifecycle.py`, `post_channel = config.PURCHASING_CHANNEL`. If empty, the bot logs an error and refuses to post the request, preventing silent fallback to `ADMIN_ALERT_CHANNEL` or DMing the requester.
3. **Startup check**: Added `path_validator.check_purchasing_channel()` and hooked it into `path_validator.validate_and_configure()` as well as `src/app.py:main()`. Also added check to `scripts/verify_setup.py`.
4. **Tests added**:
   - `tests/test_15_purchasing_channel.py` covers constant existence, positive posting to `config.PURCHASING_CHANNEL` (and not `ADMIN_ALERT_CHANNEL`), unset refusal with absence assertions for both alerts and DM, and AST scan.
   - `tests/test_regression_guards.py` added Guard 10 (`test_os_environ_read_nowhere_outside_config`).
5. **Inline environment variable scan (Out of Scope note)**:
   The AST scan across `src/` identified existing grandfathered reads:
   - `src/app.py`: `SLACK_BOT_TOKEN`, `SLACK_APP_TOKEN`
   - `src/slack_io.py`: `SLACK_BOT_TOKEN`
   - `src/path_validator.py`: `USERNAME` (via `os.getenv`), and `os.environ[k] = v` write-back
   Per Ticket 15 out-of-scope guidance, these are noted here and not migrated to avoid widening the ticket. No new inline reads outside `config.py` are permitted.
6. **Local gate**: `ruff check .`, `python scripts/check_tests_first.py` and `pytest -q` all pass (174 passed, 31 skipped, 0 failures).

