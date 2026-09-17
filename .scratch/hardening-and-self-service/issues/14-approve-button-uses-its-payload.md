# 14: The Approve button uses the payload it was handed

**What to build:** Approving a request that came from `/new-purchase` logs
exactly the request shown on the card. The button already carries the complete
parsed request in its `value`; it stops throwing that away to go re-read Slack,
and the regex that rebuilt requests out of the bot's own prose is deleted.

**Blocked by:** 13

**Status:** done

**Read before starting:** `.scratch/lifecycle-and-buyers/spec.md` §1 and §3.8 —
they named this function a defect and ordered the prose-scraping branch deleted.
`docs/adr/0001-tests-first-and-no-muted-failures.md` is binding.

## Why

`handle_req_approve_action` reads `req_data` out of the button's `value` — the
complete parsed request, nineteen fields, exactly what the card is showing — and
then calls `lifecycle.handle_epif_processing()` **without it**. That function
looks for a PDF in the thread, and when there isn't one falls through to
`find_modal_request_in_thread`.

That function has two branches. The Slack `metadata` branch is structured and
correct. The other one matches `🛒 *New Purchase Request` and **rebuilds thirteen
fields with nine regexes over the bot's own summary text**, inventing
`vendor_contact_email = "sales@vendor.com"` along the way.

So a wording change to a summary message can corrupt a purchasing row, and a
request approved from the card is not necessarily the request that was on the card.

## Requirements, stated as requirements

1. **`handle_epif_processing` gains `posted_payload: dict | None`**, and the
   listener passes what it already parsed out of the button value.

2. **Resolution order becomes, exactly:** `direct_file` → a PDF found in the
   thread → `posted_payload` → the Slack `metadata` lookup → the "I couldn't find
   a PDF or purchase request" reply.

   The metadata lookup **stays**. The keyword path — `@Purchasing approved` typed
   into the thread of a card the modal posted — has no button payload, and that
   is the path it serves.

3. **Delete the regex branch of `find_modal_request_in_thread`.** The whole
   block: the `🛒 *New Purchase Request` match, the nine field regexes, and the
   invented vendor email. Keep the `metadata` branch and **rename the function
   `find_request_metadata_in_thread`**, so it stops claiming to parse prose.

4. **Narrow `slack_io.find_row_in_thread` to the bot's own wording.** It matches
   the bot's `Logged to row N` and stops matching bare `Row #N` in human prose,
   where it happily matched "Fund 133" and prices. It is reached only when no
   `req_data` carries the row.

5. **`CONTEXT.md` is not affected by this ticket.** Check before assuming; if a
   glossary entry names the old function, fix the name.

## Acceptance criteria

- [x] `handle_epif_processing` accepts `posted_payload` and resolves sources in
      the order in requirement 2
- [x] Approving a card posted by `/new-purchase` logs the item shown on that card,
      asserted by the **row values reaching `log_writer.build_row`** — not by
      asserting which lookup function ran
- [x] A thread containing a message whose text mimics the old
      `🛒 *New Purchase Request` summary but carries **no** metadata produces no
      request and no row
- [x] The string `sales@vendor.com` appears nowhere in `src/`
- [x] `find_modal_request_in_thread` appears nowhere in `src/`; the metadata branch
      survives as `find_request_metadata_in_thread` and a test covers it
- [x] The keyword path (`@Purchasing approved` in a modal-posted card's thread,
      no button payload) still resolves through metadata and still writes the row
- [x] `find_row_in_thread` returns no row for a thread containing `Fund 133` and a
      price, and does return the row for the bot's own `Logged to row 18` line
- [x] `ruff check .`, `python scripts/check_tests_first.py` and `pytest -q` all pass

## Out of scope

- **Deleting `find_row_in_thread` outright.** `.scratch/lifecycle-and-buyers/spec.md`
  §3.8 ordered it, but the keyword path has no other way to resolve a row without
  a request index. Narrow it here; deleting it waits for that effort.
- **Multi-EPIF batch intake.** `find_epif_in_thread` still returns only the first
  PDF and that bug is real — it is a ticket set of its own and this ticket must
  not start it.
- `src/store.py`. Invariant 3 is unchanged: the message is still the store.
- The buyer picker, which reads this same button value. Ticket 17.

## Comments

### 2026-09-17

- Added `posted_payload: dict | None = None` parameter to `lifecycle.handle_epif_processing`.
- Updated `app.handle_req_approve_action` to pass `posted_payload=req_data or None`.
- Structured resolution order in `handle_epif_processing`:
  `direct_file` -> PDF found in thread -> `posted_payload` -> Slack metadata lookup -> couldn't find reply.
- Deleted the regex prose-parsing branch in `slack_io` and renamed `find_modal_request_in_thread` to `find_request_metadata_in_thread`.
- Narrowed `slack_io.find_row_in_thread` to match only `Logged to row N`, removing bare row matching.
- Replaced placeholder in `src/blocks.py` so `sales@vendor.com` appears nowhere in `src/`.
- Removed unused `interview` import from `slack_io.py`.
- Added test suite `tests/test_14_approve_payload.py` with 9 tests covering all acceptance criteria and edge cases.
- Full gate passed cleanly:
  - `ruff check .` (clean)
  - `python scripts/check_tests_first.py` (clean)
  - `pytest -q --tb=short` (225 passed, 31 skipped)
