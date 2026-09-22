# 29: Approval archives the BOM and the log points at it

**Status:** ready-for-agent

**Blocked by:** 27

**Spec:** `.scratch/bom-and-card-editing/spec.md` decision 4
**Binding:** `docs/adr/0006-bom-line-items-and-editable-posted-cards.md` decisions 4, 6, 7; AGENTS.md invariant 2

## What to build

Charlie approves an itemised request. The bot writes the row as it does today,
then saves the spreadsheet as `0018_Ruland_BOM.xlsx` in the BOMs folder — the
number being the Purchasing Log row it belongs to — writes
`BOM: 0018_Ruland_BOM.xlsx (5 items)` into that row's Notes column, and uploads
the archived file into the thread. Anyone reading the log can see an itemised
sheet exists and which one; anyone in the BOMs folder can find the row.

A request whose items no longer add up cannot be approved at all: nothing is
written, the requester is told, and the thread says so.

## Notes

- Both approval paths already converge on one finalize function. Items reach it
  from the clicked card's metadata on the button path, and from the thread's
  metadata lookup on the keyword path. Known limitation, unchanged by this
  ticket: the keyword path finds the newest card in the thread.
- The row append, the spreadsheet save and the Notes write all happen **inside the
  single queued write task** (invariant 2 — nothing else opens the workbook).
- **All-or-nothing is a requirement:** if building or saving the spreadsheet or
  writing the Notes cell raises, the task blanks the row it just wrote before
  re-raising. A row in the log with no sheet behind it is the failure this ticket
  exists to prevent.
- The Notes column is referenced by its constant, never the literal `"Y"`.
- A one-item request writes its row exactly as today: no file, no Notes, no
  upload.
- The approved card's payload records the archived file name — short enough to
  ride in the button value — so tickets 30 and 31 can find it.

## Acceptance criteria

- [ ] Approving a three-item request writes one row, saves `NNNN_<Vendor>_BOM.xlsx` into the configured BOMs folder, and the saved file's header names that row
- [ ] The row's Notes cell reads `BOM: <filename> (N items)` — asserted by reading the workbook
- [ ] The archived spreadsheet is uploaded into the thread
- [ ] Approving a one-item request writes the row and produces no file, no Notes text and no upload
- [ ] A spreadsheet save that raises leaves the row blank, no file behind, and the card not advanced — asserted on the workbook and on the absence of a card update
- [ ] An approval whose items no longer total the request amount writes no row, creates no file, DMs the requester and posts in the thread
- [ ] Approving a request with no items behaves exactly as it does today
- [ ] The approved card's payload carries the archived file name
- [ ] Every workbook write in this ticket goes through the existing write queue
- [ ] `ruff check .`, `python scripts/check_tests_first.py` and `pytest -q` all pass
