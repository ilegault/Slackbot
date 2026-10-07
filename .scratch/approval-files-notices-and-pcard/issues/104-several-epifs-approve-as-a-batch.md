# 104: Several EPIFs in a thread approve as a batch

**Status:** ready-for-agent

**Runner:** any

**Auto-merge:** yes

**Blocked by:** 102, 103

**Spec:** `.scratch/approval-files-notices-and-pcard/spec.md` (Part A, stories 12–13)
**Binding:** `docs/adr/0015-approval-reads-the-card-or-the-threads-files-by-role.md` (decision 5, first two sentences); `docs/adr/0003-decline-and-cancel.md` (decision 7, a batch cancels as a batch); ADR 0001
**Glossary:** `CONTEXT.md` — **Batch**, **Superseded**

## What to build

Today the keyword path takes one PDF. After this ticket, at `@Purchasing approved` in a thread
with no posted card:

1. Collapse `thread_files(...)["epifs"]`. Parse each with `epif_parser.parse_epif`. For EPIFs
   with the same `(user, parsed["vendor"].strip().lower())`, keep only the newest by `ts`.
2. One EPIF left: today's path (ticket 103), unchanged.
3. Two or more left: run the existing per-EPIF finalize once for each, oldest first. Each
   writes its own row and posts its **own** approved card. Each archives its own EPIF. In this
   ticket a batch carries **no** thread quotes or BOM (`attachments=[]`); ticket 105 adds them.
4. `finalize_purchase_request` today updates "the" card in the thread (`find_card_in_thread`
   → `target_card_ts`), so the second EPIF would overwrite the first card. Add a keyword-only
   parameter `new_card: bool = False`. When it is True, the found card is ignored and a fresh
   approved card is posted. Only the batch path passes `new_card=True`.
5. Each EPIF's "Logged to row N" reply is posted as today, so the existing batch cancel
   (`slack_io.find_all_rows_in_thread` in `handle_cancel`) blanks every row.

## Acceptance criteria

- [ ] New `tests/test_104_batch_approval.py`: a thread with EPIFs for vendors A and B from one uploader. Keyword approval writes two rows (vendors A and B) to the temp workbook and posts two approved cards, each showing its own vendor. Assert on the `chat_postMessage` calls carrying `blocks`.
- [ ] A thread with two EPIFs from the same uploader for vendor A (older total $10, newer total $20) writes **one** row with total 20.00.
- [ ] The same vendor from two **different** uploaders is not collapsed: two rows.
- [ ] Cancel on either card of a two-EPIF batch blanks both rows. Drive `handle_cancel` as `tests/test_05_decline_cancel.py` does, on the temp workbook.
- [ ] A single-EPIF thread still posts exactly one card, and `finalize_purchase_request` called without `new_card` still updates an existing thread card in place (the existing tests in `tests/test_14_approve_payload.py` and `tests/test_40_bare_thread_approval.py` pass unchanged).

May fake: the Slack client, downloads, `epif_parser.parse_epif` (return per-file dicts). Must be real: the collapse, `finalize_purchase_request`, the workbook writes and the blanking on a temp copy.

## Gate

Run all four, in CI's order, and all must pass:

    ruff check .
    python scripts/check_tests_first.py
    python tools/type_gate.py
    pytest --tb=short -q -n auto --dist loadfile

Tests need `SLACK_BOT_TOKEN=xoxb-test-not-a-real-token`, `SLACK_APP_TOKEN=xapp-test-not-a-real-token` and `PYTHONUTF8=1` in the environment, as `.github/workflows/tests.yml` sets.

## Comments
