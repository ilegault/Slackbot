# 82: BOM field on /new-purchase

**Status:** in-progress

**Runner:** any

**Auto-merge:** yes

**Blocked by:** 81

**Spec:** `.scratch/attached-boms-and-quotes/spec.md`
**Binding:** `docs/adr/0012-attached-boms-and-quotes-are-carried-not-read.md` decisions 1–4; `docs/adr/0006-bom-line-items-and-editable-posted-cards.md` decision 3; ADR 0001

## What to build

A requester can attach their own BOM spreadsheet (one `.xlsx` or `.csv`) on Screen 2 instead of
pasting line items. A tick box confirms every item is from one vendor (one EPIF per vendor). The
BOM is carried, never read: it is posted into the thread like the quotes from ticket 81, and no
made BOM is built.

1. `src/blocks.py`: new builder `bom_inputs()` returning two blocks, added to
   `build_stage2_view` beside `quotes_input()` (still **only when not `is_edit`**):
   - optional `input`, `block_id` `block_bom`, element
     `{"type": "file_input", "action_id": "bom", "filetypes": ["xlsx", "csv"], "max_files": 1}`,
     label `BOM spreadsheet (optional)`, hint `Your own BOM, sent to purchasing as-is. The Total Price above is the amount.`
   - optional `input`, `block_id` `block_bom_one_vendor`, element `checkboxes`, `action_id`
     `bom_one_vendor`, one option value `one_vendor` text
     `Every item in this BOM comes from one vendor`, label `Required if you attach a BOM`.
     (Always shown: a Slack form cannot reveal a block when a file is picked.)
2. `src/bom.py`: new pure function
   `attachment_errors(bom_files: list, one_vendor_ticked: bool, line_items_text: str) -> dict[str, str]`
   returning, in this priority:
   `{"block_bom": "Attach a BOM or paste line items, not both."}` when a BOM is given and the
   line-items text is not blank; else
   `{"block_bom_one_vendor": "One EPIF per vendor — split this into one request per vendor."}`
   when a BOM is given and the box is unticked; else `{}`. Pure so it can be tested directly
   and reused by tickets 85 and 86.
3. `src/app.py` `handle_stage2_submit`: before the line-items parse, read the BOM with
   `text_rules.extract_modal_files(values, "block_bom", "bom")` and the box's selected options;
   if `bom.attachment_errors(...)` is non-empty, `ack(response_action="errors", errors=...)` and
   return. Otherwise append `{"role": "bom", **file}` to `stage2["attachments"]` (BOM first,
   then quotes).
4. `src/lifecycle.py` `_process_interview_completion`: when an attachment has role `bom`, add the
   summary line `📎 BOM attached: <name>`. The existing `post_attachments_to_thread` posts it.
5. `src/blocks.py` `_BUTTON_LIST`: replace the bullet
   `• Drop quote files or confirmation receipts directly into the thread to attach them.` with
   `• Attach a BOM spreadsheet and quote PDFs in the purchase form, or drop quotes into the thread with \`@Purchasing quote\`.`

## Acceptance criteria

New test file `tests/test_82_bom_on_new_purchase.py`, payloads built like
`tests/test_81_quotes_on_new_purchase.py`.

- [ ] **The fields.** `build_stage2_view(meta)` has `block_bom` (file_input, `filetypes == ["xlsx", "csv"]`, `max_files == 1`, optional) and `block_bom_one_vendor` (checkboxes, one option `one_vendor`, optional); neither appears with `is_edit` true.
- [ ] **The rules, directly.** `bom.attachment_errors([{"id": "F"}], True, "1 | x | | 5 | |")` == the not-both error on `block_bom`; `([{"id": "F"}], False, "")` == the one-vendor error on `block_bom_one_vendor`; `([{"id": "F"}], True, "")` == `{}`; `([], False, "")` == `{}`.
- [ ] **The rules, through the form.** Submitting Screen 2 with a BOM and pasted items → `ack` called with `response_action="errors"` and exactly that text on `block_bom`, no card posted; with a BOM and the box unticked → the one-vendor text on `block_bom_one_vendor`, no card posted.
- [ ] **A BOM is carried.** BOM `order.xlsx` + box ticked + one quote → card metadata `attachments` == `[{"role": "bom", "id": ..., "name": "order.xlsx"}, {"role": "quote", ...}]`; card text contains `BOM attached: order.xlsx`; `files_upload_v2` called for both into the card's thread; `upload_draft_bom` is not called (spy on `lifecycle.upload_draft_bom`).
- [ ] **Help text.** `blocks.get_help_message()` and `build_app_home_view()` contain `Attach a BOM spreadsheet and quote PDFs in the purchase form` and no longer contain `Drop quote files or confirmation receipts`. Any existing test asserting the old bullet is updated in place.

**Tests may fake:** the Slack client, `slack_io.download_file`. **Must be real:** `bom.attachment_errors`, `blocks`, the submit handler, `lifecycle._process_interview_completion`.

## Gate

Run in this order, exactly as CI does (`.github/workflows/tests.yml`). Zero failures before
you push.

```
ruff check .
python scripts/check_tests_first.py
python tools/type_gate.py
pytest --tb=short -q -n auto --dist loadfile
```

## Comments
