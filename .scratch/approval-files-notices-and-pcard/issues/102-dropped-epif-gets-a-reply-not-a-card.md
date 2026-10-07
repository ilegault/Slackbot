# 102: A dropped EPIF gets an "EPIF read" reply, not a card

**Status:** ready-for-agent

**Runner:** any

**Auto-merge:** yes

**Blocked by:** 100

**Spec:** `.scratch/approval-files-notices-and-pcard/spec.md` (Part A, stories 4–6 and 16)
**Binding:** `docs/adr/0015-approval-reads-the-card-or-the-threads-files-by-role.md` (decisions 3 and 6); `docs/adr/0010-linked-cards-and-direct-message-help.md` (decision 1, every approval leaves a card); ADR 0001
**Glossary:** `CONTEXT.md` — **Request**, **Superseded**, **Edit**

**Deletes tests:** tests/test_33_epif_supersedes_old_card.py::test_same_vendor_same_requester_supersedes_older_card, tests/test_33_epif_supersedes_old_card.py::test_superseded_card_keeps_summary_text, tests/test_33_epif_supersedes_old_card.py::test_superseded_card_has_context_line, tests/test_33_epif_supersedes_old_card.py::test_new_card_is_posted_with_approve_button, tests/test_33_epif_supersedes_old_card.py::test_vendor_comparison_case_insensitive, tests/test_33_epif_supersedes_old_card.py::test_vendor_comparison_trims_whitespace, tests/test_33_epif_supersedes_old_card.py::test_line_items_do_not_carry_to_new_card, tests/test_93_posted_cards_logged.py::test_epif_drop_posting_creates_entry, tests/test_93_posted_cards_logged.py::test_supersede_flags_old_entry_and_new_card_gets_own, tests/test_onboarding_and_commands.py::test_pdf_drop_in_thread_produces_posted_card_with_approve_button, tests/test_onboarding_and_commands.py::test_pdf_drop_payload_built_where_pdf_parsed, tests/test_27_line_items_epif_path.py::test_dropped_epif_sets_source_epif, tests/test_65_loud_card_failures.py::test_dropped_epif_card_post_failure_alerts

## What to build

Today `lifecycle.handle_epif_drop` parses a dropped EPIF and posts a **posted** card with
Approve / Decline. Before it posts, it supersedes older cards
(`slack_io.find_posted_cards_in_thread` → "Superseded" update) and creates a request-log entry
(`_log_posted_card`). After this ticket a dropped EPIF posts **no card**. The card appears
when an approver types `@Purchasing approved`. `finalize_purchase_request` already posts an
approved card when the thread has none, and already creates the request-log entry at
approval when none exists.

In `lifecycle.handle_epif_drop`, keep the download, the parse, and the existing parse-failure
handling (the "epif"-in-name loud error and the silent ignore of other PDFs). Then:

1. Run `validators.validate(parsed, requester_name=requester)`.
2. If there are no problems, post one thread reply with no `blocks`, exactly:
   `📄 EPIF read: *{item}* — {vendor}, {price}. Waiting for approval.`
   `{price}` is formatted as the function formats `price_str` today (`$2,520.00`).
3. If there are problems, post one thread reply:
   `📄 I read *{file_name}* but it can't be approved yet:` followed by one line
   `  • {problem}` per problem. Also send the same text to the uploader by
   `slack_io.tell(client, user_id, ...)`.
4. Remove from this function: the superseding loop, the card `chat_postMessage`, and the
   `_log_posted_card` call. Leave `blocks.build_request_blocks("superseded", ...)`,
   `slack_io.find_posted_cards_in_thread` and the PDF-born **Add items** / **Edit** handlers in
   place. Cards posted before this change still use them.

## Acceptance criteria

- [ ] New `tests/test_102_drop_reply_no_card.py`: dropping a valid EPIF (the real `tests/fixtures/EPIF_TEMPLATE_HIRST.pdf` filled through `epif_filler.fill_epif`, or a faked `parse_epif` returning a valid dict) posts exactly one `chat_postMessage` with the exact `EPIF read` text and **no** `blocks` argument. `chat_update` is never called, and the request log (`store`) has no entry afterwards.
- [ ] Dropping an EPIF whose parsed dict fails validation (e.g. blank vendor) posts the "can't be approved yet" reply with that problem's bullet, and DMs the uploader the same text. Assert the DM's `channel` is the uploader's id.
- [ ] A thread with an older posted card from the same uploader and vendor: after a drop, `chat_update` is never called. The old card is left as it is.
- [ ] End to end: drop an EPIF, then call the `@Purchasing approved` path (`handle_epif_processing` as the mention handler calls it). Exactly one card is posted, in the `approved` state, a row is written on the temp workbook, and the request log now has one entry with `approved_at` set. Use the `temp_workbook` and `sync_queue` fixtures.
- [ ] `tests/test_onboarding_and_commands.py::test_pdf_request_walks_from_posted_to_delivered_with_excel_writes` is rewritten **in place, same name**: drop → keyword approve → processed → confirmed → delivered, with the same Excel assertions as today.

May fake: the Slack client, downloads, `resolve_requester`. Must be real: `handle_epif_drop`, `validators.validate`, the store on its isolated temp path (`conftest.isolate_store_path`), the workbook write on a temp copy.

## Gate

Run all four, in CI's order, and all must pass:

    ruff check .
    python scripts/check_tests_first.py
    python tools/type_gate.py
    pytest --tb=short -q -n auto --dist loadfile

Tests need `SLACK_BOT_TOKEN=xoxb-test-not-a-real-token`, `SLACK_APP_TOKEN=xapp-test-not-a-real-token` and `PYTHONUTF8=1` in the environment, as `.github/workflows/tests.yml` sets.

## Comments
