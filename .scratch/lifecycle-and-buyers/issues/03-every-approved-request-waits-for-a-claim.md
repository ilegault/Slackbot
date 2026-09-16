# 03: Every approved request waits for a claim

**What to build:** Remove the branch that lets a buyer's own request skip the claim
step. One path from now on: approval always broadcasts to buyers and always waits
on Claim. Move the email draft from approval to claim, addressed to the claimer.

**Blocked by:** 01, 02

**Status:** ready-for-agent

Read `docs/adr/0002-request-lifecycle-and-surfaces.md` decision 6 first.
`docs/adr/0001-tests-first-and-no-muted-failures.md` is binding.

## Why

`finalize_purchase_request`'s `on_success` splits on
`requester in config.GRAD_STUDENT_BUYERS`: a buyer's own request skips the claim
entirely and pings the requester, so nothing is ever claimable. That is why row 18
pinged Isaac directly and no claim was ever pending.

It also collides with the purchasing rotation. Duty moves between grad students
(Charlie's arrangement, Dylan first), so the person who asked is not necessarily
the person whose turn it is. There is no auto-assign shortcut.

The email draft is addressed to whoever emails purchasing. That is the **claimer**,
not the requester — a draft signed by the requester is wrong the moment someone
else claims.

## Requirements

- **The permission gate is `roster.is_buyer(user_id)`**, on both the button and the
  `@p-bot claim` keyword branch. Two surfaces that disagree about who may claim is
  the failure to avoid.
- **The broadcast @-mentions real IDs.** `<@U…>` built from `roster.get_buyers()`,
  not a joined string of names.
- **Do not re-parse the PDF** to build the claim's email draft. Read the fields
  from the button's `value` payload where available, falling back to
  `log_writer.get_row_info(row)`.

## Acceptance criteria

- [ ] The `is_grad_buyer` branch in `on_success` is gone; there is one path
- [ ] The approval broadcast builds its mention list from `roster.get_buyers()` as
      `<@ID>` mentions, and keeps the row number, item, price, vendor, category and
      saved-EPIF line both branches already posted
- [ ] `handle_req_claim_action` is gated on `roster.is_buyer(user_id)`; a non-buyer
      gets `respond(...)` explaining only purchase buyers can claim, the message is
      **not** updated, and nothing is written
- [ ] The existing "must be registered in the roster" check for name resolution
      still runs after the buyer gate
- [ ] The `@p-bot claim` keyword branch has the same gate
- [ ] The email draft is generated in `handle_claim` with the **claimer's** resolved
      name and DM'd to the claimer
- [ ] No email draft is DM'd at approval time
- [ ] The claim draft's fields come from the button `value` or
      `log_writer.get_row_info(row)` — the PDF is not re-parsed
- [ ] A test asserts an approved request **from a buyer** still broadcasts for a
      claim and sends **no** email-draft DM at approval — assert on the DM *not*
      being sent, not just on the broadcast text
- [ ] A test asserts a `req_claim` click from a non-buyer responds ephemerally,
      does not call `handle_claim`, does not `chat_update`, and sends no DM
- [ ] A test claims as a different user than the requester and asserts the DM
      target is the claimer and the draft's signature line is the claimer's name
- [ ] A test asserts a `req_claim` click and an `@p-bot claim` mention call
      `handle_claim` with the same channel and `thread_ts`
- [ ] `ruff check .`, `python scripts/check_tests_first.py` and `pytest -q` all pass

## Comments
