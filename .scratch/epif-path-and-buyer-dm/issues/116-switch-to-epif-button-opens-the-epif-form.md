# 116: The Switch to EPIF button opens the EPIF form

**Status:** ready-for-agent

**Runner:** any

**Auto-merge:** yes

**Blocked by:** 111, 113

**Spec:** `.scratch/epif-path-and-buyer-dm/spec.md` (Part E, stories 15–16)
**Binding:** `docs/adr/0007-purchase-path-and-generated-epif.md` (decision 5: switch until processed); `docs/adr/0018-the-path-is-the-payment-method-and-the-dm-card-shows-the-request.md` (decision 1); AGENTS.md invariant 1
**Glossary:** `CONTEXT.md` — **Workday path / EPIF path**

Supersedes the code half of ticket 42 (`.scratch/purchase-path-and-epif/issues/42-switch-workday-to-epif.md`).
That ticket was marked done by a PR that changed only the ticket file; no code from it
exists.

## What to build

A buyer who finds that a Workday-path vendor is not actually on Workday presses
**Switch to EPIF** on the approved thread card. The EPIF form opens, pre-filled from the
request. Submitting it is ticket 117; this ticket stops at the open form.

1. `src/config.py`: `ACTION_REQ_SWITCH_EPIF = "req_switch_epif"`.
2. `src/blocks.py` `build_request_blocks`: in the `approved` state, add a button
   "Switch to EPIF" (`action_id=config.ACTION_REQ_SWITCH_EPIF`, same `btn_value` as the
   other buttons, no `style`). Place it after Mark Processed and before Cancel. It is
   present only when `interview.get_request_route(request) == "workday"` **and** the
   request has no processed date. A processed card is never in the `approved` state, so
   the state check covers that. The DM card does not get this button.
3. `src/admin.py`: new `can_fill_or_switch(user_id, req_data, requester_name, resolved_actor_name) -> bool`,
   holding the four-way check that `handle_req_fill_details` and `handle_req_needs_epif`
   in `src/app.py` each write inline: the requester (by name or `user_id`), the assignee,
   any buyer while unassigned, or an admin. Both handlers call it instead of their
   inline copy. Their refusal text is unchanged.
4. `src/app.py`: new `@app.action(config.ACTION_REQ_SWITCH_EPIF)` handler
   `handle_req_switch_epif`, modelled on `handle_req_needs_epif`:
   - `ack`, then parse the button value and run the permission check (refuse with
     `slack_io.deny(respond, "🔒 Only the requester, assignee, a buyer while unassigned, or an admin can switch this to EPIF.")`).
   - Build `meta` with `route="epif"`, `vendor_choice=config.VENDOR_OTHER_OPTION`,
     `vendor_custom=<the request's vendor>`, the request's `resolved_name` / `user_id`,
     every pre-fill key `handle_req_edit_action` puts in its `meta` (`item_description`,
     `purpose`, `link`, `total_price`, contacts, date, room, project, fund, category,
     line items), and
     `"switch": {"channel", "thread_ts", "card_ts", "row", "approver", "assignee_id", "assignee_name"}`.
     Get `row` with `slack_io.find_row_in_thread(client, channel, thread_ts)`, as
     `lifecycle.handle_assign` does; the card payload does not carry it. If no row is
     found, refuse with `slack_io.deny(respond, "⚠️ I couldn't find this request's row, so I can't switch it.")`
     and do not open the form.
   - Open `blocks.build_stage2_view(meta)` with `views_open`, and log at INFO.
5. `src/blocks.py` `build_stage2_view`: pre-fill inputs when
   `meta.get("is_edit") or meta.get("switch")`. Today it pre-fills only for `is_edit`.
   `callback_id` stays the Screen 2 callback for a switch; only `is_edit` changes it.

## Acceptance criteria

- [ ] New `tests/test_116_switch_to_epif_button.py`, **one test function over a table**:
  - `build_request_blocks("approved", request)` with `payment_method="Workday"` has an action with `action_id == "req_switch_epif"`;
  - it has none with `payment_method="P-card"`;
  - it has none in states `posted`, `processed`, `confirmed` and `delivered`.
- [ ] Same file: `app.handle_req_switch_epif` pressed by the assignee calls `views_open` once. The view's `callback_id` is the Screen 2 callback. Its `private_metadata` has `route == "epif"` and a `switch` object with `card_ts` and `row`. The item-description input's `initial_value` equals the request's item.
- [ ] Same file: pressed by a user who is not the requester, not the assignee, not an admin, and not a buyer on an unassigned request, it calls `respond` with the 🔒 text and does **not** call `views_open`.
- [ ] Same file: `admin.can_fill_or_switch` returns True for each of the four allowed roles and False for a stranger. Existing Fill-in-details and This-needs-an-EPIF permission tests (`tests/test_40_bare_thread_approval.py`, `tests/test_41_this_needs_an_epif.py`) pass unchanged.

May fake: the Slack client (`MagicMock`), the roster (temp `roster.json`, as `tests/test_41_this_needs_an_epif.py` sets it up). Must be real: `blocks.build_request_blocks`, `blocks.build_stage2_view`, `interview.get_request_route`, `admin.can_fill_or_switch`, and the registered Bolt listener (find it in the app's listener registry as existing action tests do; do not call a re-implemented copy).

## Gate

Run all four, in CI's order, and all must pass:

    ruff check .
    python scripts/check_tests_first.py
    python tools/type_gate.py
    pytest --tb=short -q -n auto --dist loadfile

Tests need `SLACK_BOT_TOKEN=xoxb-test-not-a-real-token`, `SLACK_APP_TOKEN=xapp-test-not-a-real-token` and `PYTHONUTF8=1` in the environment, as `.github/workflows/tests.yml` sets.

## Comments
