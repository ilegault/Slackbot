# 28: Line items on /new-purchase

**Status:** done

**Blocked by:** 27

**Spec:** `.scratch/bom-and-card-editing/spec.md` decision 3 (the modal path)
**Binding:** `docs/adr/0006-bom-line-items-and-editable-posted-cards.md` decisions 1, 2, 3, 4

## What to build

A lab member who has no EPIF yet runs `/new-purchase` and itemises their order
while filling in the interview. Screen 2 gains an optional **Line items** box
taking the same paste as ticket 27, with a hint showing the format and the
shipping line. Leave it empty and the interview behaves exactly as it does today.

Fill it in and the request posts to the purchasing channel already itemised: the
card names the line items, and a draft spreadsheet follows it into the thread.

## Notes

- The items text travels through the interview's carried state to Screen 3, which
  Slack caps at 3 000 characters. **The items box is capped at 1 500 characters so
  the carried state cannot overflow** — a requirement, not a preference: an
  overflow silently breaks the Fabrication-category path (Screen 3), which is the
  one hardest to notice in testing.
- Items are checked against the Total Price field on the same screen, so the
  request and its sheet can never disagree.
- Errors go back on the items box itself, not as a thread message.
- Storing the items and posting the draft spreadsheet must go through the handler
  ticket 27 built. No second implementation (invariant 1).

## Acceptance criteria

- [x] Screen 2 renders an optional multiline **Line items** input with a hint naming the format and the shipping line
- [x] An empty items box completes the interview exactly as before — no metadata key, no upload
- [x] A valid paste stores items and shipping in the posted card's metadata and names the line items on the card
- [x] Two or more items post a draft spreadsheet into the thread right after the card
- [x] A paste whose totals disagree with the Total Price field is refused on the items box, and no card is posted
- [x] A line-numbered parse error is shown on the items box, and no card is posted
- [x] The items box carries its own maximum length, and a request with a full box plus a Fabrication category still completes Screen 3 and posts
- [x] A one-item paste posts the card with no spreadsheet
- [x] `ruff check .`, `python scripts/check_tests_first.py` and `pytest -q` all pass

## Comments

### 2026-09-22 — Implementation complete

- Added `config.MAX_LINE_ITEMS_LEN = 1500` to `src/config.py` to bound Screen 2 line items and prevent Screen 3 carried `private_metadata` from exceeding Slack's 3,000-character ceiling.
- Updated `src/blocks.py`:
  - Added optional multiline `block_line_items` input to Screen 2 (`build_stage2_view`) with placeholder, label "Line items (optional)", format/shipping hint, and 1500-char limit.
- Updated `src/lifecycle.py`:
  - Extracted `upload_draft_bom(client, channel, thread_ts, parsed, items, shipping)` as single function for uploading draft BOM spreadsheets (invariant 1).
  - Used `upload_draft_bom` in `handle_items_update` and `_process_interview_completion`.
  - In `_process_interview_completion`: extracts line items and shipping, stores in message metadata, builds card blocks naming line items, and uploads draft BOM when `needs_bom` is True. Leaves metadata and thread untouched when empty.
- Updated `src/app.py`:
  - In `handle_stage2_submit`: extracts and parses `block_line_items`, validates per-line syntax errors, validates total against Total Price field, reports errors on `block_line_items` without posting, and carries raw text string in `stage2["line_items"]` across to Screen 3 without carrying bloated dict lists.
- Added tests in `tests/test_28_line_items_modal_path.py` (7 tests covering all criteria).
- Verified adversarial failure when checks broken.
- Full test suite passes: 333 passed, 31 skipped. Ruff and check_tests_first pass cleanly.
