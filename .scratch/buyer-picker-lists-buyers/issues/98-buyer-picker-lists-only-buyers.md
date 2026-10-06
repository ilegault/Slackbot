# 98: The buyer picker lists only buyers

**Status:** ready-for-agent

**Runner:** any

**Auto-merge:** yes

**Blocked by:** None (can start immediately)

**Binding:** `docs/adr/0014-the-buyer-picker-lists-only-buyers.md` (all five decisions); ADR 0001
**Glossary:** `CONTEXT.md` — **Buyer picker**, **Buyer**, **Button**

## What to build

The "Assign a buyer" dropdown on the posted card, the approved card and the DM card is a Slack
`users_select`, which lists the whole workspace and cannot be filtered. Replace it with a
`static_select` whose options are the buyers who have a roster name. The `action_id`s
(`config.ACTION_REQ_ASSIGN_SELECT`, `config.ACTION_DM_REQ_ASSIGN_SELECT`) and placeholder texts
stay exactly as they are.

1. `src/blocks.py` — new **pure** function (no roster or Slack access, so it can be tested on
   plain inputs):

   ```python
   def buyer_picker_options(buyer_ids: list[str], names: dict[str, str]) -> list[dict]:
   ```

   Returns one option per buyer ID whose `names.get(id)` is a non-empty string after `.strip()`,
   each shaped `{"text": {"type": "plain_text", "text": <name>}, "value": <slack id>}`, with
   duplicate IDs dropped, sorted by `name.casefold()`.

2. `src/blocks.py` — new helper:

   ```python
   def _buyer_picker(action_id: str, placeholder: str, assignee_id: str | None) -> dict | None:
   ```

   Calls `buyer_picker_options(roster.get_buyers(), roster.get_requesters())`. Returns `None`
   when the list is empty. Otherwise returns
   `{"type": "static_select", "action_id": action_id, "placeholder": {"type": "plain_text", "text": placeholder}, "options": <options>}`
   and, only when `assignee_id` equals one option's `value`, adds `"initial_option": <that same option dict>`.

3. `src/blocks.py` `build_request_blocks` — the two `users_select` blocks (the `state == "posted"`
   branch, placeholder `"Assign a buyer (optional)"`, and the `state == "approved"` branch,
   placeholder `"Assign a buyer"`) are each replaced by
   `_buyer_picker(config.ACTION_REQ_ASSIGN_SELECT, <same placeholder>, assignee_id)`; the result
   is appended to `elements` only when it is not `None`.

4. `src/blocks.py` `build_dm_card_blocks` — the `state == "approved"` `users_select` is replaced
   the same way with `config.ACTION_DM_REQ_ASSIGN_SELECT` and `"Assign a buyer"`, keeping the
   existing assignee lookup (`request["assignee_id"]`, falling back to `parsed["assignee_id"]`).
   The actions block and its `block_id` pointer are unchanged.

5. `src/app.py` — new module-level function:

   ```python
   def _picked_buyer_id(action: dict) -> str | None:
   ```

   Returns `action["selected_option"]["value"]` when present, else `action.get("selected_user")`,
   else `None`. Cards already posted in Slack still send the old `selected_user` shape until they
   are redrawn, so both must work. In `handle_req_assign_select_action` and
   `handle_dm_assign_select_action`, replace `selected_user = action.get("selected_user")` with
   `selected_user = _picked_buyer_id(action)`. Nothing else in either handler changes, and
   `lifecycle.handle_assign` is untouched — its roster check is what still refuses an old card's
   non-buyer pick.

Update the docstrings that say "users_select" in the two handlers and the module docstring at the
top of `src/blocks.py` (ADR 0005 line) to say "buyer picker (static_select of buyers, ADR 0014)".

## Acceptance criteria

