# 67: The assigned buyer's DM carries a card with the next-step button

**Status:** done

**Runner:** any

**Auto-merge:** yes

**Blocked by:** 64, 65

**Spec:** `.scratch/dm-help-and-linked-cards/spec.md` (items 7–9)
**Binding:** `docs/adr/0010-linked-cards-and-direct-message-help.md` decisions 2 and 3, `docs/adr/0002-request-lifecycle-and-surfaces.md` decision 3 (the thread card is the store), `AGENTS.md` invariant 1 (`_send_assignee_dm` stays the only DM implementation), ADR 0001

## What to build

When a buyer is assigned, at approval (`lifecycle.finalize_purchase_request`) or later
(`lifecycle.handle_assign`), the buyer's DM gains a **DM card** as its own message, after the
email draft and any attachments: a short summary, a link to the thread card, and the one
next-step button for the current stage. This ticket only **posts** it and records where it is;
clicks are ticket 68 and keeping it current is ticket 69. The thread card stays the store — the
DM card holds a pointer, never request state.

1. `config`: add `ACTION_DM_REQ_PROCESSED = "dm_req_processed"`,
   `ACTION_DM_REQ_CONFIRMED = "dm_req_confirmed"`, `ACTION_DM_REQ_DELIVERED = "dm_req_delivered"`.
2. `slack_io.post_dm_card(client, user_id, text, blocks) -> tuple[str, str] | None`:
   `resp = client.chat_postMessage(channel=user_id, text=text, blocks=blocks)`; return
   `(resp["channel"], resp["ts"])` (Slack returns the DM's channel id when posting to a user id);
   return `None` and log a WARNING if the call raises.
3. `blocks.build_dm_card_blocks(state, request, thread_channel, thread_ts, card_ts, thread_link=None) -> list`:
   a section — `🛒 *<item>* — <vendor>, $<price> (Row <row>)` (row omitted when unknown),
   `Stage: *<state>*`, and `<thread_link|Open the request thread>` when a link is given — and,
   for states `approved`, `processed`, `confirmed` only, an `actions` block with **one** primary
   button: `Mark Processed` / `ACTION_DM_REQ_PROCESSED`, `Mark Confirmed` / `ACTION_DM_REQ_CONFIRMED`,
   `Mark Delivered` / `ACTION_DM_REQ_DELIVERED`. **No Cancel button.** The button `value` is exactly
   `json.dumps({"thread_channel": …, "thread_ts": …, "card_ts": …})` and nothing else.
4. `lifecycle._send_assignee_dm` gains optional `thread_channel`, `thread_ts`, `card_ts`,
   `request`, `state` arguments (all default `None`, so existing callers and tests still work)
   and returns `(dm_channel, dm_ts)` of the DM card or `None`. After the draft message and file
   uploads it builds the link with `client.chat_getPermalink(channel=thread_channel, message_ts=card_ts)["permalink"]`
   (link omitted if that call raises), then calls `post_dm_card`. With no `card_ts` it posts no
   DM card and logs a WARNING. A `None` from `post_dm_card` calls
   `slack_io.alert_admins(client, text_rules.format_card_failure_alert("post the buyer's DM card", thread_channel, thread_ts, None, "chat.postMessage failed"))`
   and never reverses the approval.
5. **Order in `finalize_purchase_request.on_success`:** the thread card is updated or posted
   *before* the DM is sent, so the DM card knows `card_ts` (the updated card's ts, or the `ts`
   of ticket 64's fallback post). Move the `_send_assignee_dm(...)` call to after that block; the
   `say(...)` lines stay where they are. When `_send_assignee_dm` returns a reference, set
   `dm_channel` and `dm_ts` in the request payload and call `client.chat_update` on the thread
   card once more with the same text, blocks (rebuilt from the payload, so the two keys ride in
   every button `value`) and `metadata`.
6. In `handle_assign`, after `_send_assignee_dm(...)` (pass `thread_channel=channel`,
   `thread_ts=thread_ts`, `card_ts=msg_ts`, `request=req_data`, `state=current_state`), store any
   returned reference in `req_data` and update the thread card again the same way. The first
   card update in that function (which shows the new assignee) stays.

## Acceptance criteria

- [x] **The DM card's shape**, tested on `blocks.build_dm_card_blocks` directly in
  `tests/test_67_dm_card.py`: `approved` → one button `Mark Processed`, `action_id`
  `dm_req_processed`; `processed` → `Mark Confirmed` / `dm_req_confirmed`; `confirmed` → `Mark Delivered`
  / `dm_req_delivered`; `delivered` → no `actions` block; no state has a `Cancel` button; the button
  `value` parses to a dict whose keys are exactly `thread_channel`, `thread_ts`, `card_ts`; the
  section text holds the item, vendor, a `$` price and `Row 17`; with `thread_link=None` it holds no `<http`.
- [x] **Approval with a buyer posts the card, after the draft, and records where.** Copy the
  fixtures and fake-client style of `tests/test_46_epif_path_dm_attaches_epif.py`; make
  `chat_postMessage` return `{"channel": "C123", "ts": "5.5"}` for the thread-card post and
  `{"channel": "D_BUYER", "ts": "9.9"}` when `channel == "U_BUYER"`. Assert: the call to `U_BUYER`
  carrying `blocks` comes **after** the plain draft call to `U_BUYER` and after `files_upload_v2`
  (compare `client.mock_calls` order); its button `value` holds `card_ts` equal to the thread card's
  `ts`; and the last `chat_update` of the thread card has a button `value` whose `request` holds
  `dm_channel == "D_BUYER"` and `dm_ts == "9.9"`.
- [x] **Both routes.** The same on a Workday-path approval (no PDF): a DM card is posted and
  `files_upload_v2` is not called.
- [x] **A later assignment posts it too, and a card-less thread does not.** `handle_assign` with a
  fake `conversations_replies` holding an approved card: a DM card is posted and the thread card's
  `request` gains the references. With no card found (so no `msg_ts`): no DM card is posted
  and `caplog` holds a WARNING.
- [x] **A failed DM card never undoes the approval.** `post_dm_card` returning `None` (make
  `chat_postMessage` raise for `U_BUYER` only after the draft): the row-append recorder was called
  once, the thread card exists with no `dm_channel`, and one message went to the alert channel
  containing `post the buyer's DM card`.

**Tests may fake:** the Slack client, `log_writer` I/O as ticket 46's fixtures do. **Must be real:**
`finalize_purchase_request`, `handle_assign`, `_send_assignee_dm`, `blocks`, `slack_io.post_dm_card`.

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
