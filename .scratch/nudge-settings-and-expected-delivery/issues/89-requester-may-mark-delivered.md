# 89: Requester may mark Delivered

**Status:** ready-for-agent

**Runner:** any

**Auto-merge:** yes

**Blocked by:** None (can start immediately)

**Spec:** `.scratch/nudge-settings-and-expected-delivery/spec.md`
**Binding:** `docs/adr/0013-nudge-settings-per-stage-and-expected-delivery.md` decision 6; `docs/adr/0010-linked-cards-and-direct-message-help.md` decision 4 (amended); ADR 0001

## What to build

The person who usually sees the package arrive is the requester. They may now press **Mark
Delivered** — and only that stage button. Mark Processed and Mark Confirmed stay with the assigned
buyer, admins and approvers.

1. `src/admin.py` `can_update_request(user_id, assignee_id)` gains keyword-only
   `stage: str | None = None, requester_id: str | None = None`. It additionally returns `True`
   when `stage == "delivered"` and `user_id` is non-empty and equals `requester_id`. The existing
   unassigned → `False` rule stays first. All other behaviour unchanged.
2. `src/app.py` `handle_req_delivered_action`: call
   `admin.can_update_request(user_id, assignee_id, stage="delivered", requester_id=req_data.get("user_id"))`.
3. `src/app.py` `handle_dm_stage_action`: pass `stage="delivered"` and the requester's ID (the
   thread card payload's `user_id`, which that handler already loads) when the action is
   `config.ACTION_DM_REQ_DELIVERED`; pass nothing extra for the other two actions.

The requester must still be registered in the roster (the existing check after the permission
check) — unchanged.

## Acceptance criteria

New test file `tests/test_89_requester_marks_delivered.py`, fake-client setup as
`tests/test_66_stage_permissions.py` (a confirmed card assigned to buyer `U_B`, requester `U_R`
registered in a temp roster, `U_X` registered but no role).

- [ ] **The predicate.** `can_update_request("U_R", "U_B", stage="delivered", requester_id="U_R")` is true; with `stage="confirmed"` false; `("U_X", "U_B", stage="delivered", requester_id="U_R")` false; `("U_R", None, stage="delivered", requester_id="U_R")` false; the two-argument calls behave exactly as before.
- [ ] **Requester presses Mark Delivered on the thread card.** `U_R` clicking `req_delivered` → the card's `chat_update` carries the delivered blocks (no `actions` block) and no denial is sent.
- [ ] **Requester refused the other stages.** `U_R` clicking `req_processed` on an approved card and `req_confirmed` on a processed card → `respond` receives `text_rules.format_stage_denial("U_B")` text; no `chat_update`.
- [ ] **Stranger still refused.** `U_X` clicking `req_delivered` → the denial text; no `chat_update`.

**Tests may fake:** the Slack client. **Must be real:** `admin.can_update_request`, the two action handlers, `lifecycle.handle_delivery`, the roster on a temp file.

## Gate

Run in this order, exactly as CI does (`.github/workflows/tests.yml`). Zero failures before
you push.

```
ruff check .
python scripts/check_tests_first.py
python tools/type_gate.py
pytest --tb=short -q -n auto --dist loadfile
```

## Comments
