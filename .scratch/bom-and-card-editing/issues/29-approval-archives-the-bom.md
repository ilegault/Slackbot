# 29: Approval archives the BOM and the log points at it

**Status:** done

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

- [x] Approving a three-item request writes one row, saves `NNNN_<Vendor>_BOM.xlsx` into the configured BOMs folder, and the saved file's header names that row
- [x] The row's Notes cell reads `BOM: <filename> (N items)` — asserted by reading the workbook
- [x] The archived spreadsheet is uploaded into the thread
- [x] Approving a one-item request writes the row and produces no file, no Notes text and no upload
- [x] A spreadsheet save that raises leaves the row blank, no file behind, and the card not advanced — asserted on the workbook and on the absence of a card update
- [x] An approval whose items no longer total the request amount writes no row, creates no file, DMs the requester and posts in the thread
- [x] Approving a request with no items behaves exactly as it does today
- [x] The approved card's payload carries the archived file name
- [x] Every workbook write in this ticket goes through the existing write queue
- [x] `ruff check .`, `python scripts/check_tests_first.py` and `pytest -q` all pass

## Comments

### 2026-09-22 — Implemented and verified

1. **`lifecycle.finalize_purchase_request`**:
   - Accepts `items: list[dict] | None = None` and `shipping: float = 0.0`.
   - Before queueing write, verifies line items total matches request amount via `bom.check_total`. On mismatch, logs rejection, DMs requester, posts refusal to thread, and stops without queueing.
   - Inside the single queued `write_action` (invariant 2):
     - Appends the row in `Purchasing-Log.xlsx`.
     - When `bom.needs_bom(items)` is True, generates workbook with `Purchasing Log row NNNN` in header, saves to `BOMS_DIR/NNNN_<Vendor>_BOM.xlsx`, and updates `config.COLUMN_NOTES` ("Y") with `BOM: <filename> (<N> items)`.
     - All-or-nothing: if workbook build, save, or Notes update raises, calls `log_writer.blank_row(row_num)` and cleans up any partial file before re-raising.
   - On success callback:
     - Uploads archived BOM spreadsheet from disk to thread via `upload_archived_bom` (`files_upload_v2` / `files_upload`).
     - Adds `bom_file` to request payload on the approved card (in both button value and metadata).
     - Renders item count summary on the approved card when `needs_bom` is True.

2. **`lifecycle.handle_epif_processing`**:
   - Extracts `items` and `shipping` from message metadata via `slack_io.get_card_payload` (on button clicks) or thread card metadata lookup (on keyword approval).
   - Passes items to `finalize_purchase_request` on all paths (dropped EPIF, button payload, and modal metadata lookup).

3. **`slack_io.find_request_metadata_in_thread`**:
   - Preserves `items` and `shipping` on `parsed` return dict when present in message metadata.

4. **Testing (`tests/test_29_approval_archives_bom.py`)**:
   - 8 test cases covering 3-item approval with BOM archive & Notes, 1-item approval without BOM, 0-item approval, save failure rollback and card hold, items total mismatch refusal with DM and thread notice, write queue validation, button-path metadata extraction, and keyword-path metadata extraction.
   - Full gate passed: ruff, check_tests_first, and pytest (343 passed, 31 skipped).

