# 81: Quotes field on /new-purchase

**Status:** done

**Runner:** any

**Auto-merge:** yes

**Blocked by:** None (can start immediately)

**Spec:** `.scratch/attached-boms-and-quotes/spec.md`
**Binding:** `docs/adr/0012-attached-boms-and-quotes-are-carried-not-read.md` decisions 1, 2, 5; `docs/adr/0006-bom-line-items-and-editable-posted-cards.md` decision 5; ADR 0001

## What to build

A requester filling in `/new-purchase` can attach vendor quote PDFs on Screen 2. When the
card is posted, the quotes are re-posted into the card's thread so the approver sees them,
and the card summary says how many there are. The bot never opens the PDFs. If a file can't
be fetched from Slack, nobody is left guessing: the thread says so and the requester gets a DM.

1. `src/blocks.py` `build_stage2_view`: **only when `meta["is_edit"]` is false**, add after the
   line-items block an optional `input` block, `block_id` `block_quotes`, element
   `{"type": "file_input", "action_id": "quotes", "filetypes": ["pdf"], "max_files": 10}`,
   label `Quotes (PDF, optional)`, hint `Up to 10. More? Drop them in the thread with @Purchasing quote.`
   Put the block in a small builder `blocks.quotes_input()` so tickets 85 and 86 reuse it.
2. `src/text_rules.py`: new pure function `extract_modal_files(values, block_id, action_id) -> list[dict]`
   returning `[{"id": f["id"], "name": f["name"][:80]}, ...]` from
   `values[block_id][action_id]["files"]`, or `[]` when the block, action or `files` is absent.
3. `src/app.py` `handle_stage2_submit`: put
   `[{"role": "quote", **f} for f in extract_modal_files(values, "block_quotes", "quotes")]` in
   `stage2["attachments"]` when non-empty. It already rides into Screen 3 via `meta["stage2"]`.
4. `src/lifecycle.py` `_process_interview_completion`: copy `stage2["attachments"]` into
   `req_payload["attachments"]` (the card metadata `event_payload`, like `items`). In
   `src/blocks.py` `build_request_blocks`, add `"attachments"` to the keys stripped from
   `safe_req` (beside `"items"`, `"shipping"`) so it never enters a button value. Add the
   summary line `📎 Quotes: N` after the items line.
5. `src/lifecycle.py`: new `post_attachments_to_thread(client, channel, thread_ts, attachments, requester_id) -> list[str]`.
   For each attachment: `client.files_info(file=a["id"])["file"]` → `slack_io.download_file(...)`
   → `files_upload_v2(channel=, thread_ts=, content=, filename=a["name"], title=a["name"])`
   (mirror `upload_draft_bom`). On any exception for one file: post
   `⚠️ Couldn't attach \`<name>\` — drop it in the thread with \`@Purchasing quote\`.` in the
   thread, send the same text to `requester_id` with `slack_io.tell`, log a warning, and carry
   on with the next file. Returns the names that failed. Call it from
   `_process_interview_completion` right after the card is posted (thread = `card_ts`).

## Acceptance criteria

New test file `tests/test_81_quotes_on_new_purchase.py`. Drive `app.handle_stage2_submit` (and
`app.handle_stage3_submit` for the Fabrication case) with view payloads built like
`tests/test_28_line_items_modal_path.py`, including
`state.values.block_quotes.quotes = {"type": "file_input", "files": [{"id": "F1", "name": "a.pdf", ...}]}`.

- [x] **The field.** `blocks.build_stage2_view(meta)` contains a block with `block_id == "block_quotes"`, `optional` true, element type `file_input`, `filetypes == ["pdf"]`, `max_files == 10`; with `meta["is_edit"] = True` there is no `block_quotes` block.
- [x] **Two quotes posted.** Submitting with files F1 `a.pdf` and F2 `b.pdf` posts the card whose `metadata.event_payload["attachments"] == [{"role": "quote", "id": "F1", "name": "a.pdf"}, {"role": "quote", "id": "F2", "name": "b.pdf"}]`; no button `value` on the card contains the string `attachments`; the card text contains `Quotes: 2`; then exactly two `files_upload_v2` calls with `thread_ts` = the card's `ts`, filenames `a.pdf` and `b.pdf`, and `content` equal to the fake download bytes.
- [x] **Survives Screen 3.** Same files with a Fabrication category (Screen 3 shown), then Screen 3 submitted → the posted card's `attachments` holds both entries.
- [x] **A failed download is loud, not silent.** `slack_io.download_file` raising for F2 only → `a.pdf` is uploaded; one thread post containing ``Couldn't attach `b.pdf` ``; one DM to the requester's ID with the same text; the card is still posted.
- [x] **No files, no change.** Submitting without `block_quotes` in the state → the card payload has no `attachments` key and `files_info` / `files_upload_v2` are never called.

**Tests may fake:** the Slack client (`files_info`, `files_upload_v2`, `chat_postMessage`), `slack_io.download_file`. **Must be real:** `blocks`, the submit handlers, `lifecycle._process_interview_completion`, `lifecycle.post_attachments_to_thread`, the roster on a temp file.

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

### Completed (2026-10-05)
- Added `blocks.quotes_input()` and integrated into `blocks.build_stage2_view` when `not is_edit`.
- Added `text_rules.extract_modal_files` extracting id and name (truncated to 80 chars) from modal values.
- Updated `app.handle_stage2_submit` to put quote attachments into `stage2["attachments"]`.
- Updated `blocks.build_request_blocks` to strip `"attachments"` from `safe_req` (preventing leakage into button values) and render the summary line `📎 Quotes: N`.
- Updated `lifecycle._process_interview_completion` to copy attachments to `req_payload["attachments"]` and call `post_attachments_to_thread`.
- Added `lifecycle.post_attachments_to_thread` downloading attachments and uploading them to the request thread via `files_upload_v2`, loudly alerting thread and requester DM on any download failure.
- Created `tests/test_81_quotes_on_new_purchase.py` covering all 5 criteria with real handlers, blocks, and temporary roster.