New test file `tests/test_98_buyer_picker_lists_buyers.py`. Roster on a temp file using the
`clean_roster` fixture pattern from `tests/test_72_any_buyer_moves_a_request.py` (monkeypatch
`roster.ROSTER_PATH`, set `roster._DATA = None`). Use: buyers `U_BUYER_C` ("carol"),
`U_BUYER_A` ("Alice"), `U_BUYER_B` ("Bob"), `U_BUYER_NONAME` (no requesters entry); approver
`U_CHARLIE` ("Charlie H.") who is **not** a buyer; requester `U_REQ` ("Alex") who is not a buyer.

- [ ] **Pure function.** `buyer_picker_options(["U_C", "U_A", "U_A", "U_X", "U_BLANK"], {"U_C": "carol", "U_A": "Alice", "U_BLANK": "  ", "U_Q": "Quinn"})` returns exactly the two options for Alice then carol (values `"U_A"`, `"U_C"`), in that order; `buyer_picker_options([], {...})` returns `[]`.
- [ ] **Only buyers on all three cards.** With the temp roster, the picker element (found by `action_id`) on `build_request_blocks("posted", …)`, `build_request_blocks("approved", …)` and `build_dm_card_blocks("approved", …)` has `type == "static_select"`, and its option values are exactly `["U_BUYER_A", "U_BUYER_B", "U_BUYER_C"]` — `U_CHARLIE`, `U_REQ` and `U_BUYER_NONAME` absent. No element of type `users_select` appears anywhere in any of the three cards.
- [ ] **Pre-selection.** With `assignee_id="U_BUYER_B"`, each of the three pickers has `initial_option["value"] == "U_BUYER_B"` and that dict equals the matching entry in `options`. With `assignee_id="U_GONE"` (not a buyer) and with no assignee, the picker has no `initial_option` key and keeps its placeholder text.
- [ ] **No named buyers → no picker.** With a temp roster whose `buyers` is `[]`, none of the three cards contains an element with `action_id` `req_assign_select` / `dm_req_assign_select`, and the Approve button (posted) and Mark Processed button (approved, and DM card) are still present.
- [ ] **Both payload shapes assign.** Calling `app.handle_req_assign_select_action` with a body built like `_make_picker_body` in `tests/test_72_any_buyer_moves_a_request.py` but whose action carries `{"selected_option": {"value": "U_BUYER_C", ...}}` and **no** `selected_user` → the thread card's `chat_update` carries `assignee_id == "U_BUYER_C"` in a button value, same as the existing `selected_user` case. And `_picked_buyer_id({"selected_user": "U_X"}) == "U_X"`, `_picked_buyer_id({}) is None`.

**Existing tests to rewrite in place, same function names, no test deleted:** every assertion
on `type == "users_select"` or `initial_user` in `tests/test_17_buyer_picker.py`
(`test_build_request_blocks_posted_renders_users_select_and_approved_does_not`,
`test_users_select_initial_user_when_assignee_present`,
`test_selecting_buyer_rerenders_card_with_assignee_line_and_no_excel_write`),
`tests/test_72_any_buyer_moves_a_request.py` (`test_approved_card_has_picker`) and
`tests/test_74_dm_card_picker.py` (`test_dm_card_has_picker_only_while_approved`) becomes the
`static_select` / `initial_option["value"]` equivalent. Those tests must run against a temp roster
where the assignee they use is a named buyer — add the fixture where it is missing, otherwise the
picker is legitimately absent and the test fails for the wrong reason. The "no picker in
processed / confirmed / delivered" loops must check by `action_id`, not by element type, so they
cannot pass vacuously. Tests that only build action payloads with `selected_user` stay as they
are: that shape is still supported.

**Tests may fake:** the Slack client. **Must be real:** `blocks.buyer_picker_options`,
`blocks.build_request_blocks`, `blocks.build_dm_card_blocks`, the two `app` handlers,
`lifecycle.handle_assign`, the roster on a temp file.

## Out of scope

- The `@Purchasing assign @buyer` keyword and the `@buyer @Purchasing approved` mention — unchanged.
- Any live lookup when the dropdown opens (`external_select`, `app.options`) — rejected by ADR 0014 decision 2.
- Redrawing cards already in Slack when the buyers list changes.
- `docs/adr/`, `CONTEXT.md`, `AGENTS.md` — already updated by the planner.

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
