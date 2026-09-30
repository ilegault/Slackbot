# 72: Any buyer can move an approved request from the thread card

**Status:** done

**Runner:** any

**Auto-merge:** yes

**Blocked by:** None (can start immediately)

**Deletes tests:** tests/test_08_assignment.py::test_buyer_reassign_already_assigned_request_denied

**Spec:** `.scratch/buyer-handoff-and-nudge/spec.md` (Hand-off; "Assignment", "The picker on approved cards")
**Binding:** `docs/adr/0011-buyers-hand-off-requests-and-the-request-log.md` decisions 1–2, `docs/adr/0004-assignment-replaces-claim.md` (decision 3 replaced by 0011), `docs/adr/0010-linked-cards-and-direct-message-help.md` decision 4, ADR 0001

## What to build

An approved thread card carries the buyer picker. Any buyer, approver or admin can use it
(or the typed `@Purchasing assign @buyer`) to assign the request or move it from one buyer
to another — including a buyer who is not the current assignee. Everything a reassignment
already does (history line, thread line, email draft and DM card to the new buyer, old DM
card retired) happens exactly as today through the one function, `lifecycle.handle_assign`.

1. `blocks.build_request_blocks`: the `users_select` element currently added only when
   `state == "posted"` is also added when `state == "approved"`. Same `action_id`
   (`config.ACTION_REQ_ASSIGN_SELECT`), placeholder text `Assign a buyer`, `initial_user` set
   to the request's `assignee_id` when present. No picker in any other state.
2. `app.handle_req_assign_select_action`: it currently recovers the request only from the
   sibling `req_approve` button. Also recover it from any button in the card's actions block
   whose JSON `value` has a `request` key (the approved card's `req_processed` / `req_cancel`
   buttons), taking `state` and `history` from that value.
3. `lifecycle.handle_assign` permission: replace the assigned/unassigned two-branch check with
   one rule — `roster.is_buyer(user_id)` or `admin.is_approved_reviewer(user_id)` or
   `admin.is_admin_user(user_id)`; otherwise refuse with
   `🔒 Only buyers, approvers or admins can assign purchase requests.`
   Add an optional `deny` parameter (a callable taking the text). When given, refusals go
   through it instead of `say`; the picker handler passes
   `lambda t: slack_io.deny(respond, t)` so picker refusals are private. The keyword path is
   unchanged.
4. `lifecycle.handle_assign`: when `target_user_id` equals the current `assignee_id`, return
   `True` immediately — no `chat_update`, no `chat_postMessage`, no DM.
5. Update the `handle_assign` docstring and the module docstring line that says only the
   current assignee, an approver or an admin may reassign.

## Acceptance criteria

New test file `tests/test_72_any_buyer_moves_a_request.py`. Reuse the `clean_roster` and
`sync_queue` fixtures and the `_make_thread_card_message` helper pattern from
`tests/test_69_cards_move_together.py` (roster with one admin, one approver, three buyers, one
requester who is none of those).

- [x] **The approved card has the picker.** `blocks.build_request_blocks("approved", req)` for a
  request with `assignee_id="U_BUYER"` contains an `actions` element of type `users_select`,
  `action_id == "req_assign_select"`, `initial_user == "U_BUYER"`; for a request with no
  `assignee_id` the element has no `initial_user` and placeholder text `Assign a buyer`. For
  `processed`, `confirmed` and `delivered` no element of type `users_select` exists.
- [x] **Another buyer moves an assigned request.** Through `app.handle_req_assign_select_action`
  with a body whose message is an `approved` card assigned to buyer A, clicked by buyer B,
  selecting buyer C: the thread card's `chat_update` blocks carry `"assignee_id": "U_C"` in a
  button value; a `chat_postMessage` goes to `U_C` (the new DM card); history contains
  `Reassigned to`. The same click by buyer B selecting buyer B also succeeds.
- [x] **A non-buyer is refused privately.** The same click by the requester (not buyer, approver or
  admin): `respond` is called with text containing `Only buyers, approvers or admins`, and the
  fake client records **no** `chat_update` and **no** `chat_postMessage`.
- [x] **Picking the current buyer does nothing.** Buyer A selected on a card already assigned to
  buyer A: zero `chat_update` and zero `chat_postMessage` calls.
- [x] **The typed keyword follows the same rule.** `@Purchasing assign @C` sent by buyer B on a
  thread whose card is assigned to buyer A (drive through `app.dispatch_command` as
  `test_69` does): the thread card is updated to assignee C. The deleted test
  `test_buyer_reassign_already_assigned_request_denied` asserted the old rule and is replaced
  by this criterion.

**Tests may fake:** the Slack client, `log_writer` I/O as `test_69` does. **Must be real:**
`lifecycle.handle_assign`, `app.handle_req_assign_select_action`, `blocks.build_request_blocks`,
the roster on a temp file.

## Gate

Run in this order, exactly as CI does (`.github/workflows/tests.yml`). Zero failures before
you push. If `tools/type_gate.py` exists on `master` when you start, also run
`python tools/type_gate.py` after `check_tests_first.py`, and use
`pytest --tb=short -q -n auto --dist loadfile` in place of the last line.

```
ruff check .
python scripts/check_tests_first.py
pytest -q --tb=short --durations=25
```

## Comments

### Landed 2026-09-30
- `blocks.build_request_blocks`: added `elif state == "approved":` branch with `users_select` picker
  (action_id `req_assign_select`, placeholder `"Assign a buyer"`, `initial_user` when present).
- `lifecycle.handle_assign`: unified permission check (ADR 0011 decision 1); added `deny` kwarg
  for private refusals on picker path; added same-buyer no-op.
- `app.handle_req_assign_select_action`: payload recovered from any button with a `"request"` key
  (not only `req_approve`); `deny` lambda passed to `handle_assign`.
- Harness defects fixed: `test_buyer_reassign_already_assigned_request_denied` (deleted — old ADR
  0004 rule); `test_build_request_blocks_approved_state_and_no_req_claim_in_src` and
  `test_build_request_blocks_posted_renders_users_select_and_approved_does_not` (updated to assert
  the approved card DOES carry the picker under ADR 0011).
- Gate: ruff ✓, check_tests_first ✓ (3 src / 3 test files), type_gate ✓ (0 hard / 0 soft),
  558 passed 31 skipped.
