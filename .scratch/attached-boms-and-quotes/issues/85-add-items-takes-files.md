# 85: Add items takes files on PDF-born cards

**Status:** ready-for-agent

**Runner:** any

**Auto-merge:** yes

**Blocked by:** 83

**Spec:** `.scratch/attached-boms-and-quotes/spec.md`
**Binding:** `docs/adr/0012-attached-boms-and-quotes-are-carried-not-read.md` decisions 1–5; `docs/adr/0006-bom-line-items-and-editable-posted-cards.md` decisions 1, 8; ADR 0001

## What to build

On a card born from a dropped EPIF, **Add items** opens a form that now also takes a BOM and quotes,
with the same rules as Screen 2. A requester can attach their spreadsheet instead of pasting
rows. Approval then archives them (ticket 83 already reads `attachments` from the card).

1. `src/blocks.py` `build_items_view`: make the line-items box optional
   (`line_items_input(..., optional=True, ...)`) and append `bom_inputs()` and `quotes_input()`
   (from tickets 81–82).
2. `src/app.py` `handle_items_modal_submit`: read the BOM, the one-vendor box and the quotes as
   `handle_stage2_submit` does. Errors, in order:
   - nothing at all (blank items, no BOM, no quotes) →
     `{"block_line_items": "Add line items, a BOM or quotes."}`;
   - `bom.attachment_errors(...)` non-empty → those errors.
   Run the existing items parse and total check only when the items text is not blank.
3. `src/lifecycle.py` `handle_items_update` gains `attachments: list[dict] | None = None`: the
   new attachments are appended to the card payload's existing `attachments` (a new BOM replaces
   an existing `bom` one), written in the same `chat_update(... metadata=...)` that writes items,
   posted with `post_attachments_to_thread`, and the thread edit line gains
   `attached BOM <name>` and/or `added N quote(s)`. When the items text was blank, the existing
   items are left as they are.

## Acceptance criteria

New test file `tests/test_85_add_items_files.py`, driving `app.handle_items_modal_submit` with a
fake client whose `conversations_replies` returns a posted EPIF-born card, as
`tests/test_27_line_items_epif_path.py` does.

- [ ] **The form.** `build_items_view(...)` contains `block_line_items` with `optional` true, `block_bom`, `block_bom_one_vendor` and `block_quotes`.
- [ ] **Empty is refused.** Submitting with nothing → `ack(response_action="errors", errors={"block_line_items": "Add line items, a BOM or quotes."})`, no `chat_update`.
- [ ] **Same rules.** BOM + pasted items → the not-both error on `block_bom`; BOM + box unticked → the one-vendor error on `block_bom_one_vendor`.
- [ ] **Files only.** BOM (box ticked) + two quotes, items blank → the card's `chat_update` metadata `attachments` has the BOM and both quotes; three `files_upload_v2` calls into the thread; one thread line containing `attached BOM` and `added 2 quote(s)`; the card's existing `items` are unchanged.
- [ ] **Approval archives them.** Approving that card (entry point as in ticket 83's test) writes `<row>_<Vendor>_BOM.xlsx` and `_Quote_1.pdf`, `_Quote_2.pdf` into the temp folders.

**Tests may fake:** the Slack client, `slack_io.download_file`, the lock queue. **Must be real:** `build_items_view`, `handle_items_modal_submit`, `bom.attachment_errors`, `handle_items_update`, the archive writes into temp folders.

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
