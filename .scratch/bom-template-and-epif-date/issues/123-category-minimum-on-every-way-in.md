# 123: Category minimum on every way in

**Status:** in-progress

**Runner:** any

**Auto-merge:** yes

**Blocked by:** 121

**Spec:** `.scratch/bom-template-and-epif-date/spec.md` (Part A, stories 1–8)
**Binding:** `docs/adr/0001-tests-first-and-no-muted-failures.md`; `docs/adr/0017-p-card-under-5000-req-po-at-5000-and-over.md` (the same wiring as the P-card rule)
**Glossary:** `CONTEXT.md` — **Category minimum**, **EPIF**

## What to build

The bot refuses any request whose amount is below its category's minimum, wherever the request
comes in. The bot never changes the category itself.

- **Fabrication Component (4670):** at least $200.00. This is exactly the form's "at least $200".
- **Standalone Equipment >$5k (4602):** more than $5,000.00, the form's "more than 5k".

Today nothing compares the amount with the category. In production a $109.00 fabrication EPIF
was approved.

1. **`src/config.py`** — add `CATEGORY_MINIMUMS`, a dict from the category value string (the
   values of `CHECKBOX_TO_CATEGORY`) to `(amount: float, inclusive: bool)`:
   `"Fabrication Component (4670) > $200": (200.00, True)` and
   `"Standalone Equipment >$5k (4602)": (5000.00, False)`.
2. **`src/validators.py`** — add the pure function
   `category_minimum_problem(category, total_price) -> str | None` beside `pcard_problem`. It
   returns `None` when the category has no minimum, when `total_price` is `None`, or when the
   amount meets the minimum. Otherwise it returns:
   - inclusive: `"Fabrication Component (4670) needs a total of at least $200.00 — this is $109.00. Pick another category (usually Research/Lab Supplies or Repair & Maintenance)."`
   - exclusive: `"Standalone Equipment (4602) needs a total of more than $5,000.00 — this is $X. Pick another category."`

   Format money with a thousands separator and two decimals. The first word of each sentence
   is the category's display name, as written above.
3. **`validators.validate`** — append the problem next to the existing `pcard_problem` call.
   This covers dropped EPIFs and thread EPIFs (`lifecycle.handle_epif_drop`,
   `lifecycle.handle_epif_processing`), the interview's final validation
   (`lifecycle._process_interview_completion`), the Workday-details / switch-to-EPIF submit
   (`app.handle_workday_details_submit`) and Edit (`app.handle_edit_submit`).
   - In `app.handle_edit_submit`'s problem-to-block mapping, the sentence lands on
     `block_category`.
   - It contains "category" and none of the earlier keywords. Keep it that way, or put an
     explicit branch before the others.
4. **`app.handle_stage2_submit`** — straight after the existing `pcard_problem` refusal, refuse
   with `ack(response_action="errors", errors={"block_category": msg})`. This has to happen at
   Screen 2, for the same reason the P-card check does (see the comment there): Screen 3 has
   no category field.

## Acceptance criteria

- [ ] New `tests/test_123_category_minimum.py`, one table-driven test `test_category_minimum_problem`, asserts:
  - (Fabrication, 109.00) → the exact sentence in step 2 with `$109.00`;
  - (Fabrication, 199.99) → a sentence;
  - (Fabrication, 200.00) → `None`;
  - (Standalone, 5000.00) → a sentence containing `$5,000.00`;
  - (Standalone, 5000.01) → `None`;
  - ("Research/Lab Supplies (3105)", 5.00) → `None`;
  - (Fabrication, None) → `None`.
- [ ] `test_screen2_refuses_fabrication_under_200` drives `app.handle_stage2_submit` with a Screen 2 view state (build it the way `tests/test_109_pcard_limit.py` builds its Screen 2 submission), with category Fabrication and Total Price `109`.
  - The fake `ack` receives `response_action="errors"` with `errors["block_category"]` equal to the step 2 sentence.
  - `views_open`, `views_update` and `chat_postMessage` are never called.
  - The same test, with Total Price `200`, does not receive an errors ack.
- [ ] `test_edit_refuses_fabrication_under_200` drives `app.handle_edit_submit` (build the edit view state as `tests/test_32_edit_a_posted_card.py` does).
  - `errors["block_category"]` is the sentence.
  - The card is not updated: no `chat_update` call.
- [ ] `test_dropped_epif_with_fabrication_under_200_is_refused` fills the real template (`tests/fixtures/EPIF_TEMPLATE_HIRST.pdf`) with `epif_filler.fill_epif`, ticking Fabrication at `total_price=109.0`, parses it with `epif_parser.parse_epif`, and calls `validators.validate`. The returned problems include the sentence.
- [ ] `test_screen2_refuses_standalone_at_5000`: through `app.handle_stage2_submit`, Standalone Equipment at Total Price `5000` gets `errors["block_category"]` containing `$5,000.00`, and no view is opened or updated.

May fake: the Slack client and `ack`. Must be real: `validators`, `epif_filler.fill_epif` and `epif_parser.parse_epif` on the committed fixture. Patching `category_minimum_problem` or `validate` does not count.

## Gate

Run all four, in CI's order, and all must pass:

    ruff check .
    python scripts/check_tests_first.py
    python tools/type_gate.py
    pytest --tb=short -q -n auto --dist loadfile

Tests need `SLACK_BOT_TOKEN=xoxb-test-not-a-real-token`, `SLACK_APP_TOKEN=xapp-test-not-a-real-token` and `PYTHONUTF8=1` in the environment, as `.github/workflows/tests.yml` sets.

The gate holds a PR that adds a new test which already passes on today's code. Where a ticket says checks share one test function, keep them together so the function fails on the base commit.

## Comments
