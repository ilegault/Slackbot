# 57: A missing storage location during approval is reported and leaves no row

**Status:** in-progress

**Runner:** any

**Auto-merge:** yes

**Blocked by:** 56

**Spec:** `.scratch/commands-paths-and-name/spec.md`
**Binding:** `docs/adr/0009-keywords-storage-settings-and-the-bot-name.md` decision 6, ADR 0001

## What to build

Approval (`lifecycle.finalize_purchase_request` — its inner `write_action` /
`on_failure` pair) appends the row, saves the
EPIF, saves the BOM and writes Notes as **one all-or-nothing task**; on any failure it
blanks the row it just wrote and removes the BOM. That rule stays exactly as is. Today
`on_failure` posts `Error saving/logging purchase request: <error>`, which for a moved
folder is a raw Python message.

1. `on_failure` in the approval path: when the error is a
   `log_writer.StorageLocationError` (ticket 56), `say` in the thread
   `text_rules.storage_problem_message(err.setting, err.path, err.reason)`. Other errors
   keep today's text.
2. The same for the workbook write when `PURCHASING_LOG_PATH` is not set or missing
   (`StorageLocationError` from `log_writer`, per ticket 56) — the message names
   `PURCHASING_LOG_PATH`.
3. The same `on_failure` handling for the stage-update writes that share this pattern
   (the `on_failure` that posts `Error updating Order Log for row …`).
4. Confirm `queue_worker`'s non-lock branch passes the original exception object to
   `failure_callback` (it does today) — do not change `queue_worker`.

## Acceptance criteria

- [ ] **EPIF folder missing at approval.** In `tests/test_57_approval_storage_problems.py`,
  on a temp copy of a real workbook fixture, drive an approval of a PDF-born request with
  `EPIFS_DIR` pointing at a missing folder (copy the setup of an existing approval test in
  `tests/test_45_epif_approval_archives.py`). Assert: one thread reply containing
  `EPIFS_DIR` and the path; the row that was appended is blank afterward (read the temp
  workbook); the EPIFs folder still does not exist.
- [ ] **BOM folder missing at approval.** A request with two or more line items and
  `BOMS_DIR` missing: thread reply names `BOMS_DIR`; row blank afterward; no BOM file
  anywhere under the temp tree.
- [ ] **Workbook not set.** `WORKBOOK_PATH` empty: the reply names `PURCHASING_LOG_PATH`
  and nothing is written to any temp folder.
- [ ] **A non-storage error keeps its old text**: force `log_writer.append_row` to raise
  `ValueError("boom")`; the reply still starts `Error saving/logging purchase request`.
- [ ] Only the Slack client and the file download are faked; the workbook write is real,
  on the temp copy.

## Gate

Run in this order, exactly as CI does. Zero failures before you push.

```
ruff check .
python scripts/check_tests_first.py
pytest -q --tb=short --durations=25
```

## Comments

