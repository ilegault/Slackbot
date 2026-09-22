# 26: Line items, the BOM workbook, and the BOMs folder

**Status:** done

**Blocked by:** None (can start immediately)

**Spec:** `.scratch/bom-and-card-editing/spec.md` decisions 1 and 2
**Binding:** `docs/adr/0006-bom-line-items-and-editable-posted-cards.md`, `CONTEXT.md` (**Line item**, **BOM**), `docs/adr/0001-tests-first-and-no-muted-failures.md`

## What to build

The bot can turn a pasted list of line items into a real BOM spreadsheet, and it
knows where BOMs are kept. Nothing in Slack changes yet: this is the machinery
tickets 27 onward hang off.

A lab member's paste — one item per line, `qty | name | part # | unit price | link | description`,
or the same fields tab-separated as they come out of Excel — becomes a list of
line items plus an optional shipping amount, or a list of errors naming the line
that is wrong. Two or more items can be written out as an `.xlsx` a buyer could
forward to purchasing today: header block, one row per item, shipping and total.

A new `BOMS_DIR` storage path joins the Purchasing Log, EPIFs, Confirmations and
Quotes, so a missing or misconfigured folder is named in the startup alert
instead of blowing up at the first approval.

## Notes

- The parser, the formatter, the total check and the change description are **pure
  functions in the domain layer** with no Slack and no file I/O — this is a
  requirement, not a preference, because they are what the tests drive directly.
  Add the new module to the domain list in the layering test.
- Building the workbook returns **bytes**; writing them to disk is a separate
  storage function that mirrors `save_epif`'s atomic temp-file-then-replace.
- `openpyxl` is correct here. The hazard in `log_writer`'s docstring is about
  editing `Purchasing-Log.xlsx` in place, and does not apply to a brand-new file.
- Totals in the sheet are **written as numbers, not formulas**.
- The line numbers in error messages count every line of the pasted text,
  including blanks, so they match what the user sees in the box.
- The new storage constant lives in `config.py` only (invariant 4), reads an env
  var, and defaults beside the Quotes folder. Add it to `docs/SETUP.md` and the
  `.env` example.

## Acceptance criteria

- [x] A tab-separated paste copied out of a spreadsheet parses identically to the `|` form
- [x] `part #`, `link` and `description` are optional; a 4-field line parses
- [x] Quantity must be a positive whole number, unit price a number ≥ 0, name non-empty — each violation produces its own error naming the line number and the offending value
- [x] A `shipping | <amount>` line is picked up as shipping; a second one is an error
- [x] Blank lines are skipped, and a bad line after a blank line still reports its true line number
- [x] More than 25 item lines is an error
- [x] Formatting items back to text and re-parsing them returns the same items and shipping
- [x] The total check passes when items plus shipping match the request total within $0.01, and otherwise returns a sentence naming both numbers
- [x] One line with quantity 10 does not need a BOM; two lines do
- [x] The change description returns nothing for two identical requests, and the exact fragments (e.g. `Total $412.00 → $455.50`, `items 4 → 5`) when fields differ
- [x] A built workbook opens with openpyxl and carries the header block (vendor, requester, project ID / fund, log row, date), one row per item, a shipping row and a total row, all as numbers
- [x] A workbook built without a row number reads `DRAFT` where the row would be
- [x] An item whose link is a URL gets a working hyperlink in the sheet
- [x] The file name is `NNNN_<Vendor>_BOM.xlsx` with the row zero-padded to four digits; vendor punctuation is stripped, long vendors truncated, an empty vendor falls back
- [x] Saving a BOM is atomic and leaves no temp files behind
- [x] `BOMS_DIR` is read from the environment in `config.py`, appears in the startup path check with the other storage paths, and a missing folder is named in the startup admin alert without stopping the bot
- [x] `ruff check .`, `python scripts/check_tests_first.py` and `pytest -q` all pass

## Comments

### 2026-09-22 — Implementation complete

- Implemented `src/bom.py` with pure domain functions:
  - `parse_line_items`: parses pipe- and tab-delimited pasted items, optional fields, shipping line, preserves 1-indexed line numbers through blank lines, and returns detailed validation errors.
  - `format_line_items`: inverse formatter for pre-filling edit modals, round-trips with `parse_line_items`.
  - `check_total`: checks sum of items + shipping against target total with $0.01 tolerance, returning sentence with both values on mismatch.
  - `needs_bom`: checks if request has two or more line items.
  - `describe_changes`: returns list of diff fragments (`Total $X → $Y`, `items N → M`, `items changed`, etc.).
  - `bom_filename`: formats `NNNN_<Vendor>_BOM.xlsx` (padded to 4 digits, slugged, truncated to 40 chars, falling back to `Vendor`) or `DRAFT_<Vendor>_BOM.xlsx`.
  - `build_bom_workbook`: generates in-memory openpyxl workbook containing header details, item rows, shipping row, and grand total row, with totals written as concrete numbers (never formulas) and URL hyperlinks.
- Implemented `save_bom` in `src/log_writer.py` using atomic temp file replacement into `BOMS_DIR`.
- Added `BOMS_DIR` to `src/config.py`, `src/path_validator.py` (`check_storage_paths`, `STORAGE_PATHS`, `validate_and_configure`), `docs/SETUP.md`, and `docs/PYTHON_SOURCE_DEPLOYMENT.md`.
- Added tests in `tests/test_26_line_items_and_bom.py` (16 test cases covering all criteria), updated `tests/test_layering_and_isolation.py` (pure domain import check), `tests/test_24_startup_storage_check.py` (storage paths fixture), and scoped `test_11_roster_sync.py` openpyxl guard to exclude `bom.py` per ADR 0006.
- Ran adversarial checks confirming tests fail when code is broken.
- Full test suite: 317 passed, 31 skipped in 8.56s. Ruff and tests-first check pass cleanly.
