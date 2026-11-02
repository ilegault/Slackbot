# 140: Link column in the BOM template, the reader and the builder

**Status:** done

**Runner:** any

**Auto-merge:** yes

**Blocked by:** None (can start immediately)

**Spec:** `.scratch/item-links/spec.md` (Implementation Decisions: Template file, Reader, Builder, Help text)
**Binding:** `docs/adr/0020-every-item-has-a-link-or-a-reason.md` (decisions 1, 2, 5, 6); `docs/adr/0019-boms-come-in-through-the-lab-template-and-are-read.md`; `docs/adr/0001-tests-first-and-no-muted-failures.md`
**Glossary:** `CONTEXT.md` — **Item link**, **No-link reason**, **Line item**, **BOM template**

## What to build

The lab BOM template gains a plain-text `Link` column after `Product #`. The reader turns
each row's Link cell into an **item link** or a **no-link reason**, and the builder writes
both back into the file purchasing receives. Nothing in Slack changes in this ticket except
two help texts. This is the prefactor every later ticket in the set builds on.

1. **`templates/HIRST_LAB_BOM_TEMPLATE.xlsx`** — insert a column after `Product #` headed
   `Link`. Column order becomes
   `Item | Description | Product # | Link | Vendor | Unit Cost | Quantity | Total Cost | Notes`.
   The header block (B2–B4), the Total row and the live formulas keep their meaning; Total
   Cost becomes `=G{r}*F{r}` (Quantity × Unit Cost, now columns G and F) and the Total row
   sums column H. Do it with openpyxl's `insert_cols` on a copy, then fix every formula,
   and check by opening the result: the header row reads exactly the new order.
2. **`src/config.py`** — `BOM_TEMPLATE_HEADERS` becomes the nine headers above. Add
   `BOM_OLD_TEMPLATE_HEADERS` holding the current eight (the reader needs it to recognise an
   old copy) and `NO_LINK_REASONS = ("No web page", "Covered by another row's link")`.
3. **`src/bom.py`** — add the pure function `normalize_link(text: str) -> str | None`:
   strip spaces at the ends; `None` if the result is empty, contains a space, or has no
   `.`; otherwise the text with `https://` prepended unless it already starts with
   `http://` or `https://` (case-insensitive). Ticket 142 reuses it, so it is public.
4. **`src/bom.py` `read_bom_template`** — stays a pure function from bytes to
   `(items, problems)`.
   - A header row exactly equal to `BOM_OLD_TEMPLATE_HEADERS` (same case/space rule as
     today) returns `([], [_OLD_TEMPLATE])` where `_OLD_TEMPLATE` is the sentence
     `"This is the old BOM template, which has no Link column — get the new one with the “Send me the BOM template” button."`
     Any other mismatch still returns `_NOT_TEMPLATE`.
   - Every item gains `row` (the spreadsheet row number, int), `link` and `no_link_reason`.
   - Link cell text that case-insensitively equals one of `config.NO_LINK_REASONS` (spaces
     trimmed) → `link=""`, `no_link_reason=` that phrase, spelled as in config.
   - Otherwise non-blank Link text → `normalize_link`; `None` adds the row problem
     `f"Row {row_no}: Link '{text}' isn't a web address."` and the row is skipped like any
     other bad row.
   - Blank Link cell → the Item cell's hyperlink target if it has one (as today), else
     `link=""` and `no_link_reason=""`. A blank link is **not** a problem.
5. **`src/bom.py` `build_bom_workbook`** — writes nine columns. Column D (Link): when the
   item has a `link`, the URL as the cell value with `cell.hyperlink` set to it and the same
   blue underlined font the Item cell gets today; else the item's `no_link_reason` text (or
   empty). The Item cell is hyperlinked exactly as today. Vendor/Unit Cost/Quantity/Total/
   Notes each move one column right; update `ncols`, the Total-row lookup (`Total` is now in
   column G) and the formulas.
