# 31: Cancel moves the BOM out of the live folder

**Status:** done

**Blocked by:** 29

**Spec:** `.scratch/bom-and-card-editing/spec.md` decision 5
**Binding:** `docs/adr/0003-decline-and-cancel.md`, `docs/adr/0006-...` decision 7

## What to build

Cancelling an approved request already un-writes its row, because the workbook is
a log of live approved purchases and nothing else. Its spreadsheet should follow:
the archived BOM moves into a `Cancelled/` folder inside the BOMs folder, keeping
its row-numbered name. The live folder then matches the live log, and a recycled
row number can never collide with a stale sheet.

## Notes

- Cancel's existing behaviour does not change in any other way. Who may cancel,
  when it is refused, and the blanking of the rows are all as ADR 0003 has them.
- A missing file is logged, not raised. **The cancellation still completes** — a
  file that was never saved must not leave a cancelled purchase sitting in the
  log.

## Acceptance criteria

- [x] Cancelling an approved itemised request blanks its rows and moves its spreadsheet into `Cancelled/` inside the BOMs folder, keeping the file name
- [x] The live BOMs folder no longer holds that file
- [x] Cancelling a request with no spreadsheet behaves exactly as it does today
- [x] A spreadsheet that is already missing leaves the cancellation successful, the rows blanked, and a logged warning
- [x] Cancel is still refused after a request is processed, with no file moved — asserted on the absence
- [x] The existing decline/cancel tests still pass untouched
- [x] `ruff check .`, `python scripts/check_tests_first.py` and `pytest -q` all pass

## Comments

2026-09-22 — Implemented by agent.

**What was built:**
- Added `_move_bom_to_cancelled(bom_fname)` helper in `src/lifecycle.py` (just before `handle_cancel`).
  It moves `BOMS_DIR/<name>` → `BOMS_DIR/Cancelled/<name>`, creating `Cancelled/` if needed.
  A missing file logs a warning at WARNING level and returns normally.
- `handle_cancel` now reads `req_data.get("bom_file")` and calls `_move_bom_to_cancelled` inside
  the same queued write task as the row blanking (rows-present path), and inline on the no-rows
  path (belt-and-suspenders; in practice a BOM can't exist without a logged row).
- Added `import shutil` to `lifecycle.py`.
- Docstring updated with Per Ticket 31 section.

**Tests (8, all passing):**
- BOM moves to `Cancelled/` and disappears from the live folder.
- Filename is preserved after the move.
- No BOM on request: rows blanked, no `Cancelled/` created.
- Missing BOM: cancel succeeds, row blanked, WARNING log contains the filename.
- Missing BOM: `Cancelled/` dir not created.
- `state=processed`: cancel refused, BOM not moved, `Cancelled/` not created.
- `state=confirmed`/`delivered`: same.

Gate: `ruff check .` ✓, `check_tests_first.py` ✓, `pytest -q` 359 passed 31 skipped ✓.
