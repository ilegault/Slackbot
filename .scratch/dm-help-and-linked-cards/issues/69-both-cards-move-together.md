# 69: Both cards move together — every stage, cancel, reassignment and a stale click

**Status:** done

**Runner:** any

**Auto-merge:** yes

**Blocked by:** 68

**Spec:** `.scratch/dm-help-and-linked-cards/spec.md` (item 11)
**Binding:** `docs/adr/0010-linked-cards-and-direct-message-help.md` decision 3, `AGENTS.md` invariant 1 (the keyword and the button share one handler, so both refresh the DM card), ADR 0001

## What to build

Whichever card is clicked — or the `@Purchasing processed` keyword is used — the thread card and
the DM card end up at the same stage with the same next button. The DM card is a view: it is
rebuilt from the thread card's request (which carries `dm_channel` and `dm_ts`, ticket 67).

1. Extend `blocks.build_dm_card_blocks` with `note: str | None = None`. States `cancelled` and
   `reassigned` render the section plus one line (`🚫 Cancelled`, or `↪️ <note>`) and **no
   buttons**; `delivered` renders `✅ Delivered` and no buttons. Other states are unchanged.
2. `lifecycle.sync_dm_card(client, request, state, channel, thread_ts, card_ts, history=None, note=None) -> bool`:
   a no-op returning `False` when `request` has no `dm_channel` / `dm_ts`; otherwise
   `client.chat_update(channel=dm_channel, ts=dm_ts, text=…, blocks=blocks.build_dm_card_blocks(…))`
   (permalink built as in `_send_assignee_dm`, omitted if it fails) and returns `True`. It never
   raises: on any exception it logs a WARNING and calls
   `slack_io.alert_admins(client, text_rules.format_card_failure_alert("update the buyer's DM card", channel, thread_ts, None, str(error)))`.
3. Call it, after the thread card's own `chat_update`, from the `on_success` of `handle_processed`
   (state `processed`), `handle_confirmation` (`confirmed`) and `handle_delivery` (`delivered`),
   passing the `target_req`, `target_card_ts` and `target_hist` those functions already hold; and
   from `handle_cancel` after its `chat_update` (state `cancelled`, `req_data`, `msg_ts`).
4. In `handle_assign`, when `current_assignee` is set and `req_data` has DM references, call
   `sync_dm_card(..., state="reassigned", note=f"Reassigned to {target_name}")` on the **old**
   references **before** the new DM card replaces them (ticket 67's flow then stores the new
   references in the thread card).
5. In `app.handle_dm_stage_action` (ticket 68), after refusing a stale click, call
   `lifecycle.sync_dm_card` with the thread card's current state so the DM card is refreshed.

## Acceptance criteria

- [x] **Retired states have no buttons.** In `tests/test_69_cards_move_together.py`,
  `build_dm_card_blocks` for `cancelled`, `reassigned` (with a `note`) and `delivered` returns no
  `actions` block and its section/context text contains `Cancelled`, the note, and `Delivered`
  respectively.
- [x] **A thread click moves the DM card, and the keyword does too.** Fixtures as ticket 46 with
  `sync_queue`. A request whose payload has `dm_channel="D_BUYER"`, `dm_ts="9.9"`: the assignee's
  Mark Processed click on the thread card produces a `chat_update(channel="D_BUYER", ts="9.9")`
  whose blocks hold `Mark Confirmed`; the same via real `app.dispatch_command` with text `processed`
  (fake replies contain the card and a `Logged to row 17` message). A request **without** the two
  keys produces exactly one `chat_update` (the thread card's) and none with `ts == "9.9"` (absence).
- [x] **A run from the DM keeps both cards level.** Click `dm_req_processed`, then `dm_req_confirmed`,
  then `dm_req_delivered` through `app.handle_dm_stage_action`, feeding each `chat_update` back into
  the fake thread so the next click sees it: after each click both cards' blocks show the same next
  button; after delivered neither has an `actions` block.
- [x] **Cancel and reassignment retire cards.** `handle_cancel` on an approved request with DM
  references: the DM card is updated with no `actions` block and text containing `Cancelled`; with no
  references, no DM update. `handle_assign` moving an assigned request to a second buyer: the first
  DM card is updated to `reassigned` (contains `Reassigned to`, no `actions`), a DM card is posted to
  the second buyer, and the thread card's last `chat_update` holds the second card's references.
- [x] **A stale click refreshes; a failed refresh never blocks.** A `dm_req_processed` click when the
  thread is already `processed`: refused with `already`, and the DM card is updated to the `processed`
  state's blocks. With `chat_update` raising only for the DM card, a normal Mark Processed click still
  calls `update_row` once and updates the thread card, and exactly one message goes to the alert
  channel containing `update the buyer's DM card`.

**Tests may fake:** the Slack client, `log_writer` I/O as ticket 46's fixtures do. **Must be real:**
the lifecycle handlers, `sync_dm_card`, `dispatch_command`, `app.handle_dm_stage_action`, `blocks`.

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
- Extended `blocks.build_dm_card_blocks` with optional `note` argument and support for retired states (`cancelled`, `reassigned`, `delivered`), ensuring no actions blocks are rendered and respective status lines are included.
- Implemented `lifecycle.sync_dm_card` to rebuild and update the linked DM card via `chat_update`, safely catching exceptions and alerting admin channel without blocking lifecycle operations.
- Wired `sync_dm_card` into `on_success` of `handle_processed`, `handle_confirmation`, and `handle_delivery`.
- Wired `sync_dm_card` into `handle_cancel` to retire the DM card.
- Wired `sync_dm_card` into `handle_assign` to retire the previous buyer's DM card prior to dispatching the new buyer's card.
- Updated `app.handle_dm_stage_action` to invoke `sync_dm_card` when refusing stale clicks so the DM card is refreshed to the thread card's current stage.
- Added comprehensive test suite in `tests/test_69_cards_move_together.py` covering all acceptance criteria.
- Full gate passed cleanly (ruff, check_tests_first, full pytest suite 548 passed, 31 skipped).
