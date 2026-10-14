# 132: The rebuilt BOM follows the lab template and is named HIRST_LAB_BOM_<Description>_<date>

**Status:** ready-for-agent

**Runner:** any

**Auto-merge:** yes

**Blocked by:** 131

**Spec:** `.scratch/bom-template-and-epif-date/spec.md` (Part E, stories 50–54)
**Binding:** `docs/adr/0019-boms-come-in-through-the-lab-template-and-are-read.md`; `docs/adr/0001-tests-first-and-no-muted-failures.md`
**Glossary:** `CONTEXT.md` — **BOM**, **BOM template**

## What to build

The BOM the bot writes, both the draft before approval and the archived copy at approval,
follows the lab template exactly and gets the lab's file naming.

1. **`bom.build_bom_workbook(request, items) -> bytes`** — load `config.BOM_TEMPLATE_PATH` and
   fill it.
   - B2 Order Description = `item_description`; B3 BOM Creator = the requester's roster name
     (`request["requester"]`).
   - One row per item from row 6: Item (with a hyperlink when `link` starts with `http://` or
     `https://`), Description, Product #, Vendor (the item's own `vendor`, else the request's
     vendor), Unit Cost, Quantity, `=F{r}*E{r}`, Notes.
   - Then the Total row (`Total` in F, `=SUM(G6:G{last})` in G) and B4 `=G{total_row}`.
   - Insert rows so any item count fits, keeping the template's styles.
   - Drop everything in ADR 0008 that ADR 0019 replaced.
2. **`bom.bom_filename(description: str, approval_date: datetime.date | None, draft: bool = False) -> str`**
   — replaces the `(row, vendor, ext)` signature.
   - Each whitespace-separated word of `description` keeps only characters valid in a
     Windows file name; the words are joined with `-` and cut to 60 characters.
   - Result: `HIRST_LAB_BOM_<that>_<MM.DD.YYYY>.xlsx`, or for `draft=True`
     `DRAFT_HIRST_LAB_BOM_<that>_<MM.DD.YYYY>.xlsx` using today's date.
   - Update every caller: `lifecycle.finalize_purchase_request` (both branches) and
     `lifecycle.upload_draft_bom`.
   - An **attached** BOM on a card posted before this ships keeps its original extension and
     is archived as-is under the new name with its own extension: add an `ext` keyword with
     default `"xlsx"`.
3. **`log_writer.save_bom`** — when the target name exists in the folder, save as `_2`, `_3`, …
   before the extension, and return the final path. The Notes column and the card's
   `bom_file` use the returned name.
4. **`text_rules.generate_email_draft`** already names the BOM file. It needs no change beyond
   receiving the new name.

## Acceptance criteria

- [ ] **Rewrite in place, same names**, to assert the ADR 0019 layout and names. In `tests/test_26_line_items_and_bom.py`: `test_build_bom_workbook_content_and_numbers`, `test_build_bom_workbook_draft_header`, `test_bom_filename`. In `tests/test_49_bom_lab_layout.py`: `test_layout`, `test_formulas_compute_right_total`, `test_unknown_vendor_fallback`, `test_nothing_the_adr_removed`. No test function is deleted.
- [ ] New file `tests/test_132_bom_round_trip.py`, `test_rebuilt_bom_reads_back`:
  - Read the fixture with `bom.read_bom_template`, rebuild it with `build_bom_workbook`, and read the result again.
  - The items are equal, including links.
  - B2 is the description and B3 the requester name.
  - The header row is on the row where the template has it.
- [ ] `test_bom_filename_cases`:
  - `("Copper gaskets for CF flanges", date(2026,10,14))` gives `HIRST_LAB_BOM_Copper-gaskets-for-CF-flanges_10.14.2026.xlsx`;
  - a description with `/:*?"<>|` drops those characters;
  - a 200-character description gives a name part of 60 characters;
  - `draft=True` starts with `DRAFT_`.
- [ ] `test_save_bom_never_overwrites` (uses `tmp_path`): saving the same name twice yields `…_10.14.2026.xlsx` and `…_10.14.2026_2.xlsx`, both on disk.
- [ ] The approval tests that assert BOM names (`tests/test_29_approval_archives_bom.py`, `tests/test_30_buyers_dm_carries_bom.py`, `tests/test_31_cancel_moves_bom.py`, `tests/test_83_approval_archives_attachments.py`) are rewritten in place under the same names to expect the new names. The Notes column written at approval names the returned file. (no test: the full suite in the gate proves it)

May fake: the Slack client and the queue's workbook (capture the row). Must be real: openpyxl, the committed template and fixture, `log_writer.save_bom` into `tmp_path`.

## Gate

Run all four, in CI's order, and all must pass:

    ruff check .
    python scripts/check_tests_first.py
    python tools/type_gate.py
    pytest --tb=short -q -n auto --dist loadfile

Tests need `SLACK_BOT_TOKEN=xoxb-test-not-a-real-token`, `SLACK_APP_TOKEN=xapp-test-not-a-real-token` and `PYTHONUTF8=1` in the environment, as `.github/workflows/tests.yml` sets.

The gate holds a PR that adds a new test which already passes on today's code. Where a ticket says checks share one test function, keep them together so the function fails on the base commit.

## Comments
