# 33: A corrected EPIF supersedes the old card

**Status:** done

**Blocked by:** 27

**Spec:** `.scratch/bom-and-card-editing/spec.md` decision 7
**Binding:** `docs/adr/0006-bom-line-items-and-editable-posted-cards.md` decision 9, `CONTEXT.md` (**Superseded**)

## What to build

Someone notices a wrong fund number on the EPIF they just posted, fixes it, and
uploads the corrected PDF into the same thread. Today that leaves two cards, each
with its own Approve button, and whichever Charlie happens to click decides what
gets logged.

After this ticket the older card becomes terminal: it keeps its summary so the
history is readable, loses every button, and reads
`Superseded by a newer EPIF below`. There is exactly one card to approve.

## Notes

- Only **posted** cards from the **same requester** for the **same vendor**
  (compared case-insensitively and trimmed) in that thread are superseded.
- An approved, processed, confirmed, delivered or cancelled card is **never**
  superseded — a real purchase must not be hidden by a stray upload.
- A second vendor's EPIF in the same thread supersedes nothing. One EPIF per
  vendor is the lab's rule and multi-vendor threads are normal.
- Line items do not carry across; the new card starts empty.

## Comments

2026-09-22 — Implemented by agent.

**What was built:**
- `build_request_blocks("superseded", ...)` in `blocks.py`: returns summary + history blocks (no buttons) plus a context block reading "Superseded by a newer EPIF below". Early-returns so the primary/secondary button logic is never reached.
- `slack_io.find_posted_cards_in_thread(client, channel, thread_ts, user_id, vendor)`: scans the thread for cards whose button value explicitly says `state="posted"`, matching user_id and vendor (case-insensitive, trimmed). Terminal-state cards (no button value) are never matched.
- `handle_epif_drop` in `lifecycle.py` (before `chat_postMessage`): calls `find_posted_cards_in_thread` and for each match calls `client.chat_update` with "superseded" blocks and an appended history line. Errors are logged as WARNING; the new card is always posted.
- Docstring updated with Per Ticket 33 section.

**Tests (21, all passing):**
- Same vendor + same requester: chat_update called, no buttons in result.
- Superseded card keeps summary text, has "Superseded by a newer EPIF below" context.
- New card posted with Approve button.
- Different vendor: chat_update NOT called (absence asserted).
- Different requester: chat_update NOT called.
- Approved card: NOT superseded.
- processed/confirmed/delivered states: NOT superseded (parametrized).
- Vendor comparison: case-insensitive ✓, whitespace-trimmed ✓.
- Line items do not carry to new card.
- `build_request_blocks("superseded")` unit tests: no buttons, context line, summary kept, history included.
- `find_posted_cards_in_thread` unit tests: returns match, excludes approved/wrong-vendor/wrong-user.

Gate: `ruff check .` ✓, `check_tests_first.py` ✓, `pytest -q` 378 passed 31 skipped ✓ (2 pre-existing Windows-only subprocess failures in `test_layering_and_isolation` also present on master).

## Acceptance criteria

- [x] A second EPIF for the same vendor from the same requester rewrites the older posted card with no buttons and a line saying it was superseded
- [x] The superseded card keeps its summary text
- [x] The new card is posted as usual with its own buttons
- [x] An EPIF for a different vendor in the same thread leaves the existing card untouched — asserted on the absence of a card update
- [x] An EPIF from a different requester leaves the existing card untouched
- [x] An approved card in the thread is never superseded, whatever is uploaded after it
- [x] Vendor comparison ignores case and surrounding whitespace
- [x] Line items on a superseded card do not appear on the new card
- [x] `ruff check .`, `python scripts/check_tests_first.py` and `pytest -q` all pass
