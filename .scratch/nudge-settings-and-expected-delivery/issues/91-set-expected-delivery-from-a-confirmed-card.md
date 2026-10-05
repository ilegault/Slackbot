# 91: Set expected delivery from a Confirmed card

**Status:** in-progress

**Runner:** any

**Auto-merge:** yes

**Blocked by:** 89

**Spec:** `.scratch/nudge-settings-and-expected-delivery/spec.md`
**Binding:** `docs/adr/0013-nudge-settings-per-stage-and-expected-delivery.md` decision 5; `docs/adr/0010-linked-cards-and-direct-message-help.md` decision 3; ADR 0001

## What to build

When a vendor gives a ship date, the buyer (or the requester, an admin or an approver) can record
it: a Confirmed card gets an optional **Set expected delivery** button that opens a form with one
date picker. The date shows on both cards, a thread line announces it, and it is kept in the
request log so ticket 92 can pause nudges until then. It is never required.

1. `src/config.py`: `ACTION_SET_EXPECTED_DELIVERY = "set_expected_delivery"`,
   `EXPECTED_DELIVERY_CALLBACK_ID = "expected_delivery_submit"`.
2. `src/blocks.py`:
   - `build_request_blocks` state `confirmed` and `build_dm_card_blocks` state `confirmed`: add a
     second (unstyled) button `Set expected delivery`, `action_id`
     `config.ACTION_SET_EXPECTED_DELIVERY`, value `json.dumps({"thread_channel", "thread_ts", "card_ts"})`
     (a small pointer, never the request).
   - Both builders: when `request.get("expected_delivery")` is set, add a line
     `*Expected delivery:* <Mon D>` (e.g. `Nov 16`) to the summary.
   - New `build_expected_delivery_view(thread_channel, thread_ts, card_ts, initial_date: str) -> dict`:
     `callback_id` `config.EXPECTED_DELIVERY_CALLBACK_ID`, title `Expected delivery`, one `input`
     block `block_expected_delivery` with a `datepicker` (`action_id` `expected_delivery`,
     `initial_date` = `initial_date`), the pointer in `private_metadata`.
3. `src/app.py`: a module-level `_today() -> date` returning `datetime.now().date()`, the single
   place these handlers read the clock (tests monkeypatch it).
   - `@app.action(config.ACTION_SET_EXPECTED_DELIVERY)`: load the thread card
     (`slack_io.get_card_by_ts`); allow the assignee, the requester (card payload `user_id`), an
     admin or an approver — i.e. `admin.can_update_request(user_id, assignee_id, stage="delivered", requester_id=...)`;
     refused → `slack_io.deny` with `text_rules.format_stage_denial(assignee_id)`. Open the view
     with `initial_date` = the current `expected_delivery`, else `_today() + 14 days`.
   - `@app.view(config.EXPECTED_DELIVERY_CALLBACK_ID)`: date before `_today()` →
     `ack(response_action="errors", errors={"block_expected_delivery": "Pick today or a later date."})`.
     Otherwise `ack()`, set `req_data["expected_delivery"]` (ISO date), append history
     `Expected delivery set to <Mon D> by <name> on <now>`, `chat_update` the thread card with
     `build_request_blocks("confirmed", ...)`, move the DM card with
     `lifecycle.sync_dm_card(..., state="confirmed", ...)`, record it in the request log
     (`store.update(id, expected_delivery=...)` and `store.append_history`, entry found with
     `store.find_id_by_thread`, failures alerting via `lifecycle._request_log` as elsewhere), and
     post in the thread `📦 Expected delivery <Mon D> — I'll check back then.`

## Acceptance criteria

New test file `tests/test_91_expected_delivery.py`; fake client returning a `confirmed` thread
card (buyer `U_B`, requester `U_R`); temp log and roster; `app._today` monkeypatched to 2026-10-05.

- [ ] **The button.** `build_request_blocks("confirmed", req)` and `build_dm_card_blocks("confirmed", ...)` each contain a button with `action_id == "set_expected_delivery"` whose `value` parses to the three pointer keys only; `build_request_blocks("processed", req)` has no such button.
- [ ] **Opening the form.** `U_B` clicking it → `views_open` with `callback_id == "expected_delivery_submit"` and `initial_date == "2026-10-19"`; `U_X` (no role, not the requester) → the denial text and no `views_open`.
- [ ] **Past dates refused.** Submitting `2026-10-04` → `ack(response_action="errors", errors={"block_expected_delivery": "Pick today or a later date."})`, no `chat_update`.
- [ ] **A valid date lands everywhere.** `U_R` submitting `2026-11-16` → the thread card's `chat_update` blocks contain `Expected delivery:* Nov 16` and its button value's `request.expected_delivery == "2026-11-16"`; the DM card is updated with the same line; the request log entry has `expected_delivery == "2026-11-16"` and a new history line; one thread post `📦 Expected delivery Nov 16 — I'll check back then.`
- [ ] **Changing it.** Submitting `2026-11-30` afterwards → the cards show `Nov 30`, the log holds `2026-11-30`, and a second thread line is posted.

**Tests may fake:** the Slack client, `app._today`. **Must be real:** the builders, both handlers, `admin.can_update_request`, `lifecycle.sync_dm_card`, `store` on the temp file.

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
