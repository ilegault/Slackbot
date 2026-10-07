# 99: The Approve button approves the card it is on

**Status:** in-progress

**Runner:** any

**Auto-merge:** yes

**Blocked by:** None (can start immediately)

**Spec:** `.scratch/approval-files-notices-and-pcard/spec.md` (Part A, stories 1–3)
**Binding:** `docs/adr/0015-approval-reads-the-card-or-the-threads-files-by-role.md` (decision 1); `docs/adr/0012-attached-boms-and-quotes-are-carried-not-read.md` (decision 2); ADR 0001
**Glossary:** `CONTEXT.md` — **Quote**, **Posted**, **Request**

## What to build

This is a live production bug. A requester submits `/new-purchase` with a quote PDF in the
Quotes field. The bot re-posts the quote in the thread (`lifecycle.post_attachments_to_thread`).
When the approver presses **Approve**, `src/app.py` `handle_req_approve_action` calls
`lifecycle.handle_epif_processing(..., posted_payload=req_data, card_ts=msg_ts)`. That function
calls `slack_io.find_epif_in_thread` **before** it looks at `posted_payload`, finds the quote,
tries to parse it as an EPIF, fails with "This PDF has no fillable form fields…", and approves
nothing.

Change `lifecycle.handle_epif_processing` so that when `card_ts` or `posted_payload` is given,
`slack_io.find_epif_in_thread` is **not called** and the request comes from the card (the
existing "Button Action Payload Path" in the same function). Two exceptions keep working:
`direct_file` still comes first, and a payload whose `source == "epif"` (a card posted from a
dropped EPIF before this change, which carries no file reference) still uses
`find_epif_in_thread`. Rewrite the function's docstring resolution order to match.

## Acceptance criteria

- [ ] New test in a new file `tests/test_99_approve_uses_its_card.py`: drive `app.handle_req_approve_action` with a fake client whose `conversations_replies` returns the thread parent, a `/new-purchase` card, and a **bot-posted** message carrying a PDF named `Quote 27732 University of Wisconsin.pdf`. The PDF bytes are a real PDF with no form fields, built in the test with `pypdf.PdfWriter()` + `add_blank_page(...)` — not a mocked parser. Assert a row is written with the card's item, vendor and total (use the `temp_workbook` / `sync_queue` fixtures as `tests/test_40_bare_thread_approval.py::test_scenario_end_to_end` does), and that no `chat_postMessage` text starts with `Error processing`.
- [ ] Same test: wrap `epif_parser.read_fields` in a spy that calls the real function, and assert it was **never** called. The quote is carried, not read. Also assert the quote is still archived as ADR 0012 decision 5 requires: the card's metadata lists it as an attachment with `"role": "quote"`, and after approval the temporary `QUOTES_DIR` holds `bom.quote_filename(row, vendor, 1)`.
- [ ] `tests/test_14_approve_payload.py::test_handle_epif_processing_resolution_order` is rewritten **in place, same name**. Its case 2 ("PDF in thread beats posted_payload") now asserts that `posted_payload` wins and `find_epif_in_thread` is not called. Cases 1 (direct_file first) and 3 (payload beats metadata) are unchanged.
- [ ] New test: a payload with `"source": "epif"` and a thread holding an EPIF still approves from the thread PDF (a legacy dropped-EPIF card). It may fake `epif_parser.parse_epif` here, as `test_14` does.
- [ ] The docstring of `handle_epif_processing` lists the new order: direct_file → card/posted_payload (thread searched only for `source == "epif"`) → PDF in thread → metadata lookup → bare thread.

May fake: the Slack client, `slack_io.resolve_requester`, the lock queue via `sync_queue`. Must be real: `handle_epif_processing`, `finalize_purchase_request`, `validators.validate`, the workbook write on the temp copy.

## Gate

Run all four, in CI's order, and all must pass:

    ruff check .
    python scripts/check_tests_first.py
    python tools/type_gate.py
    pytest --tb=short -q -n auto --dist loadfile

Tests need `SLACK_BOT_TOKEN=xoxb-test-not-a-real-token`, `SLACK_APP_TOKEN=xapp-test-not-a-real-token` and `PYTHONUTF8=1` in the environment, as `.github/workflows/tests.yml` sets.

## Comments
