# 86: Edit keeps, removes or replaces quotes and the BOM

**Status:** in-progress

**Runner:** any

**Auto-merge:** yes

**Blocked by:** 85

**Spec:** `.scratch/attached-boms-and-quotes/spec.md`
**Binding:** `docs/adr/0012-attached-boms-and-quotes-are-carried-not-read.md` decision 6; `docs/adr/0006-bom-line-items-and-editable-posted-cards.md` decision 8; ADR 0001

## What to build

Before approval, the requester (or a buyer or admin) can fix a posted card's attachments without
starting over: untick a bad quote to remove it, untick it and attach a new one to replace it, add
late quotes, or attach a new BOM to replace the old one. Slack can't pre-fill a file field, so an
empty file field means "keep what's there". This applies to both edit forms: **Edit** on a
modal-born card (`build_stage2_view` with `is_edit`) and **Edit items** on an EPIF-born card
(`build_items_view`).

1. `src/blocks.py`: new builder `keep_quotes_input(quotes: list[dict]) -> dict | None` returning an
   optional `input`, `block_id` `block_keep_quotes`, element `checkboxes`, `action_id`
   `keep_quotes`, one option per current quote (value = file id, text = file name),
   `initial_options` = all of them, label `Quotes on this request — untick to remove`. Returns
   `None` when there are no quotes (Slack needs at least one option). Add it, then `bom_inputs()`
   and `quotes_input()`, to `build_stage2_view` when `is_edit` is true, and add it to
   `build_items_view` above the file fields. The current quotes come from the card payload's
   `attachments`, passed in by `handle_req_edit_action` / `handle_req_items_action` — **not**
   through `private_metadata`, which is capped at 3000 characters.
2. `src/bom.py`: new pure `merge_attachments(current: list[dict], kept_quote_ids: list[str], new_bom: list[dict], new_quotes: list[dict]) -> list[dict]`
   → BOM: `new_bom[0]` if given, else the current `bom` one (if any); quotes: current quotes whose
   id is in `kept_quote_ids`, in their original order, then `new_quotes`.
   And `describe_attachment_changes(old: list[dict], new: list[dict]) -> list[str]` →
   `removed quote <name>`, `added quote <name>`, `replaced BOM with <name>`,
   `attached BOM <name>`.
3. `src/app.py` `handle_edit_submit` and `handle_items_modal_submit`: compute the merged list
   and validate it with `bom.attachment_errors` against the **final** state — a BOM present after
   the merge (new or kept) plus non-blank line items is refused on `block_bom`; a new BOM with the
   box unticked is refused on `block_bom_one_vendor`. Pass the merged list on to
   `lifecycle.handle_request_edit` / `handle_items_update`.
4. `src/lifecycle.py` `handle_request_edit` and `handle_items_update`: store the merged list as
   the payload's `attachments` in the existing `chat_update(... metadata=...)`, post only the
   **new** files with `post_attachments_to_thread`, and add the
   `describe_attachment_changes` fragments to the existing edit thread line. A file change counts
   as a change for the existing "no changes → nothing posted" rule.

## Acceptance criteria

New test file `tests/test_86_edit_files.py`, set up like `tests/test_32_edit_a_posted_card.py`
(a posted modal-born card with two quotes F1 `a.pdf`, F2 `b.pdf` and a BOM `old.xlsx` in its
metadata).

- [ ] **The form shows current quotes.** The Edit view has `block_keep_quotes` with options `F1`/`a.pdf`, `F2`/`b.pdf`, both in `initial_options`, plus `block_bom` and `block_quotes`; a card with no quotes has no `block_keep_quotes`. The view's `private_metadata` does not contain `a.pdf`.
- [ ] **Remove and replace.** Submitting with only F1 ticked and new quote F3 `c.pdf` → card metadata `attachments` quotes are `a.pdf`, `c.pdf` (in that order) and the BOM is still `old.xlsx`; one `files_upload_v2` (for `c.pdf` only); the thread line contains `removed quote b.pdf` and `added quote c.pdf`.
- [ ] **New BOM replaces.** Submitting a new BOM `new.xlsx` with the box ticked → the BOM entry is `new.xlsx`; the thread line contains `replaced BOM with new.xlsx`.
- [ ] **Final-state rule.** Pasting line items while the card keeps `old.xlsx` → the not-both error on `block_bom`, no `chat_update`.
- [ ] **Edit items on an EPIF-born card** gets `block_keep_quotes` the same way, and unticking a quote there removes it from the metadata.
- [ ] **`bom.merge_attachments` and `bom.describe_attachment_changes`** are tested directly with the cases above, including "nothing changed" → `[]`.

**Tests may fake:** the Slack client, `slack_io.download_file`. **Must be real:** the view builders, both submit handlers, `bom.merge_attachments`, `bom.describe_attachment_changes`, `handle_request_edit`, `handle_items_update`.

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
