# 17: The posted card carries a buyer picker

**What to build:** A dropdown beside Approve on the posted card, so the approver
picks the responsible buyer instead of remembering the `@`-mention syntax.
Skipping it still approves. Picking a non-buyer still approves.

**Blocked by:** 14

**Status:** done

**Read `docs/adr/0005-assignment-can-be-a-button.md` before anything in this
ticket** — it is the whole rationale and it amends ADR 0004's reasoning.
`docs/adr/0004-assignment-replaces-claim.md` decisions 2 and 3 are unchanged and
binding. `docs/adr/0001-tests-first-and-no-muted-failures.md` is binding.

## Why

Ticket 08 made the approver name the buyer in the approval message, in either
mention order. That works and it stays. But the posted card — the thing Charlie
is actually looking at when he decides — offers no way to name anyone, so the
only route is typing a mention with exactly the right syntax.

ADR 0005 accepted a picker. This is it.

## Requirements, stated as requirements

1. **The picker lives in `blocks.build_request_blocks("posted", …)`** — a pure
   builder taking a dict and returning blocks, already the seam for every card
   assertion in `test_regression_guards.py` and `test_08_assignment.py`.

   A `users_select` in the **same `actions` block** as Approve and Decline,
   `action_id` `req_assign_select`, placeholder "Assign a buyer (optional)".

2. **A `users_select` carries no arbitrary `value`.** Its action payload carries
   `selected_user` and the message's blocks. The handler recovers the request
   payload from the **sibling Approve button's `value`** inside
   `body["message"]["blocks"]`.

   **Do not add a parallel store for this.** Invariant 3 is unchanged: the message
   is still the store, and `src/store.py` stays dead.

3. **Selecting a buyer does not approve anything.** It records the selection on the
   card by re-rendering with `assignee_id` set. Approve then reads it from the
   button value it already carries. Approval remains the money decision and stays a
   deliberate second click.

4. **The picked person goes through the same checks a mentioned person does:** on
   the buyers roster, and registered as a lab member. A refusal leaves the request
   unassigned and **never refuses the approval** — ADR 0004 decision 2, unchanged.

5. **If both a picker selection and an `@`-mention are present, the mention wins,
   and the bot says which it used.** ADR 0005 decision 4. No guessing, no silence.

6. **Both inputs resolve to `lifecycle.handle_assign`.** Invariant 1: no second
   implementation of assignment.

7. **The approved card does not carry the picker.** Reassignment after approval
   stays on the existing `@Purchasing assign` path; ADR 0004 decision 3's
   permission rules are unchanged.

8. **`AGENTS.md` §9 trap 7 is corrected in this ticket.** It still says "Claimed by
   Dylan". The word is **assigned**. The underlying trap is real and worth keeping
   — a buyer needs a `requesters` entry as well as a `buyers` entry — so fix the
   wording, not the trap.

## Acceptance criteria

- [x] `build_request_blocks("posted", …)` renders a `users_select` with `action_id`
      `req_assign_select` in the same `actions` block as Approve, and
      `build_request_blocks("approved", …)` does **not**
- [x] A test asserts the handler recovers the request payload from the sibling
      Approve button's `value` in `body["message"]["blocks"]` — with no new state file
- [x] Selecting a buyer re-renders the card with the assignee line set and performs
      **no** Excel write — assert `append_row` was not called
- [x] Picking a non-buyer leaves the request unassigned, posts the `add-buyer`
      refusal, **and** a subsequent Approve still writes the row
- [x] Picking a buyer with no `requesters` entry gets the existing
      `/roster-set-name` refusal and leaves the request unassigned
- [x] A picked buyer and a mentioned buyer together: the **mention** wins, and the
      reply names which input was used
- [x] A test asserts both the picker path and the mention path call
      `lifecycle.handle_assign` — one implementation, not two
- [x] Picking nobody and approving writes the rows and posts the unassigned card,
      exactly as ticket 08 established
- [x] `AGENTS.md` §9 trap 7 says "assigned", and the trap itself is still there
- [x] `ruff check .`, `python scripts/check_tests_first.py` and `pytest -q` all pass

## Out of scope

- A picker on the approved card. Requirement 7.
- Any new Excel column for the buyer. ADR 0004 decision 7 says no, and that has
  not changed.
- Teaching the bot the purchasing rotation. The bot models a name chosen by a
  person who knows whose turn it is. A default buyer or a round-robin is a new
  ADR, not a constant.
- `src/store.py`. Requirement 2.

## Comments

### 2026-09-17 Implementation summary

- Added `ACTION_REQ_ASSIGN_SELECT = "req_assign_select"` to `src/config.py`.
- Updated `blocks.build_request_blocks`: on `posted` cards, renders a `users_select` alongside Approve and Decline in the same actions block with placeholder `"Assign a buyer (optional)"`, pre-selecting `initial_user` if `assignee_id` is present. Approved card does not carry the picker. Added `default=str` to `json.dumps` for safe date serialization.
- Added `@app.action("req_assign_select")` (`handle_req_assign_select_action`) in `src/app.py`: recovers request payload from sibling Approve button's `value` in `body["message"]["blocks"]` (no state file) and delegates to `lifecycle.handle_assign`.
- Updated `lifecycle.handle_assign`: supports `current_state="posted"`; validates target buyer against roster and requesters map; updates message card in place via `client.chat_update` without writing to Excel, posting Workday announcements, or sending premature email draft DMs before approval.
- Updated `dispatch_command` in `src/app.py`: checks card in thread for picked buyer; enforces mention-over-picker precedence when both are present and sets `input_note` ("Using mentioned buyer instead of dropdown selection."); passes `input_note` and `card_ts` into `handle_epif_processing` and `finalize_purchase_request` to notify in thread.
- Updated `validators.validate`: safely accesses `parsed.get("category_error")`.
- Verified all 10 tests in `tests/test_17_buyer_picker.py` and full suite (245 passed).
- Gate passed: `ruff check .`, `python scripts/check_tests_first.py`, `pytest -q --tb=short`.
