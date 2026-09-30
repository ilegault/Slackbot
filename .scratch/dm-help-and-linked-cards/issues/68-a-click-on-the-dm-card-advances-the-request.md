# 68: A click on the DM card advances the request

**Status:** in-progress

**Runner:** any

**Auto-merge:** yes

**Blocked by:** 66, 67

**Spec:** `.scratch/dm-help-and-linked-cards/spec.md` (items 10, 12)
**Binding:** `docs/adr/0010-linked-cards-and-direct-message-help.md` decisions 2–4, `AGENTS.md` invariant 1 (one implementation per lifecycle operation) and §7 ("Every listener acks first"), ADR 0001

## What to build

The buyer clicks the button on the DM card (ticket 67) and the request advances exactly as if
they had clicked the thread card's button. Slack's block-action payloads carry a `response_url`
on every surface, so `slack_io.deny(respond, …)` works in a DM.

1. `slack_io.get_card_by_ts(client, channel, thread_ts, card_ts) -> tuple[dict, list, str] | None`:
   `conversations_replies` for the thread, find the message whose `ts` equals `card_ts`, and read
   `(request, history, state)` from the `value` of its `actions`-block button (the JSON
   `find_card_in_thread` already parses — share that parsing, do not copy it). **Never read the
   message metadata for state** — the button value is the store. `None` when the message is not
   found or has no such button.
2. In `src/app.py` one function `handle_dm_stage_action(ack, body, respond, client)` with three
   stacked decorators, `@app.action(config.ACTION_DM_REQ_PROCESSED)`,
   `@app.action(config.ACTION_DM_REQ_CONFIRMED)`, `@app.action(config.ACTION_DM_REQ_DELIVERED)`
   (Bolt's decorator returns the function, so stacking registers all three). It must
   `ack()` first, then, in order:
   - read the pointer from `body["actions"][0]["value"]` and the stage from its `action_id`:
     processed expects thread state `approved` and calls `lifecycle.handle_processed`; confirmed
     expects `processed` and calls `handle_confirmation`; delivered expects `confirmed` and calls
     `handle_delivery`;
   - `get_card_by_ts`; when `None`: `slack_io.deny(respond, "⚠️ I can't find the request card in the thread any more, so nothing was changed. An admin has been told.")`
     and `alert_admins(client, text_rules.format_card_failure_alert("find the card for a DM click", thread_channel, thread_ts, None, "card not found"))`;
   - the same checks as the thread listeners, in the same order, with the assignee taken from the
     **thread card's** request: unassigned → `format_stage_unassigned()`; not
     `admin.can_update_request(user_id, assignee_id)` → `format_stage_denial(assignee_id)`; not
     registered in the roster → the existing `🔒 You must be registered in the lab roster …` text;
   - a stale click (thread state is not the expected one) →
     `slack_io.deny(respond, f"ℹ️ This request is already *{state}*, so nothing was changed.")`;
   - otherwise call the lifecycle handler with `channel=thread_channel`, `thread_ts`, `user_id`,
     `event_ts=card_ts`, `text=""`, `card_ts=card_ts`, `req_data=request`, `history=history`, and a
     `say` closure that posts with `client.chat_postMessage(channel=thread_channel, text=text, thread_ts=thread_ts, **kw)`
     (copy the closure in `handle_req_processed_action`); `handle_confirmation` also gets `files=None`.
   Nothing about processing, confirming or delivering is reimplemented here.

## Acceptance criteria

- [ ] **Registered once per stage.** In `tests/test_68_dm_click.py`,
  `sum(1 for l in app.app._listeners if l.ack_function is app.handle_dm_stage_action) == 3`.
- [ ] **`get_card_by_ts` reads the button value, not the metadata, and picks the exact card.** A fake
  thread with two cards, one whose metadata says `posted` but whose button value says `approved`:
  asking for that card's `ts` returns state `approved` and its own history; the other card's `ts`
  returns the other card; an unknown `ts` returns `None`.
- [ ] **The assignee's click advances the request, for each stage.** Parametrized over processed,
  confirmed, delivered (fixtures as ticket 46 with `sync_queue`; `log_writer.update_row` replaced by
  a recorder): a body shaped like a DM click (`channel.id` `D_BUYER`, `message.ts` a DM ts, **no**
  `container.thread_ts`) whose pointer names thread channel `C123`. Assert `update_row` was called
  once with a dict containing `config.COLUMN_DATE_PROCESSED`, `COLUMN_DATE_CONFIRMED`, or
  `COLUMN_DATE_DELIVERY` respectively; `chat_update` was called with `channel == "C123"` and the
  thread card's `ts` and blocks holding the next stage's button (none after delivered); and a
  `chat_postMessage(channel="C123", thread_ts=…)` confirms it in the thread.
- [ ] **Everyone else is refused privately and nothing is written.** A different buyer, an
  unassigned request, and an unregistered user each: `respond` called once with
  `response_type="ephemeral"` and the exact text from `text_rules` (or the roster text);
  `update_row` not called; `chat_update` not called (absence asserted). The approver and an admin
  are **not** refused.
- [ ] **A stale click and a vanished card.** With the thread card already in state `processed`, a
  `dm_req_processed` click: `respond` text contains `already`, `update_row` not called. With the
  card missing from the thread: refused with the `can't find` text, `update_row` not called, and one
  message to the alert channel containing `find the card for a DM click`.

**Tests may fake:** the Slack client, `respond`, `log_writer` I/O as ticket 46's fixtures do. **Must be
real:** `app.handle_dm_stage_action`, the lifecycle handlers, `slack_io.get_card_by_ts`, `admin`,
`roster` (temp copy).

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
