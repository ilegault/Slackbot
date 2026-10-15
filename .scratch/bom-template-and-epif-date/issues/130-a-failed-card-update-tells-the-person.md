# 130: A failed card update tells the person who acted

**Status:** in-progress

**Runner:** any

**Auto-merge:** yes

**Blocked by:** None (can start immediately)

**Spec:** `.scratch/bom-template-and-epif-date/spec.md` (Part D, story 27)
**Binding:** `docs/adr/0001-tests-first-and-no-muted-failures.md`
**Glossary:** `CONTEXT.md` — **Edit**, **The request message / the card**

## What to build

When `chat_update` fails for an **Edit** (`lifecycle.handle_request_edit`, which logs
`Failed to chat_update card %s with edits`) or for Add items (`lifecycle.handle_items_update`,
`... with new items`), only the log records it today. The requester believes the edit landed.

On that failure, the person who acted must be told with `slack_io.tell(client, user_id, text)`.
That function is a DM, because a view submission has no `response_url`. The message is:

`⚠️ Your edit to <item description> was not saved — Slack refused the update (<error>). Nothing changed on the card.`

Here `<error>` is the Slack error string, for example `invalid_blocks`. The existing log line
stays. The thread gets no "edited" history line when the update failed.

## Acceptance criteria

- [ ] `test_failed_edit_update_tells_the_editor`:
  - Drive `app.handle_edit_submit` with a fake client whose `chat_update` raises `SlackApiError` with `{"ok": False, "error": "invalid_blocks"}`.
  - One message is posted to the editor's DM containing `was not saved` and `invalid_blocks`.
  - No `chat_postMessage` to the thread contains the edit's history text.
- [ ] `test_failed_items_update_tells_the_editor`: the same, through `app.handle_items_modal_submit`.
- [ ] Both functions above fail on today's code. (no test: a constraint on the two tests above)

May fake: the Slack client (raising `slack_sdk.errors.SlackApiError` with a real `SlackResponse`-like `response` dict, as `tests/test_65_loud_card_failures.py` does). Must be real: the handlers under test.

## Gate

Run all four, in CI's order, and all must pass:

    ruff check .
    python scripts/check_tests_first.py
    python tools/type_gate.py
    pytest --tb=short -q -n auto --dist loadfile

Tests need `SLACK_BOT_TOKEN=xoxb-test-not-a-real-token`, `SLACK_APP_TOKEN=xapp-test-not-a-real-token` and `PYTHONUTF8=1` in the environment, as `.github/workflows/tests.yml` sets.

The gate holds a PR that adds a new test which already passes on today's code. Where a ticket says checks share one test function, keep them together so the function fails on the base commit.

## Comments
