# 49: The BOM sheet uses the lab layout

**Status:** done

**Runner:** any

**Auto-merge:** yes

**Blocked by:** None

**Spec:** `.scratch/bom-lab-layout/spec.md`
**Binding:** `docs/adr/0008-bom-sheet-follows-the-lab-layout.md` (read all seven decisions first), ADR 0001

## What to build

Rewrite `bom.build_bom_workbook` in `src/bom.py` so the spreadsheet matches the layout
below exactly. Nothing else about the BOM changes: when it is made, its file name, where
it is saved, how it is posted and attached.

**Signature change:** `build_bom_workbook(request: dict, items: list[dict]) -> bytes`.
The `shipping` and `row` parameters are removed (ADR 0008 decisions 4 and 6 — neither is
rendered any more). Update both callers in `src/lifecycle.py`:
`finalize_purchase_request` (the call inside the queued write, ~line 287) and
`upload_draft_bom` (~line 1629). Pass only `request` and `items`. Do not change anything
else in either function.

**The layout.** Sheet title `BOM`. Font everywhere: `Aptos Narrow`, size 12.
Colours are hex RGB.

| Cell(s) | Value | Style |
|---|---|---|
| A1:B1 merged | `BILL OF MATERIALS` | fill `0B3041`, font white (`FFFFFF`) bold |
| A2 | `Total Cost` | fill `DCEAF7`, bold |
| B2 | `=G{T}` where `T` is the Total row | fill `DCEAF7`, number format `"$"#,##0.00`, left-aligned |
| row 3 | empty | — |
| A4…H4 | `Item`, `Description`, `Product #`, `Vendor`, `Unit Cost`, `Quantity`, `Total Cost`, `Notes` | fill `104862`, font white bold |
| item row `r` (from 5) | A = item `name`, B = `description`, C = `part_number`, D = request vendor, E = `unit_price` (float), F = `qty` (int), G = `=E{r}*F{r}`, H = empty (None) | E and G number format `"$"#,##0.00` |
| Total row `T` = last item row + 1 | F = `Total`, G = `=SUM(G5:G{T-1})` | A–H fill `104862`; F and G font white bold; G number format `"$"#,##0.00` |

- Column A cell is a hyperlink to the item's `link` when the link starts with `http://`
  or `https://`, with font colour `467886` and single underline. Otherwise plain text and
  no hyperlink.
- Vendor (column D) is `str(request.get("vendor") or "").strip()`, and `Unknown Vendor`
  when that is empty. Same value on every row — one EPIF per vendor.
- Freeze panes at `A5`.
- Column widths: A 35, B 68, C 14, D 17, E 12, F 10, G 13, H 47.
- **No other cell holds a value.** No shipping row, no requester, project, fund, date,
  log row or `DRAFT` text anywhere in the sheet.

**Docstring.** Update `src/bom.py`'s module docstring: point 4 currently says totals are
concrete numbers "never formulas". Replace it with the ADR 0008 reasoning in two
sentences — formulas to match the lab's hand-made BOM so purchasing can adjust a quantity;
accepted cost that Slack's preview shows the formula cells blank because openpyxl stores
no cached results. Add one sentence that the sheet has no shipping row, so its Total can
be below the EPIF amount by the shipping entered, and that this is intended. Point 5
(hyperlinks) now refers to the Item cell.

## Acceptance criteria

- [x] **The two old layout tests are replaced, not muted.**
  `test_build_bom_workbook_content_and_numbers` and `test_build_bom_workbook_draft_header`
  in `tests/test_26_line_items_and_bom.py` assert the ADR 0006 decision-10 layout, which
  ADR 0008 supersedes. Delete those two functions and nothing else in that file. This is
  the only test deletion this ticket authorises; any other failing test is fixed or
  escalated per AGENTS.md.
- [x] **Layout, in `tests/test_49_bom_lab_layout.py`, on the real bytes.** Build a
  3-item request (one item with an `https://` link, one with an empty link, one with a
  non-URL link like `see quote`), reopen the bytes with `openpyxl.load_workbook`, and
  assert: A1 is `BILL OF MATERIALS` and A1:B1 is merged; A2 is `Total Cost`; row 4 reads
  exactly the eight headers in order; rows 5–7 hold name / description / part / vendor /
  unit price / qty in A–F and H is None; row 8 F is `Total`; freeze panes is `A5`; only
  the `https://` item's A cell has a hyperlink, and its target equals the link. Nothing
  may be faked in this test.
- [x] **The formulas compute the right total.** In the same test file, write a small
  helper that evaluates only the two formula shapes this sheet uses —
  `=E{r}*F{r}` and `=SUM(G{a}:G{b})`, plus `=G{n}` for B2 — by reading the referenced
  cells from the reopened workbook, and **raises on any other formula text**. Assert that
  every G cell in rows 5–7 evaluates to `qty × unit_price`, and that G8 and B2 both
  evaluate to the sum of `qty × unit_price` over the three items. This is what catches an
  off-by-one row range; asserting the formula string alone does not.
- [x] **Nothing the ADR removed is in the sheet.** Build with a request carrying
  `requester`, `project_id`, `fund` and `date_of_purchase` values and a 5-item list.
  Walk every cell with a value: none contains the requester, project ID, fund or date
  string, `Shipping`, `DRAFT` or `Purchasing Log`. Row 3 is empty. The last row with any
  value is the Total row (row 10).
- [x] **Both callers still produce the file.** The existing tests for approval archiving
  and draft upload (`tests/test_29_approval_archives_bom.py`, and the draft-BOM tests in
  `tests/test_27_line_items_epif_path.py` / `tests/test_28_line_items_modal_path.py`) pass
  unchanged against the new signature. If one fails because it passed `shipping=` or
  `row=` directly to `build_bom_workbook`, fix the call in the test and say so in the
  commit message; never weaken what it asserts.
- [x] Full gate green, in CI order: `ruff check .`, `python scripts/check_tests_first.py`,
  `pytest -q`.

## Out of scope

- `parse_line_items`, `check_total`, the paste format, shipping handling in the totals
  check, `bom_filename`, `save_bom`, the Notes text in the Purchasing Log.
- Styling the sheet from a template file. The layout is built in code.
- The items box in any modal (ticket 50).


## Comments

**2026-09-25**:
- Replaced old layout tests in `test_26_line_items_and_bom.py`.
- Implemented `test_49_bom_lab_layout.py` which thoroughly tests layout, formula computations, and omission of removed fields.
- Rewrote `build_bom_workbook` in `bom.py` to match the exact lab-provided hand-made layout (Aptos Narrow, correct colors/formulas, freezing panes, hyperlinks).
- Cleaned up `finalize_purchase_request` and `upload_draft_bom` inside `lifecycle.py` to no longer pass `shipping` or `row` to `build_bom_workbook`.
- The test suite is fully passing, full verification gate complete.
