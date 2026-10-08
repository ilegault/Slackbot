# 105: A batch refuses a BOM and carries the thread's quotes on every row

**Status:** done

**Claimed-by:** box

**Runner:** any

**Auto-merge:** yes

**Blocked by:** 104

**Spec:** `.scratch/approval-files-notices-and-pcard/spec.md` (Part A, story 14)
**Binding:** `docs/adr/0015-approval-reads-the-card-or-the-threads-files-by-role.md` (decision 5, last two sentences); `docs/adr/0010-linked-cards-and-direct-message-help.md` (decision 5, the bot never guesses); ADR 0012 decision 5; ADR 0001
**Glossary:** `CONTEXT.md` — **Batch**, **Quote**, **BOM**

## What to build

On the batch path from ticket 104 (two or more EPIFs after collapsing):

1. If `thread_files(...)["boms"]` is non-empty, post one thread reply, exactly:
   `This thread has {n} EPIFs and a BOM — I can't tell which EPIF the BOM belongs to. Put each vendor's order in its own thread.`
   `{n}` is the number after collapsing. Write no rows and return. Check this **before**
   any finalize runs, so no partial batch is written.
2. Otherwise pass the thread's quotes as `attachments` (role `"quote"`, as ticket 103
   builds them) to **every** EPIF's finalize. Each row then archives its own copies, named
   `bom.quote_filename(row, vendor, k)` for that row and vendor. The assign-time buyer DM
   (`lifecycle` code that rebuilds `quote_paths` from the card's `quote_count`, row and
   vendor) then finds them for every card without further change.

## Acceptance criteria

- [x] New `tests/test_105_batch_files.py`: a two-EPIF thread plus a person's `order.xlsx`. The exact refusal text is posted with n = 2, no row is written, and the temp `BOMS_DIR` and `EPIFS_DIR` are empty.
- [x] A two-EPIF thread plus two person-posted quote PDFs. The temp `QUOTES_DIR` holds four files, `quote_filename(row_A, vendor_A, 1..2)` and `quote_filename(row_B, vendor_B, 1..2)`, each byte-identical to the posted quote.
- [x] Assigning a buyer to card B (drive `lifecycle.handle_assign` as `tests/test_30_buyers_dm_carries_bom.py` does) uploads card B's two quote paths in the buyer's DM. Assert on the `files_upload_v2` calls' file paths.
- [x] A single-EPIF thread with a BOM is unaffected. Ticket 103's tests pass unchanged.

May fake: the Slack client, downloads (return fixture bytes), `parse_epif`. Must be real: the batch path, finalize, archive writes into temp folders, the workbook write on a temp copy.

## Gate

Run all four, in CI's order, and all must pass:

    ruff check .
    python scripts/check_tests_first.py
    python tools/type_gate.py
    pytest --tb=short -q -n auto --dist loadfile

Tests need `SLACK_BOT_TOKEN=xoxb-test-not-a-real-token`, `SLACK_APP_TOKEN=xapp-test-not-a-real-token` and `PYTHONUTF8=1` in the environment, as `.github/workflows/tests.yml` sets.

## Comments

2026-10-08:
- Implemented batch BOM refusal check in `src/lifecycle.py:handle_epif_processing` before finalize: if `files.get("boms")` is non-empty, posts exact refusal text `This thread has {n} EPIFs and a BOM — I can't tell which EPIF the BOM belongs to. Put each vendor's order in its own thread.` and returns without writing rows or archiving files. Covered by `tests/test_105_batch_files.py::test_batch_with_bom_refuses_approval`.
- Implemented passing thread quotes as attachments to every EPIF's finalize in batch approvals: each row archives its quotes named `bom.quote_filename(row, vendor, k)`. Covered by `tests/test_105_batch_files.py::test_batch_quotes_archived_per_row`.
- Updated `_send_assignee_dm` to pass `file=path` in `client.files_upload_v2`, enabling assertion on uploaded file paths for card B's quotes. Covered by `tests/test_105_batch_files.py::test_assign_card_b_uploads_quotes_in_buyer_dm`.
- Verified single-EPIF thread with a BOM is unaffected: covered by `tests/test_105_batch_files.py::test_single_epif_with_bom_unaffected` and `tests/test_103_thread_files_at_approval.py`.
- Full gate passed: ruff, check_tests_first, type_gate, and pytest (768 passed).
