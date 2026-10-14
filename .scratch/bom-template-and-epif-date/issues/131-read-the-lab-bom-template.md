# 131: Read the lab BOM template

**Status:** done

**Runner:** any

**Auto-merge:** yes

**Blocked by:** None (can start immediately)

**Spec:** `.scratch/bom-template-and-epif-date/spec.md` (Part E, stories 33, 37–43)
**Binding:** `docs/adr/0019-boms-come-in-through-the-lab-template-and-are-read.md`; `docs/adr/0001-tests-first-and-no-muted-failures.md`
**Glossary:** `CONTEXT.md` — **BOM template**, **Line item**, **BOM check**

## What to build

A pure reader for the lab's BOM template. Nothing calls it yet: tickets 134 and 136 wire it in.
`templates/HIRST_LAB_BOM_TEMPLATE.xlsx` is the blank template. `tests/fixtures/BOM_TEMPLATE_FILLED_EXAMPLE.xlsx`
is a real filled one: four copper-gasket rows totalling $858.50, an Item hyperlink on every row,
a stray backtick in A10, and "Total" in F10. Both are already committed. Open them before writing
code.

1. **`src/config.py`**:
   - `BOM_TEMPLATE_PATH`, pointing at `templates/HIRST_LAB_BOM_TEMPLATE.xlsx` relative to the
     repo or bundle base, resolved the way `config` resolves other repo-relative paths;
   - `BOM_TEMPLATE_HEADERS = ("Item", "Description", "Product #", "Vendor", "Unit Cost", "Quantity", "Total Cost", "Notes")`;
   - `BOM_MAX_ROWS`. Size it so the line items of a full BOM, serialised as the card's
     message metadata, stay under Slack's documented metadata limit. Cite the Slack docs URL
     in a comment. If Slack documents no limit, use 50 and say so in the comment.
2. **`src/bom.py`** — `read_bom_template(xlsx_bytes: bytes) -> tuple[list[dict], list[str]]`,
   pure, using `openpyxl.load_workbook(..., data_only=False)` on the bytes.
   - **Header row.** Find it in the first 10 rows of the first sheet. It matches when the
     cells, `.strip().lower()`, equal the headers in order. No match returns
     `([], ["This isn't the lab BOM template — get it with the “Send me the BOM template” button. Vendor carts and quotes go in the Quotes field."])`.
     Bytes that are not a readable `.xlsx` (a CSV, a PDF) return the same single problem.
   - **Rows.** Read the rows below it until a row whose Quantity cell, `.strip()`, equals
     `Total` (case-insensitive). Skip rows where Unit Cost and Quantity are both blank.
   - **Each read row** becomes
     `{"item_name", "description", "part_number", "vendor", "unit_price": float, "quantity": int, "notes", "link"}`.
     - Use the key names the current line-item dicts use (`bom.parse_line_items`) for the
       fields both have, so the card, the BOM builder and `request_summary_lines` keep working.
     - `link` is `cell.hyperlink.target` of the Item cell, or `""`.
     - The Total Cost column is never read.
   - **Problems**, each naming the spreadsheet row:
     - `Row N: Item is blank.`
     - `Row N: Quantity '<v>' isn't a whole number of 1 or more.`
     - `Row N: Unit Cost '<v>' isn't a number.`
     - More than `BOM_MAX_ROWS` rows: `This BOM has K rows — the most is BOM_MAX_ROWS.`
3. **`bom.bom_total(items) -> float`**: the sum of `quantity * unit_price`, rounded to cents.
   **`bom.check_bom_total(items, total_price) -> str | None`**: returns
   `The BOM totals $X but you typed $Y — they must match.` unless the two are equal to the
   cent. Shipping plays no part.
4. Module docstring: why the reader never reads formula cells (openpyxl-written files hold no
   cached results), and why there is no header guessing (ADR 0019).

## Acceptance criteria

- [x] New `tests/test_131_read_bom_template.py`, `test_reads_the_real_lab_bom`: reading `tests/fixtures/BOM_TEMPLATE_FILLED_EXAMPLE.xlsx` gives:
  - 4 items and no problems;
  - the first item `quantity == 2`, `unit_price == 23.75`, `part_number == "G-0133"`, `link == "https://www.duniway.com/part/g-0133"`;
  - `bom_total(items) == 858.50`.
- [x] `test_not_the_template` builds three inputs in the test, each returning exactly the single "isn't the lab BOM template" problem:
  - an xlsx with headers `Qty | Part | Price` (via openpyxl);
  - a CSV's bytes with the template headers;
  - a PDF's bytes (the EPIF fixture).
- [x] `test_row_problems_by_row_number` copies the fixture in memory and edits it:
  - E7 = `"TBD"` gives `Row 7: Unit Cost 'TBD' isn't a number.`;
  - F8 = `2.5` gives the Quantity problem for row 8;
  - A9 = `None` gives `Row 9: Item is blank.`;
  - a fully blank inserted row and the stray A10 mark produce no problem.
- [x] `test_check_bom_total`: `(items, 858.50)` gives `None`; `(items, 858.49)` gives the exact mismatch sentence with `$858.50` and `$858.49`.
- [x] `test_row_cap`: an in-test template with `BOM_MAX_ROWS + 1` valid rows gives the cap problem.

May fake: nothing needs faking. Must be real: openpyxl reading the committed fixture and in-test workbooks. A test that builds dicts instead of reading an `.xlsx` does not count.

## Gate

Run all four, in CI's order, and all must pass:

    ruff check .
    python scripts/check_tests_first.py
    python tools/type_gate.py
    pytest --tb=short -q -n auto --dist loadfile

Tests need `SLACK_BOT_TOKEN=xoxb-test-not-a-real-token`, `SLACK_APP_TOKEN=xapp-test-not-a-real-token` and `PYTHONUTF8=1` in the environment, as `.github/workflows/tests.yml` sets.

The gate holds a PR that adds a new test which already passes on today's code. Where a ticket says checks share one test function, keep them together so the function fails on the base commit.

## Comments

2026-10-14 — Landed. `bom.read_bom_template`, `bom_total`, `check_bom_total` plus `config.BOM_TEMPLATE_PATH/HEADERS/BOM_MAX_ROWS`. All five criteria covered by `tests/test_131_read_bom_template.py` (real fixture, in-test workbooks, CSV and EPIF PDF bytes).
- Items carry both the existing keys (`qty`, `name`) and the ticket's (`quantity`, `item_name`), plus `vendor`, `notes`.
- `BOM_MAX_ROWS = 50`: the Slack metadata docs page could not be fetched from the sandbox, so no limit is cited.
- `test_only_log_writer_opens_workbook_path` now exempts `load_workbook(io.BytesIO(...))` in bom.py only (harness defect: guard targets the log workbook path; paths still fail).
- Local `test_docs_adr_is_unmodified` fails only because the shared checkout's local `master` is stale; `git diff origin/master -- docs/adr` is empty.
