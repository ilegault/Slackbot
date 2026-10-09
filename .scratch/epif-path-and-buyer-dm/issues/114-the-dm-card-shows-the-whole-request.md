# 114: The DM card shows the whole request

**Status:** ready-for-agent

**Runner:** any

**Auto-merge:** yes

**Blocked by:** 111, 113

**Spec:** `.scratch/epif-path-and-buyer-dm/spec.md` (Part D, stories 13–14)
**Binding:** `docs/adr/0018-the-path-is-the-payment-method-and-the-dm-card-shows-the-request.md` (decision 2); `docs/adr/0010-linked-cards-and-direct-message-help.md` (decisions 2–3: the DM card is a view, and the thread card is the store)
**Glossary:** `CONTEXT.md` — **DM card**

## What to build

The buyer's DM card shows every line the thread card shows, plus the row, the History,
the stage and the link to the thread. It does this in every state, including stage
updates, reassignment, cancel and delivery. Today it shows only "item — vendor, price".
It stays a view; nothing about its buttons, picker or pointer changes.

1. `src/blocks.py` `build_dm_card_blocks` gains two keyword parameters,
   `history: list | None = None` and `route: str = "workday"`. Its section text is,
   in order:
   - `🛒 *Place this in Workday*` when `route == "workday"`, else
     `📧 *Email the EPIF to purchasing*`;
   - `blocks.request_summary_lines(request, state)[1:]` (ticket 113's function, minus its
     own header line);
   - `• *Row:* {row}` when the request has a row;
   - `Stage: *{state}*`;
   - the thread link line, as today;
   - the retired-state line (cancelled / reassigned / replaced / delivered), as today.

   Remove the DM card's own `*Expected delivery:*` line: the summary lines already carry
   it.
2. When `history` is non-empty, `build_dm_card_blocks` adds the same History `context`
   block that `build_request_blocks` adds (`*History:*` then one `• line` per entry),
   directly after the section. Buttons, the buyer picker and the actions `block_id`
   pointer are unchanged.
3. `src/lifecycle.py` `sync_dm_card` passes `history=history` and
   `route=interview.get_request_route(request)` to `build_dm_card_blocks`.
4. `src/nudge.py` `_repost_dm_card` passes `history=history` and
   `route=interview.get_request_route(req_data)` to `build_dm_card_blocks`.
5. Update the `build_dm_card_blocks` docstring: the DM card shows the whole request
   (ADR 0018). It is still a view.

`lifecycle._send_assignee_dm` is **not** changed here; ticket 115 does that.

## Acceptance criteria

- [ ] New `tests/test_114_dm_card_whole_request.py`:
  - build a request with every field set and a row, then call `blocks.build_dm_card_blocks(state="approved", request=..., ..., history=["Approved by the approver on 10/09/26 10:00"], route="workday")`;
  - assert that every line of `blocks.request_summary_lines(request, "approved")[1:]` appears in the section text, and that the section starts with `🛒 *Place this in Workday*`;
  - assert it contains `• *Row:* 7` and `Stage: *approved*`;
  - assert the next block is a `context` block whose text contains `*History:*` and the history line.
- [ ] Same file: with `route="epif"` the section starts with `📧 *Email the EPIF to purchasing*`. For states `processed`, `confirmed`, `cancelled`, `reassigned` (with a note) and `delivered`, every summary line is still present, and the retired states still show their status line and no `actions` block.
- [ ] Same file: `lifecycle.sync_dm_card` on a request with `payment_method="P-card"`, `dm_channel` and `dm_ts`, given a history list, calls `chat_update` with blocks whose section starts with `📧 *Email the EPIF to purchasing*` and whose History block holds that history.
- [ ] Existing DM card tests (`tests/test_67_dm_card.py`, `tests/test_69_cards_move_together.py`, `tests/test_74_dm_card_picker.py`, `tests/test_88_confirmed_nudge.py`, `tests/test_91_expected_delivery.py`, `tests/test_98_buyer_picker_lists_buyers.py`) pass. Any assertion on the old first line `🛒 *{item}* — {vendor}, {price}` or the old expected-delivery line is rewritten in place to assert the new text, keeping the same test name and number of assertions. No test is deleted.

May fake: the Slack client (`MagicMock`). Must be real: `blocks.build_dm_card_blocks`, `blocks.request_summary_lines`, `interview.get_request_route`, `lifecycle.sync_dm_card`.

## Gate

Run all four, in CI's order, and all must pass:

    ruff check .
    python scripts/check_tests_first.py
    python tools/type_gate.py
    pytest --tb=short -q -n auto --dist loadfile

Tests need `SLACK_BOT_TOKEN=xoxb-test-not-a-real-token`, `SLACK_APP_TOKEN=xapp-test-not-a-real-token` and `PYTHONUTF8=1` in the environment, as `.github/workflows/tests.yml` sets.

## Comments
