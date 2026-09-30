# 66: One permission rule for Mark Processed, Confirmed and Delivered — assignee, admin or approver

**Status:** ready-for-agent

**Runner:** any

**Auto-merge:** yes

**Blocked by:** 58

**Spec:** `.scratch/dm-help-and-linked-cards/spec.md` (item 12)
**Binding:** `docs/adr/0010-linked-cards-and-direct-message-help.md` decision 4, `docs/adr/0004-assignment-replaces-claim.md`, `docs/adr/0001-tests-first-and-no-muted-failures.md`

## What to build

The three stage-button listeners in `src/app.py` — `handle_req_processed_action`,
`handle_req_confirmed_action`, `handle_req_delivered_action` — each carry their own inline
"assignee or admin" check with three different refusal texts, and the approver is refused.
Replace them with one rule, so the DM card added later reuses it.

1. `admin.can_update_request(user_id, assignee_id) -> bool`: `False` when `assignee_id` is
   empty; otherwise `True` when `user_id == assignee_id`, or `is_admin_user(user_id)`, or
   `is_approved_reviewer(user_id)`.
2. Two pure message builders in `src/text_rules.py`:
   `format_stage_denial(assignee_id: str) -> str` returning
   `🔒 Only the assigned buyer (<@ASSIGNEE>), an admin or an approver can update this request.`
   and `format_stage_unassigned() -> str` returning
   ``⚠️ This request must be assigned to a buyer before it can be updated. Use `@Purchasing assign @buyer`.``
3. In each of the three listeners, in this order: unassigned → `slack_io.deny(respond, format_stage_unassigned())`
   and return; not `can_update_request` → `slack_io.deny(respond, format_stage_denial(assignee_id))`
   and return; the existing not-registered-in-the-roster check unchanged; then the existing call
   into `lifecycle`. Nothing else in the listeners changes.

## Acceptance criteria

- [ ] **The predicate's truth table** in `tests/test_66_stage_permissions.py`, on a temp roster
  (copy `clean_roster` from `tests/test_46_epif_path_dm_attaches_epif.py`): the assignee, an
  admin and an approver → `True`; a different buyer, a requester with no role, and `None` →
  `False`; any user with `assignee_id=None` → `False`.
- [ ] **The approver succeeds on all three buttons.** For each of the three listeners, a click
  by the approver on an assigned request calls the matching `lifecycle.handle_processed` /
  `handle_confirmation` / `handle_delivery` once (a recorder on the lifecycle function is
  fine — the listener is the code under test) and does not call `respond`.
- [ ] **A different buyer is refused privately on all three.** `respond` is called once with
  `response_type="ephemeral"`, `replace_original=False`, and text equal to
  `text_rules.format_stage_denial("U_ASSIGNED")`; the lifecycle handler is **not** called and
  `chat_update` is **not** called (absence asserted).
- [ ] **An unassigned request is refused on all three**, text equal to
  `format_stage_unassigned()`, lifecycle handler not called.
- [ ] **A real write follows an approver's click.** With the workbook functions replaced by
  recorders as in ticket 46's fixtures and the queue made synchronous (`sync_queue`), the
  approver clicking Mark Processed causes `log_writer.update_row` to be called once with a
  dict containing `config.COLUMN_DATE_PROCESSED`.

Existing scenarios in `tests/test_12_denials.py` (`req_processed_unassigned`,
`req_processed_non_assignee`, `req_confirmed_non_assignee`, and the delivered equivalents)
assert on the old refusal wording. **Rewrite their expected substring in place, keeping every
test name and every one of the four guarantees that file asserts** (message unchanged,
nothing written, ephemeral, the role named). Do not delete a scenario and do not drop a
guarantee. Do not edit the help text, App Home or `CONTEXT.md`.

**Tests may fake:** the Slack client, `respond`, and the lifecycle handlers as recorders where
stated. **Must be real:** the listeners, `admin`, `roster` (temp copy), `text_rules`.

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

