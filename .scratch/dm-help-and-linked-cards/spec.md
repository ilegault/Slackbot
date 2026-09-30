# Spec — DM help, cards that always exist, and a Mark Processed button in the buyer's DM

**Status:** ready-for-agent
**Binding:** `docs/adr/0010-linked-cards-and-direct-message-help.md`,
`docs/adr/0009-keywords-storage-settings-and-the-bot-name.md`,
`docs/adr/0004-assignment-replaces-claim.md`,
`docs/adr/0001-tests-first-and-no-muted-failures.md`
**Glossary:** `CONTEXT.md` — **DM card** (new), **card**, **DM**, **Alert channel**,
**Keyword** (updated)
**Builds on:** `.scratch/commands-paths-and-name/` — tickets 51 and 53 land first.

## Why

Production, 2026-09-29:

- A member's first DM to the bot was `I want to purchase this: <link>`. It crashed with
  `ValueError: respond is unsupported here as there is no response_url`, raised from
  `slack_io.deny` in the unknown-word branch of `app.dispatch_command`. Ticket 51 fixes
  the crash. Two seconds later a second `message` event arrived with no user and empty
  text (Slack's edit of the message when it unfurled the link). `on_direct_message`
  filters only `bot_message`, so the event reached the dispatcher and crashed the same
  way. After 51 it would not crash — it would post an "I don't know" reply to an event
  no person sent.
- After 51 and 53 a DM that is not a keyword gets `I don't know "I"`, which teaches
  nothing to someone who typed a sentence.
- A member dropped a filled EPIF in a purchasing thread; the approver approved it with
  `@Buyer @Purchasing Approved`. The bot wrote the row and DM'd the buyer the email
  draft. **No card appeared in the thread**, not on the drop and not on approval. The
  buyer had nothing to click and typed a free-text reply. `finalize_purchase_request`
  updates the card `if target_card_ts:` and otherwise silently does nothing, and
  `handle_epif_drop` returns with only a log line on several failures. Why the drop card
  was missing is not yet known (event never delivered, or a silent failure) — this
  spec makes both visible and makes approval independent of the cause.

## What is true afterward

### A. Slack's own events are ignored (ADR 0010 decision 6)

1. `on_direct_message` returns before doing anything for a `message` event that has no
   `user`, or whose `subtype` is not absent, `file_share` or `thread_broadcast`.
   Nothing is logged above DEBUG, nothing is replied, the dispatcher is never reached.

### B. A DM the bot cannot read gets help (ADR 0010 decision 5, amends ADR 0009 decision 3)

2. `dispatch_command` knows whether the message came in a DM. In a DM: a close match
   still gets ticket 53's "did you mean" reply; **no close match** gets one message
   containing the full help text (`blocks.get_help_message()`) and a **Start a purchase
   request** button above it, with the action id of the existing App Home button
   (`start_purchase_interview`), which already opens the blank interview from any
   surface. In a channel thread nothing changes from ticket 53.
3. Nothing from the DM is carried into the interview: no link, no text. The button opens
   a blank Screen 1.

### C. Every approval leaves a card; failures are loud (ADR 0010 decisions 1, 7)

4. In `lifecycle.finalize_purchase_request`, when approval finds no card in the thread
   (`target_card_ts` is empty), the bot posts one with `client.chat_postMessage` in the
   thread — state `approved`, text `🛒 Purchase Request (Approved)`, the blocks from
   `blocks.build_request_blocks("approved", …)` with the History lines it would have
   written, and the same `metadata` (`event_type` `purchase_request`) the update path
   sets. The update-in-place path is unchanged.
5. One function `slack_io.alert_admins(client, text)` posts to
   `config.ADMIN_ALERT_CHANNEL` and never raises (log a warning if the post fails or the
   channel is unset). Every failure below calls it with: what step failed, the channel
   and thread, the file name if any, and the exception text.
   - `handle_epif_drop`: parse failure, download failure, and card-post failure.
   - `finalize_purchase_request`: fallback card post failure, and card update failure.
   - The `except` branches that today only `log.error` stay logged as well.
6. `handle_epif_drop` logs one INFO line at entry and one at every return, saying which
   exit it was.

### D. The buyer's DM carries a linked card (ADR 0010 decisions 2, 3, 4)

7. The thread card's request payload records `dm_channel` and `dm_ts` — where the DM card
   lives. Every card rebuild carries them forward. They ride in the button `value` with
   the rest of the request (a few dozen characters).
8. When a buyer is assigned — at approval (`finalize_purchase_request`) or later
   (`handle_assign`) — `_send_assignee_dm` remains the only DM implementation. After the
   email draft and attachments it posts the DM card as its own message and **returns**
   `(dm_channel, dm_ts)`; the caller stores them in the thread card's payload before that
   card is updated. A failed DM card is logged and alerted to the admin channel; it never
   reverses the approval.
9. The DM card shows: item, vendor, total, row, the stage, a link to the thread card
   (`chat_getPermalink`; omit the link line if the call fails), and the one next-step
   button for the stage — Mark Processed, then Mark Confirmed, then Mark Delivered.
   **No Cancel button.** Its button `value` holds only the pointer:
   `{"thread_channel": …, "thread_ts": …, "card_ts": …}` — no request state.
10. New action ids in `config`: `dm_req_processed`, `dm_req_confirmed`,
    `dm_req_delivered`. One shared listener body (not three copies) does, in order:
    ack; read the pointer; load the thread card (`slack_io.get_card_payload` /
    `find_card_in_thread`) — the request, history and **current state come from the
    thread card, never from the DM card**; run the permission check (item 12); refuse a
    stale click; then call the same `lifecycle.handle_processed`, `handle_confirmation`
    or `handle_delivery` the thread buttons call, with `channel` and `card_ts` set to the
    thread card's, and a `say` that posts into the thread. Nothing about processing is
    reimplemented.
11. **A stage click on either card moves both.** `lifecycle.sync_dm_card(client, req,
    state, history)` rebuilds and `chat_update`s the DM card from the `dm_channel` /
    `dm_ts` in the request; it is called from the success path of `handle_processed`,
    `handle_confirmation`, `handle_delivery`, `handle_cancel` and `handle_assign`. It is
    a no-op when the request has no DM card. Because the `@Purchasing processed`
    keyword calls the same handlers, it refreshes the DM card too.
    - After delivered, or after cancel, the DM card has no buttons and one line saying
      so.
    - `handle_assign` on a reassignment first retires the old buyer's DM card ("Reassigned
      to <name>"), then sends the new buyer a fresh one (items 7–8).
    - A DM click whose button stage is behind the thread card's state is refused
      privately with "already <stage>", and the DM card is refreshed to match. A DM click
      when the thread card cannot be found is refused privately and alerted.
12. **One permission predicate** `admin.can_update_request(user_id, assignee_id) -> bool`:
    true for the assignee, an admin, or an approver. It replaces the inline checks in the
    `req_processed`, `req_confirmed`, `req_delivered` listeners and is used by the DM
    listener too. Refusal (private, nothing written): `🔒 Only the assigned buyer
    (<@ID>), an admin or an approver can update this request.` An unassigned request
    keeps `⚠️ This request must be assigned to a buyer …` for Mark Processed and gets the
    same for the other two. The registered-in-the-roster check stays.

## Testing decisions

- Fake the Slack client; drive the real Bolt listeners (find them in `app.app._listeners`
  as `tests/test_regression_guards.py` does), the real handlers, the real `log_writer`
  on a temporary copy of the workbook (copy the `temp_workbook` and `sync_queue`
  fixtures from `tests/test_29_approval_archives_bom.py`). Never the live workbook or
  roster.
- **Events:** a `message_changed` event with no user, and one with a `user` but subtype
  `message_deleted`, produce no `say`, no exception, no dispatcher call. A plain message
  and a `file_share` still reach their handlers.
- **DM help:** `flurb` in a DM → one message whose blocks contain the help text and a
  button with action id `start_purchase_interview`. `remve-vendor` in a DM → the "did
  you mean" reply and no help text. The same `flurb` in a channel mention → ticket 53's
  reply and **no** button (absence asserted).
- **No card in the thread at approval**: thread with no card,
  approve through the real listener → exactly one `chat_postMessage` with an
  `approved`-state card, metadata present, the workbook row written. With a card
  present → `chat_update` and **no** new post.
- **Loud failure:** parse failure and card-post failure each produce exactly one
  `chat_postMessage` to the alert channel whose text contains the file name and the
  error text; with the alert channel unset, no exception.
- **Linked cards:** approve with an assignee → the DM card is posted, its `ts` appears in
  the thread card's payload. A DM `dm_req_processed` click by the assignee → the
  workbook's Date Processed cell for the row is set exactly once **and** both cards were
  updated to the processed stage with a Mark Confirmed button. Then the same click again
  (stale) → refused privately, no second workbook write (assert the cell unchanged).
- **A thread click also updates the DM card.** And `@Purchasing processed` does too.
- **Permissions:** a different buyer, and a requester who is nobody, clicking the DM
  button → private refusal, no workbook write, no `chat_update` (absence). The
  approver and an admin succeed. Same three cases on the thread buttons.
- **Reassign:** after `assign` to a second buyer, the first buyer's DM card was updated to
  a no-button retired state and the second buyer's DM card exists.
- **Cancel:** the DM card was updated to a no-button retired state.
- Tests must fail on today's code for the behaviour they name; none may be weakened to
  pass (ADR 0001).

## Tickets

Published in `issues/`, numbered from 62.

- 62 — ignore Slack's own message events (item 1). Blocked by 51.
- 63 — a DM with no close match gets the help text and a Start button (items 2–3). Blocked
  by 53, 62.
- 64 — approval posts a card when none exists (item 4). Blocked by 57 (same function).
- 65 — `slack_io.alert_admins`; a failed drop or card is reported loudly (items 5–6).
  Blocked by 64.
- 66 — one permission rule for the three stage buttons: assignee, admin or approver
  (item 12). Blocked by 58 (same denial strings).
- 67 — the assigned buyer's DM carries a card; its address is recorded on the thread card
  (items 7–9). Blocked by 64, 65.
- 68 — a click on the DM card advances the request (item 10). Blocked by 66, 67.
- 69 — both cards move together: every stage, cancel, reassignment, stale click (item 11).
  Blocked by 68.
- 70 — **ready-for-developer:** confirm the Slack app's event subscriptions and drop a test
  EPIF. No blockers — do it first.
- 71 — **ready-for-developer:** deploy and verify. Blocked by 62–70.

## Out of scope

- Filling the interview from the DM's text or link (rejected: fragile, and a wrong guess
  becomes a wrong purchase).
- Reading thread replies to detect "sent" or "ordered" (the bot acts only when addressed).
- A Cancel or Decline button on the DM card.
- Changing the workbook layout, the four stage words, or the email draft text.
- Renaming anything in `p_bot.*`.
