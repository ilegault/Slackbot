# 129: Every button value fits for the largest request the forms allow

**Status:** ready-for-agent

**Runner:** any

**Auto-merge:** yes

**Blocked by:** 122

**Spec:** `.scratch/bom-template-and-epif-date/spec.md` (Part D, stories 26, 28)
**Binding:** `docs/adr/0001-tests-first-and-no-muted-failures.md`
**Glossary:** `CONTEXT.md` — **The request message / the card**, **DM card**

## What to build

On 2026-10-13 an **Edit** failed at `chat_update` with `invalid_blocks: must be less than 2001
characters`, on all three buttons of the card. On 2026-09-29 the same error stopped a card being
posted. Slack caps a button `value` at 2,000 characters.

The card's buttons each serialise the request into their `value` (`blocks.build_request_blocks`,
`btn_value = json.dumps(...)` with `safe_req`). `safe_req` already drops `items`, `shipping` and
`attachments`, but other fields can still grow:

- the raw `line_items` paste text, which can be up to 1,500 characters;
- `raw_fields`;
- long `purpose` / `item_description`;
- `history`.

Find which fields overflow and fix it at the builder. Every button value on the thread card and
the DM card must stay at or under 2,000 characters for the largest request the forms allow. What
the next click needs must still be in the value or recoverable from the card. Anything unbounded
moves to the message metadata, as line items already do (AGENTS.md trap 9), or is dropped if
nothing reads it. Record the cause in `blocks.build_request_blocks`'s docstring.

## Acceptance criteria

- [ ] New `tests/test_129_button_values_fit.py`, one function `test_every_button_value_fits_for_the_largest_request`:
  - It builds a request at every form maximum: each text field at its modal `max_length`, read from the real `blocks.build_stage2_view`; a 1,500-character `line_items` string; 10 quotes; `raw_fields` with every EPIF field filled at 200 characters; 12 history lines of 120 characters.
  - It renders it through `blocks.build_request_blocks` for every state that has buttons, and through `blocks.build_dm_card_blocks`.
  - It asserts every `value` in every button and overflow option is ≤ 2,000 characters.
  - It must fail on today's code.
- [ ] `test_a_large_edit_reaches_the_card` drives `app.handle_edit_submit` for such a request with the fake client, as `tests/test_32_edit_a_posted_card.py` does.
  - The fake `chat_update` raises `SlackApiError` when any button value exceeds 2,000 characters, mirroring Slack.
  - The update succeeds, and the new card shows the edited purpose.
- [ ] `test_largest_request_moves_through_the_stages`: a request built at that maximum, with the same limit-enforcing fake, is approved, marked processed and marked confirmed. Reuse the setup of an existing test that drives approve → processed. Each step's card update succeeds.

May fake: the Slack client, with `chat_update`/`chat_postMessage` enforcing the 2,000-character limit as Slack does. Must be real: the `blocks` builders and the handlers under test.

## Gate

Run all four, in CI's order, and all must pass:

    ruff check .
    python scripts/check_tests_first.py
    python tools/type_gate.py
    pytest --tb=short -q -n auto --dist loadfile

Tests need `SLACK_BOT_TOKEN=xoxb-test-not-a-real-token`, `SLACK_APP_TOKEN=xapp-test-not-a-real-token` and `PYTHONUTF8=1` in the environment, as `.github/workflows/tests.yml` sets.

The gate holds a PR that adds a new test which already passes on today's code. Where a ticket says checks share one test function, keep them together so the function fails on the base commit.

## Comments
