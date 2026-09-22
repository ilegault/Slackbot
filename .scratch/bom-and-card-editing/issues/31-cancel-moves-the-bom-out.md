# 31: Cancel moves the BOM out of the live folder

**Status:** ready-for-agent

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

- [ ] Cancelling an approved itemised request blanks its rows and moves its spreadsheet into `Cancelled/` inside the BOMs folder, keeping the file name
- [ ] The live BOMs folder no longer holds that file
- [ ] Cancelling a request with no spreadsheet behaves exactly as it does today
- [ ] A spreadsheet that is already missing leaves the cancellation successful, the rows blanked, and a logged warning
- [ ] Cancel is still refused after a request is processed, with no file moved — asserted on the absence
- [ ] The existing decline/cancel tests still pass untouched
- [ ] `ruff check .`, `python scripts/check_tests_first.py` and `pytest -q` all pass
