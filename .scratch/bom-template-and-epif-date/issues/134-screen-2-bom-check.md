# 134: Interview Screen 2 reads the BOM and shows the BOM check; the paste box leaves Screen 2

**Status:** in-progress

**Runner:** any

**Auto-merge:** yes

**Blocked by:** 131, 132, 133

**Deletes tests:** tests/test_28_line_items_modal_path.py::test_screen2_renders_optional_multiline_line_items_input, tests/test_28_line_items_modal_path.py::test_valid_paste_stores_items_and_shipping_in_metadata_and_uploads_draft_bom, tests/test_28_line_items_modal_path.py::test_totals_mismatch_refused_on_items_box_no_card_posted, tests/test_28_line_items_modal_path.py::test_line_numbered_parse_error_refused_on_items_box_no_card_posted, tests/test_28_line_items_modal_path.py::test_items_box_1500_char_with_fabrication_completes_screen3_and_posts, tests/test_28_line_items_modal_path.py::test_one_item_paste_posts_card_with_no_spreadsheet, tests/test_82_bom_on_new_purchase.py::test_form_rejects_bom_with_pasted_items, tests/test_82_bom_on_new_purchase.py::test_bom_is_carried_with_quote

**Spec:** `.scratch/bom-template-and-epif-date/spec.md` (Part E, stories 29, 32–36, 45–47, 55)
**Binding:** `docs/adr/0019-boms-come-in-through-the-lab-template-and-are-read.md`; `docs/adr/0001-tests-first-and-no-muted-failures.md`; `docs/adr/0006-bom-line-items-and-editable-posted-cards.md` (items in message metadata)
**Glossary:** `CONTEXT.md` — **BOM check**, **BOM template**, **Line item**, **BOM**

## What to build

A new request with two or more items comes in as the lab BOM template, and the requester sees
what the bot read before anything is posted.

- **Screen 2** (`blocks.build_stage2_view`, also used by Edit) loses the paste box
  (`line_items_input`). It keeps the BOM file field, `.xlsx` only, and the one-vendor
  checkbox, which is required when a BOM is attached (the existing
  `bom.attachment_errors` rule).
- **Submitting Screen 2 with a BOM:**
  1. `app.handle_stage2_submit` runs every existing check first (P-card, category minimum,
     one-vendor).
  2. It then answers at once with `ack(response_action="update", view=blocks.build_bom_reading_view(meta))`,
     a view with `callback_id == "bom_check_submit"` that says `Reading your BOM…`. Download
     and parse take longer than Slack's 3-second acknowledgement window.
  3. A background thread downloads the file with `slack_io.download`, runs
     `bom.read_bom_template` and `bom.check_bom_total` against the typed Total Price, and
     calls `client.views_update(view_id=body["view"]["id"], view=blocks.build_bom_check_view(meta, items, problems, total, typed_total))`.
- **The check view** (`callback_id` `bom_check_submit`) shows:
  - one line per row: `qty × item — part # — $unit = $line`;
  - after 40 rows, `…and N more rows`;
  - the BOM total next to the typed total;
  - every problem, or `✅ The bot read N items totalling $X. This matches your total.`;
  - an optional `.xlsx` file input `block_bom_reupload` for a corrected file.

  `meta` (including `stage2`) rides in `private_metadata`. The items do not ride in any
  button value.
- **Submitting the check view:**
  - **With a new file**, it repeats the reading step on that file.
  - **With problems still outstanding and no new file**, it answers
    `response_action="errors"` on `block_bom_reupload` with the problems joined by newlines.
  - **With none**, it continues exactly as Screen 2 would have: Screen 3 for asset
    categories (`response_action="update"` with `build_stage3_view`), else
    `lifecycle._process_interview_completion` with the items placed where the paste path
    placed them today.

  Line items go into the card's message metadata, the draft BOM is uploaded to the thread,
  and the Filled EPIF says `See attached BOM — N items`. This is the existing
  `epif_filler` rule for 2 or more items.
- **A one-item request** has no BOM and behaves as today.
- **An uploaded BOM file is not kept as an attachment.** The bot's rebuilt BOM (ticket 132)
  replaces it. Quotes are unchanged.

## Acceptance criteria

- [ ] New file `tests/test_134_screen2_bom_check.py`, `test_screen2_has_no_paste_box`: `build_stage2_view` (new request and edit meta) has no `block_line_items` block, and `block_bom`'s file input accepts only `xlsx`.
- [ ] `test_submit_with_the_real_bom_shows_the_check` drives `app.handle_stage2_submit` with a fake client whose file download returns the fixture bytes, Total Price `858.50`, one-vendor ticked. Run the background work synchronously by patching the thread starter only.
  - The ack is `response_action="update"` with `callback_id == "bom_check_submit"`.
  - `views_update` was called with that view id.
  - The updated view's text contains `4 items` and `$858.50`, and no `chat_postMessage` has happened yet.
- [ ] `test_check_refuses_a_mismatch_then_accepts_a_fix`:
  - With Total Price `900`, the check view lists `The BOM totals $858.50 but you typed $900.00 — they must match.`
  - Submitting the check view with no new file gets `response_action="errors"` on `block_bom_reupload`, and no card is posted.
  - Submitting it with a corrected file that totals $900.00 posts the card. The card message's `metadata` holds 4+ line items, and a `DRAFT_HIRST_LAB_BOM_` file is uploaded to the thread.
  - All in this one function.
- [ ] `test_non_template_file_is_refused_on_the_check_screen`: a CSV upload shows the "isn't the lab BOM template" sentence, and posting is refused until a template is uploaded.
- [ ] `test_fabrication_bom_goes_to_screen3_after_the_check`: with category Fabrication and a clean BOM ≥ $200, submitting the check view acks `response_action="update"` with the Screen 3 view.

May fake: the Slack client (including `views_update`, `files_info`/download), the thread starter (run inline). Must be real: `bom.read_bom_template` on the committed fixture, `bom.build_bom_workbook`, the `blocks` view builders, `app.handle_stage2_submit` and the new check-view listener found through the real Bolt registry.

## Gate

Run all four, in CI's order, and all must pass:

    ruff check .
    python scripts/check_tests_first.py
    python tools/type_gate.py
    pytest --tb=short -q -n auto --dist loadfile

Tests need `SLACK_BOT_TOKEN=xoxb-test-not-a-real-token`, `SLACK_APP_TOKEN=xapp-test-not-a-real-token` and `PYTHONUTF8=1` in the environment, as `.github/workflows/tests.yml` sets.

The gate holds a PR that adds a new test which already passes on today's code. Where a ticket says checks share one test function, keep them together so the function fails on the base commit.

## Comments
