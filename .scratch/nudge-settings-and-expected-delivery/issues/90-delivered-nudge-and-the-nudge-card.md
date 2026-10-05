# 90: Delivered nudge and the nudge card

**Status:** ready-for-agent

**Runner:** any

**Auto-merge:** yes

**Blocked by:** 88, 89

**Spec:** `.scratch/nudge-settings-and-expected-delivery/spec.md`
**Binding:** `docs/adr/0013-nudge-settings-per-stage-and-expected-delivery.md` decisions 1, 2, 4, 6; `docs/adr/0010-linked-cards-and-direct-message-help.md` decision 3; ADR 0001

## What to build

A confirmed request that hasn't been delivered gets the **delivered** nudge every N working days
after Date Confirmed (default every 10, channel). It @-mentions both the buyer and the requester
and asks "Has this been delivered?" on a small **nudge card** with a **Delivered** button. Pressing
it works exactly like Mark Delivered: both the thread card and the DM card move. Only one nudge card
is live per request: posting a new one retires the older ones. (Ticket 92 adds the "Not yet" button.)

1. `src/config.py`: `ACTION_NUDGE_DELIVERED = "nudge_delivered"`.
2. `src/blocks.py`: new `build_nudge_card_blocks(state, mentions: str, item: str, n: int, thread_channel, thread_ts, card_ts, note: str | None = None) -> list`.
   - `state == "active"`: a section
     `⏰ <mentions> — *<item>* was confirmed <n> working days ago. Has this been delivered?`
     and an `actions` block with one primary button `Delivered`, `action_id`
     `config.ACTION_NUDGE_DELIVERED`, value `json.dumps({"thread_channel", "thread_ts", "card_ts"})`
     like `build_dm_card_blocks`.
   - `state in ("replaced", "delivered", "closed")`: the same section plus a context line with
     `note`, and no `actions` block.
3. `src/nudge.py` `run_nudges`: first row's Date Confirmed parsed (`parse_sheet_date`), Date
   Delivered empty, `delivered.enabled` true, thread card state `confirmed`, and
   `is_due(working_days_between(date_confirmed, today), delivered.every)` →
   - mentions = `<@buyer_id>` plus `<@requester_id>` when the entry (or the card payload's
     `user_id`) has one and it differs from the buyer;
   - first `chat_update` every `(channel, ts)` in the entry's `nudge_cards` to state `replaced`
     with note `Replaced by a newer reminder.`;
   - `channel` true → `chat_postMessage(channel=<thread channel>, thread_ts=..., reply_broadcast=True, blocks=<active card>, text=<section text>)`;
     `dm` true → the same card to the buyer's ID and to the requester's ID;
   - `store.update(id, last_nudged=today.isoformat(), nudge_cards=[[channel, ts], ...])` with
     every card just posted.
4. `src/app.py`: new `@app.action(config.ACTION_NUDGE_DELIVERED)` handler, modelled on
   `handle_dm_stage_action`: load the thread card with `slack_io.get_card_by_ts`. State not
   `confirmed` → `chat_update` the clicked message to state `closed` with note
   `Already <state>.` and stop. Otherwise check
   `admin.can_update_request(user_id, assignee_id, stage="delivered", requester_id=<card payload user_id>)`;
   refused → `slack_io.deny(respond, text_rules.format_stage_denial(assignee_id))`. Allowed (and
   registered, same check as `handle_req_delivered_action`) → `lifecycle.handle_delivery(...)`
   with the thread card's `req_data`/`history`/`card_ts`, then `chat_update` every card in the
   request log entry's `nudge_cards` to state `delivered` with note `✅ Delivered by <@user>`.

## Acceptance criteria

New test file `tests/test_90_delivered_nudge.py`; temp log/settings/roster; `get_row_info`
returns Date Processed and Date Confirmed = `"46300"` (2026-10-05), Date Delivered empty; card in
state `confirmed`, buyer `U_B`, requester `U_R`.

- [ ] **Day 10 posts the card to the channel.** 2026-10-16 (day 9) → nothing. 2026-10-19 (day 10) → exactly one post with `reply_broadcast=True` whose blocks contain `<@U_B>`, `<@U_R>`, `Has this been delivered?` and a button with `action_id == "nudge_delivered"`; no DMs; the entry's `nudge_cards` holds that post's channel and ts.
- [ ] **DM option.** Settings `delivered = {"enabled": true, "every": 10, "dm": true, "channel": false}` → day 10: the card goes to `U_B` and `U_R` by DM, no channel post.
- [ ] **One live card.** Running day 10 then day 20 (2026-11-02) → before the day-20 post, the day-10 card is `chat_update`d with `Replaced by a newer reminder.` and no `actions` block.
- [ ] **Delivered from the card.** `U_R` pressing `nudge_delivered` → `lifecycle.handle_delivery` runs (spy or observe the thread card's `chat_update` to delivered blocks) and every nudge card is updated to contain `Delivered by <@U_R>` with no `actions`. A stranger pressing it → the denial text, no thread-card update. Pressing it when the thread card is already `delivered` → the clicked card shows `Already delivered.` and `handle_delivery` is not called.
- [ ] **Stops.** Date Delivered present → nothing; `delivered.enabled` false → nothing; the confirmed nudge never fires once Date Confirmed is present.

**Tests may fake:** the Slack client, `log_writer.get_row_info`. **Must be real:** `nudge`, `nudge_settings` and `store` on temp files, `blocks.build_nudge_card_blocks`, the action handler, `admin.can_update_request`.

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
