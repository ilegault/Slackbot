# 50: One items box everywhere

**Status:** ready-for-agent

**Runner:** any

**Auto-merge:** yes

**Blocked by:** None

**Spec:** `.scratch/bom-lab-layout/spec.md`
**Binding:** `docs/adr/0006-bom-line-items-and-editable-posted-cards.md` decisions 1–2 (one
items form, one format), ADR 0001; AGENTS.md invariant 1

## What to build

Line items are typed into three modals, and each builds its own input block in
`src/blocks.py`:

1. `build_items_view` (the **Add items / Edit items** modal on a PDF-born card), action_id
   `action_line_items`.
2. `build_stage2_view` (interview Screen 2), action_id `line_items`, optional,
   `max_length=config.MAX_LINE_ITEMS_LEN`.
3. `build_workday_details_view` (the bare-thread **Fill in details** modal), action_id
   `line_items`, optional. Its hint says "qty, unit, name, part, price, link. Last line
   must be shipping if not $0" and its placeholder is `2 EA | Flask | FL-1 | 10.00` —
   both wrong: `bom.parse_line_items` rejects `2 EA` as a quantity and shipping may be on
   any line. It also has no `max_length`.

Add one builder to `src/blocks.py`:

```python
def line_items_input(action_id: str, *, optional: bool, initial_value: str | None = None,
                     max_length: int | None = None) -> dict:
```

It returns the input block with `block_id` `block_line_items`, label
`Line items (optional)` when `optional` else `Line items`, placeholder
`qty | name | part # | unit price | link | description\nshipping | 24.50`, and the hint text
currently in `build_items_view`:
`One item per line (pipe or tab separated): qty | name | part # | unit price | link | description. Optional line: shipping | <amount>`.
It sets `initial_value` and `max_length` on the element only when they are not None.

All three views call it. Keep each view's existing action_id, optional flag, and initial
value source so no submit handler changes its field lookup. The Workday view gets no
`max_length` (its state is not carried to another screen).

Then fix `handle_workday_details_submit` in `src/app.py` (~line 572): it passes the
`parse_line_items` error **list** as the value in `ack(response_action="errors", ...)`.
Slack requires a string. Join with `"\n"`, exactly as `handle_items_modal_submit` does.

## Acceptance criteria

- [ ] **The example we show parses.** In `tests/test_50_one_items_box.py`: for each of the
  three views, find the `block_line_items` block, take its placeholder text, run
  `bom.parse_line_items` on it, and assert zero errors and one item plus shipping 24.50.
  This fails today for the Workday view. Build the views with their real builders; fake
  nothing but inputs.
- [ ] **Same hint and placeholder in all three.** Assert the three blocks' `hint` and
  `placeholder` text are identical to each other, and that Screen 2's element still has
  `max_length == config.MAX_LINE_ITEMS_LEN`.
- [ ] **A bad paste in the Workday modal shows the error.** Call
  `app.handle_workday_details_submit` with `block_line_items.line_items.value` set to
  `2 EA | Flask | FL-1 | 10.00`, using the **real** `bom.parse_line_items` (do not
  monkeypatch it — the existing test in `tests/test_40_bare_thread_approval.py` mocks it
  to return `None` errors, which is how this bug hid). Assert `ack` was called once with
  `response_action="errors"` and that `errors["block_line_items"]` is a `str` containing
  `line 1:`. Assert `lifecycle.finalize_purchase_request` was **not** called. Copy the
  fake-client setup from `test_fill_in_details_writes_row_and_updates_card` in that file.
- [ ] No other file under `src/` builds a `block_line_items` block: a test greps
  `src/blocks.py` source for the literal `"block_line_items"` and asserts it appears
  exactly once (inside `line_items_input`).
- [ ] Full gate green, in CI order: `ruff check .`, `python scripts/check_tests_first.py`,
  `pytest -q`.

## Out of scope

- The paste format and `bom.parse_line_items` itself.
- Adding the items box to any modal that does not have one.
- The BOM spreadsheet layout (ticket 49).

## Comments
