# 74: The DM card carries the buyer picker too

**Status:** done

**Runner:** any

**Auto-merge:** yes

**Blocked by:** 72

**Spec:** `.scratch/buyer-handoff-and-nudge/spec.md` (Hand-off; "The picker on approved cards")
**Binding:** `docs/adr/0011-buyers-hand-off-requests-and-the-request-log.md` decision 2, `docs/adr/0010-linked-cards-and-direct-message-help.md` decisions 2–3, ADR 0001

## What to build

An assigned buyer's DM card shows the same buyer picker while the request is `approved`, so
a buyer who can't do an order hands it off from where they already are. The DM card holds
only a pointer to the thread card; a pick there resolves the thread card exactly as a DM stage
click does, and goes through `lifecycle.handle_assign`, so both cards end in sync.

1. `config`: add `ACTION_DM_REQ_ASSIGN_SELECT = "dm_req_assign_select"`.
2. `blocks.build_dm_card_blocks`: in state `approved`, add a `users_select` element with
   `action_id` `config.ACTION_DM_REQ_ASSIGN_SELECT`, placeholder `Assign a buyer`,
   `initial_user` the request's `assignee_id`. Slack does not allow a `value` on a
   `users_select`, so put the pointer (`thread_channel`, `thread_ts`, `card_ts`, as JSON)
   in the actions block's `block_id`. No picker in any other state.
3. `app`: new handler for `config.ACTION_DM_REQ_ASSIGN_SELECT`. `ack()`, read the pointer from
   the action's `block_id`, load the thread card with `slack_io.get_card_by_ts` as
   `app.handle_dm_stage_action` does (including its "can't find the request card" private
   refusal and admin alert), then call `lifecycle.handle_assign` with the thread channel,
   thread ts, the thread card's `req_data`, `history`, `current_state` and `msg_ts=card_ts`,
   and `deny=lambda t: slack_io.deny(respond, t)`. The `say` it passes posts in the thread.

## Acceptance criteria

New test file `tests/test_74_dm_card_picker.py`, fixtures as `tests/test_68_dm_click.py`.

- [x] **The DM card has the picker only while approved.** `build_dm_card_blocks("approved", …)`
  has a `users_select` with `action_id == "dm_req_assign_select"` and `initial_user` equal to
  the assignee, and its actions block's `block_id` parses as JSON with `thread_ts` and
  `card_ts`; for `processed` there is none.
- [x] **A pick in the DM moves the request.** The assignee (buyer A) selects buyer B on the DM
  card: the thread card (`channel` = thread channel, `ts` = card_ts) is `chat_update`d with
  `"assignee_id": "U_B"`, buyer A's DM card is retired (no `actions` block, contains
  `Reassigned to`), and a new DM card is posted to `U_B`.
- [x] **Permission and refusal match the thread card.** A requester who is not a buyer, approver or
  admin: `respond` is called with `Only buyers, approvers or admins`, no `chat_update`.
- [x] **A missing thread card refuses privately and alerts.** `conversations_replies` returns no
  card: `respond` contains `can't find the request card`, one message goes to the admin alert
  channel, no `chat_update`.

**Tests may fake:** the Slack client. **Must be real:** the new handler, `slack_io.get_card_by_ts`,
`lifecycle.handle_assign`, `blocks.build_dm_card_blocks`, the roster on a temp file.

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
- `config`: added `ACTION_DM_REQ_ASSIGN_SELECT = "dm_req_assign_select"`.
- `blocks.build_dm_card_blocks`: added buyer picker (`users_select`) in `approved` state with `initial_user` from request assignee and pointer serialized in actions block's `block_id`.
- `app`: added `handle_dm_assign_select_action` listening on `ACTION_DM_REQ_ASSIGN_SELECT`. Reads thread card pointer from `block_id`, resolves card via `slack_io.get_card_by_ts` (with missing-card private refusal and admin alert), and delegates to `lifecycle.handle_assign`.
- Tests added in `tests/test_74_dm_card_picker.py` covering all 4 criteria plus handler registration.
- Updated `tests/test_67_dm_card.py` to expect 2 elements in actions block for approved DM card.
- Gate: ruff ✓, check_tests_first ✓, type_gate ✓, full suite (568 passed, 31 skipped) ✓.
