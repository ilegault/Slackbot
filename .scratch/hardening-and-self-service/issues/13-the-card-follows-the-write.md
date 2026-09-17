# 13: The card follows the write, not the click

**What to build:** A card advances a stage only once the workbook write actually
landed. Mark Processed stops saying "Processed" when nothing was written, and an
approval that fails validation leaves the card reading exactly what it read
before.

**Blocked by:** 12

**Status:** done

**Read before starting:** `docs/adr/0002-request-lifecycle-and-surfaces.md` —
specifically what it means by the workbook being the final reference.
`docs/adr/0001-tests-first-and-no-muted-failures.md` is binding. `CONTEXT.md` has
the vocabulary.

## Why

Every button listener runs `chat_update` unconditionally after calling its
lifecycle handler. On approval that is a **second** render racing the correct one
— `finalize_purchase_request.on_success` already updates the card properly. On
Mark Processed, Mark Confirmed and Mark Delivered it is the **only** render, and
it lies: the card says Processed whether or not column U ever got a date.

So the channel can say a purchase is logged when no row exists, and say an order
was processed when the workbook write failed. Excel is supposed to be the final
reference. Right now the card is a rumour.

## Starting state — the model already exists

`finalize_purchase_request.on_success` renders the card correctly today, locating
it with `slack_io.find_card_in_thread`. `lifecycle.handle_cancel` already returns
a bool and renders its own terminal card. **Nothing about card rendering needs
inventing.** This ticket brings the other three handlers into line with the two
that are already right, and deletes the racing duplicate.

`src/app.py` contains 7 `chat_update` calls. After this ticket it contains none.

## Requirements, stated as requirements

1. **Three handlers gain three parameters.** `lifecycle.handle_processed`,
   `handle_confirmation` and `handle_delivery` each take `card_ts`, `req_data` and
   `history`, and each renders the card **inside its own `on_success`**.

2. **The history line moves with the render.** Today the listener appends
   "Processed by X on …" before calling the handler, so the line is written whether
   or not anything was. The handler appends it in `on_success` instead. One line
   per successful transition — not two, not zero.

3. **A refusal branch touches nothing.** A handler that cannot identify a row, or
   has nothing to write, posts its existing "couldn't figure out which order"
   reply and **returns without rendering the card at all**.

4. **`handle_req_approve_action` stops rendering.** Delete its unconditional
   `chat_update`. `finalize_purchase_request.on_success` was already doing this
   job correctly, a background thread's worth of time later.

5. **Every `chat_update` leaves `src/app.py`.** After this ticket the string
   appears nowhere in that file. A source scan asserts it, so a future listener
   cannot advance a card on a failed write.

6. **Do not change `handle_cancel`.** It is the model the others are being brought
   in line with.

7. **Accepted consequence, stated so nobody "fixes" it later:** when
   `Purchasing-Log.xlsx` is open on somebody's desktop, the card stays on the
   previous stage until the lock queue drains. That is the truth. The queue already
   messages the thread about a delayed write; **no second "pending" state is added
   to the card.**

8. **`AGENTS.md` §2 is corrected in this ticket, not in a cleanup pass.** It still
   says `blocks`, `handlers` and `listeners` are all inside one 2 855-line
   `src/app.py` that ticket 01 will split. Ticket 01 landed; `src/app.py` is ~1 170
   lines and the layers are split. Trap 8's "sixteen modified files uncommitted" is
   also stale. Fix both.

## Acceptance criteria

- [x] `handle_processed`, `handle_confirmation` and `handle_delivery` each accept
      `card_ts`, `req_data` and `history`, and render the card inside `on_success`
- [x] A `handle_processed` call that cannot identify a row posts its reply and
      calls `chat_update` **not at all** — assert on the absence
- [x] A `handle_processed` whose queued write fails: the thread gets the error and
      the card still reads `approved` — asserted on the rendered blocks, not a flag
- [x] A successful `handle_processed`: the card reads `processed` and history
      gained **exactly one** line
- [x] The same three criteria hold for `handle_confirmation` and `handle_delivery`
- [x] An approval whose EPIF fails validation writes no row and leaves the card on
      its previous state — asserted on the blocks
- [x] A test with the workbook locked asserts the card stays on the previous stage
      and the thread carries the delayed-write message
- [x] `chat_update` appears nowhere in `src/app.py` (source scan)
- [x] `handle_cancel` is unchanged and its existing tests still pass untouched
- [x] `AGENTS.md` §2 and §9 trap 8 describe the repo as it is
- [x] `ruff check .`, `python scripts/check_tests_first.py` and `pytest -q` all pass

## Out of scope

- Any change to the queue's retry or messaging behaviour.
- A "pending" or "writing…" card state. Requirement 7.
- `handle_cancel`. Requirement 6.
- The Approve button's payload handling — that is ticket 14, which edits the same
  listener immediately after this one.

## Comments

### 2026-09-17 — Ticket 13 implementation complete
- Added `card_ts`, `req_data`, and `history` parameters to `lifecycle.handle_processed`, `handle_confirmation`, and `handle_delivery`.
- Moved card update rendering and history line appending inside each write's `on_success` callback in `src/lifecycle.py`.
- Moved alert button channel message updates out of `src/app.py` into dedicated handler functions in `src/ops.py` (`handle_approve_new_requester`, `handle_approve_new_admin`, `handle_approve_new_vendor`).
- Removed all `chat_update` calls from `src/app.py` (source scan asserts 0 occurrences).
- Added `tests/test_13_card_follows_write.py` with 12 tests validating card behaviour on write success, write failure, refusal/missing row, locked workbook delays, and approval validation failures.
- Updated `AGENTS.md` §2 line count and invariant 4.
- All quality gates pass: `ruff check .`, `python scripts/check_tests_first.py`, and `pytest -q` (216 passed, 31 skipped).