6. **Help text** — `blocks.py` BOM field hint (`"Two or more items? Fill in the lab BOM template."`,
   in the function containing `block_bom`) becomes
   `"Two or more items? Fill in the lab BOM template, with each item's web page in the Link column."`
   and step 3 of `ops._TEMPLATE_KIT_GUIDE` adds the sentence
   `Put each item's web page in the *Link* column.`
7. **`tests/fixtures/BOM_TEMPLATE_FILLED_EXAMPLE.xlsx`** — rebuilt in the new layout from the
   new template, a link on every row, same items and total as today.

## Acceptance criteria

New file `tests/test_140_link_column.py`, real `.xlsx` bytes in and out, nothing faked.

- [x] `test_reader_takes_link_with_or_without_scheme` — a row with `vendor.com/p/1` reads as `https://vendor.com/p/1`, one with `http://x.org/a` is kept as given; both rows carry `row` equal to their spreadsheet row.
- [x] `test_reader_falls_back_to_item_hyperlink_and_reads_reasons` — blank Link + hyperlinked Item → that target; Link cell `no web page` → `link == ""`, `no_link_reason == "No web page"`; Link cell `Covered by another row's link` likewise; blank Link and no hyperlink → both empty and `problems == []`.
- [x] `test_reader_flags_bad_link_and_old_template` — Link `see quote` gives exactly `"Row N: Link 'see quote' isn't a web address."`; a sheet with `config.BOM_OLD_TEMPLATE_HEADERS` gives the old-template sentence and no items; a sheet with other headers still gives the not-the-template sentence.
- [x] `test_build_then_read_keeps_links_and_reasons` — build a workbook from three items (one link, one each reason), open it with openpyxl: header row equals `config.BOM_TEMPLATE_HEADERS`, the linked row's Link cell and Item cell both have `.hyperlink.target` equal to the URL, the other rows' Link cells hold the reason text; reading the bytes back gives the same `name`, `qty`, `link`, `no_link_reason` per row and `problems == []`.
- [x] Existing tests built on the eight-column layout (`test_131_read_bom_template`, `test_132_bom_round_trip`, `test_49_bom_lab_layout`, and any other that fails on the new headers or fixture) are rewritten **in place under their existing names** to the new layout; ADR 0020 authorises it. No test function is deleted, skipped or marked xfail. The two help-text strings are asserted in the tests that already cover those views/messages.

## Gate

    ruff check .
    python scripts/check_tests_first.py
    python tools/type_gate.py
    pytest --tb=short -q -n auto --dist loadfile --durations=25

## Out of scope

The BOM check screen, Screen 2's link field, approval and card metadata (tickets 141–144).
Editing `docs/adr/` or `CONTEXT.md`.

## Comments

2026-11-02: Completed implementation of Ticket 140.
- Updated `templates/HIRST_LAB_BOM_TEMPLATE.xlsx` to 9 columns with `Link` inserted at column D and formulas adjusted.
- Added `BOM_OLD_TEMPLATE_HEADERS` and `NO_LINK_REASONS` to `src/config.py`, updated `BOM_TEMPLATE_HEADERS`.
- Implemented `normalize_link` in `src/bom.py`.
- Updated `read_bom_template` to return `row`, `link`, `no_link_reason`, validate links, parse reason phrases, fall back to Item hyperlinks, and detect the old template.
- Updated `build_bom_workbook` to write 9 columns with hyperlinks and reason text.
- Updated help texts in `src/blocks.py` and `src/ops.py`.
- Rebuilt `tests/fixtures/BOM_TEMPLATE_FILLED_EXAMPLE.xlsx`.
- Added `tests/test_140_link_column.py` covering all acceptance criteria.
- Updated existing tests (`test_49_bom_lab_layout`, `test_131_read_bom_template`, `test_132_bom_round_trip`, `test_26_line_items_and_bom`, `test_29_approval_archives_bom`, `test_54_storage_settings`, `test_82_bom_on_new_purchase`, `test_133_send_bom_template`, `test_139_template_kit`) in place.
- All gates passed: ruff, check_tests_first, type_gate, full pytest suite.
