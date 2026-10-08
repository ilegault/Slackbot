# 103: Quotes and a BOM dropped in the thread go with the request at approval

**Status:** done

**Claimed-by:** box

**Runner:** any

**Auto-merge:** yes

**Blocked by:** 100, 101

**Spec:** `.scratch/approval-files-notices-and-pcard/spec.md` (Part A, stories 8–11 and 15)
**Binding:** `docs/adr/0015-approval-reads-the-card-or-the-threads-files-by-role.md` (decision 4); `docs/adr/0012-attached-boms-and-quotes-are-carried-not-read.md` (decisions 2 and 5); ADR 0001
**Glossary:** `CONTEXT.md` — **Thread files at approval**, **Quote**, **BOM**

## What to build

At `@Purchasing approved` in a thread with **no posted card** and **exactly one EPIF**, the bot
takes the person-posted quotes and BOM in the thread along with the EPIF. They are archived and
sent to the buyer through the code that already handles form-attached files: the
`attachments` list of `{"id", "name", "role"}` dicts that `finalize_purchase_request`
splits into `attached_boms` / `attached_quotes`.

1. `src/slack_io.py` — new function `thread_files(client, channel, thread_ts) -> dict`. It
   fetches the replies and returns `classify_thread_files(...)` (from ticket 100) with the same
   `bot_user_id` and `read_fields` that `find_epif_in_thread` uses. `find_epif_in_thread` is
   reimplemented on top of it, with unchanged behaviour.
2. `src/lifecycle.py` `handle_epif_processing`, on the thread-PDF path when it was reached by
   the keyword (no `card_ts`, no `posted_payload`, no `direct_file`), and `attachments is
   None`:
   - If `len(files["boms"]) > 1`: post one thread reply, exactly
     `One BOM per EPIF — delete the extra and approve again: ` followed by the BOM file names,
     each in backticks and joined by `, `. Write no row and return.
   - Otherwise set `attachments` to one dict per BOM (`"role": "bom"`) and per quote
     (`"role": "quote"`), oldest first, with `"id"` and `"name"` taken from the Slack file
     object. Then continue to `finalize_purchase_request` as today.
3. Bare-thread approvals (no EPIF found) are unchanged.

## Acceptance criteria

- [x] New `tests/test_103_thread_files_at_approval.py`. A thread holds a person's EPIF, a person's form-less `Quote_A.pdf`, and a person's `order.xlsx` (real bytes for each). Keyword approval writes the row, the temp `QUOTES_DIR` holds `bom.quote_filename(row, vendor, 1)`, the temp `BOMS_DIR` holds the archived BOM with the `.xlsx` extension, and the BOM file is byte-identical to what was posted (carried, not read). Copy the folder setup from `tests/test_83_approval_archives_attachments.py`.
- [x] Two BOM files in the thread: the exact refusal text is posted with both names, no row is written (the workbook row count is unchanged), and nothing is archived.
- [x] A `.png` screenshot in the thread is not archived, and the attachments passed to `finalize_purchase_request` contain no entry for it.
- [x] A quote posted on a `<@BOT> quote` message is not archived a second time at approval. Exactly one file exists in the temp `QUOTES_DIR` for it: the one `handle_quote` saved.
- [x] A bot-posted PDF in the thread is not archived as a quote.

May fake: the Slack client, downloads (return fixture bytes), `resolve_requester`. Must be real: `classify_thread_files`, `finalize_purchase_request`, the archive writes into temp folders, the workbook write on a temp copy.

## Gate

Run all four, in CI's order, and all must pass:

    ruff check .
    python scripts/check_tests_first.py
    python tools/type_gate.py
    pytest --tb=short -q -n auto --dist loadfile

Tests need `SLACK_BOT_TOKEN=xoxb-test-not-a-real-token`, `SLACK_APP_TOKEN=xapp-test-not-a-real-token` and `PYTHONUTF8=1` in the environment, as `.github/workflows/tests.yml` sets.

## Comments

2026-10-08:
Implemented thread quotes and BOM collection on keyword approval (`@Purchasing approved`) for threads with no posted card and an EPIF (ADR 0015 decision 4, ADR 0012 decisions 2 & 5):
- Added `slack_io.thread_files(client, channel, thread_ts)` to fetch and classify thread files; reimplemented `slack_io.find_epif_in_thread` on top of it.
- Updated `lifecycle.handle_epif_processing` on the thread-PDF keyword path:
  - If `len(files["boms"]) > 1`: replies with "One BOM per EPIF — delete the extra and approve again: `...`", writing no row and archiving nothing.
  - Otherwise, attaches thread BOMs and quotes as `attachments` (`role="bom"` and `role="quote"`), sorted oldest first, proceeding to `finalize_purchase_request`.
- Bare-thread approval path remains unchanged when no EPIF is found.

Tests in `tests/test_103_thread_files_at_approval.py`:
- `test_thread_files_archived_at_keyword_approval`: covers criterion 1 (person's EPIF, formless quote, xlsx BOM archived byte-for-byte in temp dirs, notes updated, row written).
- `test_two_boms_in_thread_refused_no_row_written`: covers criterion 2 (two BOMs refused with exact text, no row written, nothing archived).
- `test_screenshot_png_in_thread_not_archived`: covers criterion 3 (.png ignored, not archived, absent from attachments).
- `test_quote_on_bot_quote_message_not_archived_again`: covers criterion 4 (quote from @BOT quote not duplicated at approval).
- `test_bot_posted_pdf_not_archived_as_quote`: covers criterion 5 (bot-posted PDF skipped and not archived as quote).
- `test_thread_files_and_find_epif_in_thread_delegation`: unit test covering `thread_files` classification and `find_epif_in_thread` delegation.
All 6 new tests and full 756 test suite pass; ruff, type gate, check_tests_first all green.

