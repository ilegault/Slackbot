# 101: `@Purchasing approved` approves a posted card in the thread

**Status:** in-progress

**Claimed-by:** box

**Runner:** any

**Auto-merge:** yes

**Blocked by:** 99

**Spec:** `.scratch/approval-files-notices-and-pcard/spec.md` (Part A, story 7)
**Binding:** `docs/adr/0015-approval-reads-the-card-or-the-threads-files-by-role.md` (decisions 1 and 4, first sentence); AGENTS.md invariant 1; ADR 0001
**Glossary:** `CONTEXT.md` — **Posted**, **Request**

## What to build

The keyword and the button must approve the same thing. Today `@Purchasing approved` reaches
`lifecycle.handle_epif_processing` with no `card_ts` and no `posted_payload`. The function
searches the thread for a PDF first and only then finds the `/new-purchase` card through
`slack_io.find_request_metadata_in_thread`. So a re-posted quote still derails the keyword.

In `lifecycle.handle_epif_processing`: when neither `card_ts` nor `posted_payload` nor
`direct_file` is given, call `slack_io.find_card_in_thread(client, channel, thread_ts)` first.
If it returns a card whose state is `"posted"`, set `card_ts` to that card's ts and
`posted_payload` to its request. From there take exactly the path ticket 99 made for the
button. Do not search the thread for a PDF. The logic lives in `lifecycle` (not in the
`src/app.py` mention handler) so the button and the keyword share one implementation.

## Acceptance criteria

- [ ] New test in `tests/test_101_keyword_approves_posted_card.py`: the thread holds a `/new-purchase` card in the `posted` state and a bot-posted form-less quote PDF (real bytes from `pypdf.PdfWriter`). Calling `handle_epif_processing` as the mention handler does writes a row with the card's item, vendor and total. No `Error processing` text is posted.
- [ ] Same setup: the card is updated in place to the `approved` state. Assert `chat_update` was called with `ts` = the card's ts, and no second card was posted with `chat_postMessage` + `blocks`.
- [ ] A thread with a posted card **and** a person's dropped EPIF approves the card. Assert the row's vendor is the card's, not the EPIF's.
- [ ] `tests/test_14_approve_payload.py::test_keyword_path_approves_via_metadata_lookup` still passes unchanged.

May fake: the Slack client, `resolve_requester`. Must be real: `handle_epif_processing`, `finalize_purchase_request`, the workbook write on a temp copy (`temp_workbook`, `sync_queue`).

## Gate

Run all four, in CI's order, and all must pass:

    ruff check .
    python scripts/check_tests_first.py
    python tools/type_gate.py
    pytest --tb=short -q -n auto --dist loadfile

Tests need `SLACK_BOT_TOKEN=xoxb-test-not-a-real-token`, `SLACK_APP_TOKEN=xapp-test-not-a-real-token` and `PYTHONUTF8=1` in the environment, as `.github/workflows/tests.yml` sets.

## Comments
