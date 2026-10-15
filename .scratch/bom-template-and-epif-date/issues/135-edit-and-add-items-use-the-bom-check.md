# 135: Edit and Add items take a BOM through the same check; the paste box is gone everywhere

**Status:** in-progress

**Runner:** any

**Auto-merge:** yes

**Blocked by:** 134

**Deletes tests:** tests/test_26_line_items_and_bom.py::test_parse_line_items_pipe_and_tab_identical, tests/test_26_line_items_and_bom.py::test_parse_line_items_optional_fields, tests/test_26_line_items_and_bom.py::test_parse_line_items_validation_errors, tests/test_26_line_items_and_bom.py::test_shipping_line_and_duplicate_error, tests/test_26_line_items_and_bom.py::test_blank_lines_skipped_and_line_numbering, tests/test_26_line_items_and_bom.py::test_more_than_25_items_error, tests/test_26_line_items_and_bom.py::test_format_line_items_round_trip, tests/test_26_line_items_and_bom.py::test_check_total, tests/test_50_one_items_box.py::test_the_example_we_show_parses, tests/test_50_one_items_box.py::test_same_hint_and_placeholder_in_all_three, tests/test_50_one_items_box.py::test_block_line_items_literal_appears_once_in_blocks_source, tests/test_50_one_items_box.py::test_bad_paste_in_workday_modal_shows_the_error, tests/test_27_line_items_epif_path.py::test_submitting_valid_paste_stores_items_and_shipping_in_metadata_and_not_in_button_value, tests/test_27_line_items_epif_path.py::test_totals_mismatch_refused_inside_modal_naming_both_numbers_card_untouched, tests/test_27_line_items_epif_path.py::test_bad_line_refused_inside_modal_with_line_number_card_untouched, tests/test_27_line_items_epif_path.py::test_reopening_button_once_items_exist_prefills_box_and_reads_edit_items, tests/test_27_line_items_epif_path.py::test_resubmitting_different_items_replaces_stored_items_and_reposts_draft_spreadsheet, tests/test_85_add_items_files.py::test_bom_with_pasted_items_and_bom_without_one_vendor_are_refused, tests/test_86_edit_files.py::test_pasting_items_while_card_keeps_bom_is_refused

**Spec:** `.scratch/bom-template-and-epif-date/spec.md` (Part E, stories 47–49)
**Binding:** `docs/adr/0019-boms-come-in-through-the-lab-template-and-are-read.md`; `docs/adr/0001-tests-first-and-no-muted-failures.md`; `docs/adr/0006-bom-line-items-and-editable-posted-cards.md`
**Glossary:** `CONTEXT.md` — **Edit**, **BOM check**, **Line item**

## What to build

Ticket 134 removed the paste box from the view Edit shares. This ticket finishes the job:

- **Edit** (`app.handle_edit_submit` → `lifecycle.handle_request_edit`) and **Add items**
  (`blocks.build_items_view`, `app.handle_items_modal_submit` → `lifecycle.handle_items_update`)
  take a BOM file and go through 134's reading view and check view before they apply.
- **An empty BOM field on Edit** keeps the current rows (ADR 0012 decision 6 rule, still in
  force).
- **The Workday details modal** (`blocks.build_workday_details_view`, bare-thread and
  switch-to-EPIF) loses its paste box and gets the same BOM field, one-vendor checkbox and
  check flow.
- **The paste-path code is deleted**: `blocks.line_items_input`, `bom.parse_line_items`,
  `bom.format_line_items`, `bom.check_total` and shipping handling.
  - Everywhere that read `shipping` from a card treats it as absent. Cards posted before this
    ships may still carry it: ignore it, never fail on it.
  - When the check view finishes, it must know which form opened it. Record `origin` in
    `private_metadata` (`interview` / `edit` / `items` / `workday_details`) and dispatch to
    that form's existing apply function.

## Acceptance criteria

- [ ] New file `tests/test_135_edit_and_add_items_bom.py`, `test_edit_with_a_new_bom_replaces_the_rows`:
  - Edit a posted card, uploading the fixture through the check flow; the card's metadata now holds the fixture's 4 items.
  - One thread line names the change, as `bom.describe_changes` does today.
  - A new `DRAFT_HIRST_LAB_BOM_` is uploaded.
  - In the same function, a second Edit that only changes Purpose leaves the metadata items identical and uploads no BOM.
- [ ] `test_add_items_uses_the_check`: Add items with a mismatching BOM is refused on `block_bom_reupload`, and the card is unchanged (no `chat_update`).
- [ ] `test_no_paste_box_anywhere`:
  - `"block_line_items"` does not occur in `src/blocks.py`.
  - None of the built views (`build_stage2_view`, `build_items_view`, `build_workday_details_view`) has it.
  - `bom` has no attribute `parse_line_items`.
- [ ] **Rewrite in place, same names**, to upload the fixture instead of pasting: `test_edit_items_change_reposts_draft_bom` (`tests/test_32_edit_a_posted_card.py`), `test_form_has_optional_items_box_bom_and_quotes` (`tests/test_85_add_items_files.py`), `test_attachment_errors_rules` (`tests/test_82_bom_on_new_purchase.py`), and any other test that sent `block_line_items`.

May fake: the Slack client and file download, the thread starter. Must be real: the reader, the BOM builder, the view builders and the handlers.

## Gate

Run all four, in CI's order, and all must pass:

    ruff check .
    python scripts/check_tests_first.py
    python tools/type_gate.py
    pytest --tb=short -q -n auto --dist loadfile

Tests need `SLACK_BOT_TOKEN=xoxb-test-not-a-real-token`, `SLACK_APP_TOKEN=xapp-test-not-a-real-token` and `PYTHONUTF8=1` in the environment, as `.github/workflows/tests.yml` sets.

The gate holds a PR that adds a new test which already passes on today's code. Where a ticket says checks share one test function, keep them together so the function fails on the base commit.

## Comments
