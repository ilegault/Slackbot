# 127: Uploads to the buyer's DM retry before alerting

**Status:** done

**Runner:** any

**Auto-merge:** yes

**Blocked by:** None (can start immediately)

**Spec:** `.scratch/bom-template-and-epif-date/spec.md` (Part C, stories 21–22)
**Binding:** `docs/adr/0001-tests-first-and-no-muted-failures.md`
**Glossary:** `CONTEXT.md` — **DM card**, **Filled EPIF**

## What to build

On 2026-10-13 a Filled EPIF upload to the assigned buyer's DM failed with "The read operation
timed out". The admin was alerted, but the buyer never got the EPIF.

Each DM upload must be tried up to three times before the admin alert is posted. A timed-out
upload may in fact have landed, so a duplicate file in the DM is acceptable.

1. **`config`**: `DM_UPLOAD_ATTEMPTS = 3`, `DM_UPLOAD_WAITS = (2.0, 5.0)` (seconds before
   attempts 2 and 3).
2. **`lifecycle`** — extract the per-file upload block inside `_send_assignee_dm` (the
   `files_upload_v2` / `files_upload` try and the admin alert) into one function:
   `_upload_to_dm(client, dm_channel, path, fname, assignee_id, assignee_name) -> bool`.
   - It loops over the attempts, sleeping through a module-level `_sleep = time.sleep` so
     tests can replace it.
   - It logs each failed attempt at WARNING.
   - It alerts the admin with the existing text only after the last attempt fails.
   - `_send_assignee_dm` calls it for every file. Ticket 128 and ticket 125's handler use it
     too: one implementation.
   - Remove the `files_upload` fallback branch's passing of both `file=` and `content=`
     (Slack rejects that combination: "You cannot specify both the file and the content
     argument", seen in production 2026-10-05). Pass `content` only.

## Acceptance criteria

- [x] `test_dm_upload_retries_then_succeeds`:
  - A fake client's `files_upload_v2` raises `TimeoutError("The read operation timed out")` twice, then returns `{"ok": True}`.
  - `_send_assignee_dm` with one EPIF file results in three calls, one success, and **no** `chat_postMessage` to `config.ADMIN_ALERT_CHANNEL`.
  - `_sleep` is replaced with a recorder showing waits `[2.0, 5.0]`.
- [x] In the same function `test_dm_upload_retries_then_succeeds`, a fake that raises three times produces exactly one admin alert containing `Failed to attach` and the file name.
- [x] The existing DM tests in `tests/test_46_epif_path_dm_attaches_epif.py`, `tests/test_30_buyers_dm_carries_bom.py` and `tests/test_112_uploads_and_dm_log.py` pass unchanged. (no test: the full suite in the gate proves it)

May fake: the Slack client and `_sleep`. Must be real: `_send_assignee_dm` and the new helper, with files on disk in a temp directory.

## Gate

Run all four, in CI's order, and all must pass:

    ruff check .
    python scripts/check_tests_first.py
    python tools/type_gate.py
    pytest --tb=short -q -n auto --dist loadfile

Tests need `SLACK_BOT_TOKEN=xoxb-test-not-a-real-token`, `SLACK_APP_TOKEN=xapp-test-not-a-real-token` and `PYTHONUTF8=1` in the environment, as `.github/workflows/tests.yml` sets.

The gate holds a PR that adds a new test which already passes on today's code. Where a ticket says checks share one test function, keep them together so the function fails on the base commit.

## Comments

2026-10-15: Done. `lifecycle._upload_to_dm` (3 attempts, waits 2.0 and 5.0 s via `_sleep`, one admin alert after the last failure) is the one DM upload; `_send_assignee_dm` and `handle_change_epif_date` call it. The `files_upload` fallback now sends `content` only. Tests: `tests/test_127_dm_upload_retry.py`.

For the developer: `test_bom_dm_upload_failure_leaves_approval_intact` (test_30) could not pass unchanged. Its fake failed the DM upload only once, which the retry now (correctly) recovers from, so no alert was posted. Its input was changed to a BOM upload that fails on every attempt, which keeps the test's intent (failed attach -> one admin alert, approval intact) and still goes red if the alert or the approval handling breaks.
