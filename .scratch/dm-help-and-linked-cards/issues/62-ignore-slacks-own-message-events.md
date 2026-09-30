# 62: The bot ignores Slack's own message events

**Status:** done

**Runner:** any

**Auto-merge:** yes

**Blocked by:** 51

**Spec:** `.scratch/dm-help-and-linked-cards/spec.md` (item 1)
**Binding:** `docs/adr/0010-linked-cards-and-direct-message-help.md` decision 6, `docs/adr/0001-tests-first-and-no-muted-failures.md`

## What to build

In production a member's DM containing a link was followed two seconds later by a second
`message` event with **no user and empty text** — Slack editing the message when it
unfurled the link. `on_direct_message` in `src/app.py` only returns early for
`subtype == "bot_message"` or a `bot_id`, so the edit event reached
`dispatch_command` as if a person had typed nothing. After ticket 51 stops the crash, the
bot would answer that event with an "I don't know" reply nobody asked for.

Add `config.HUMAN_MESSAGE_SUBTYPES = (None, "file_share", "thread_broadcast")`. At the top
of `on_direct_message`, before the existing bot check's log lines or any other work,
return when `event.get("user")` is empty or `event.get("subtype")` is not in that tuple
(a missing `subtype` key is `None`). The listener logs nothing at INFO for such an event.
The existing `bot_message` / `bot_id` check stays. No other behaviour of the listener
changes: a DM still goes to the FAQ layer then `dispatch_command`; a PDF in a channel
still goes to `lifecycle.handle_epif_drop`.

## Acceptance criteria

- [x] **The listener is the registered one.** In `tests/test_62_ignore_slack_events.py`,
  assert `app.on_direct_message` is the `ack_function` of a listener in
  `app.app._listeners` (walk the registry as `tests/test_regression_guards.py` does; do not
  build a stand-in), then call it directly in the tests below.
- [x] **An edit event with no user does nothing.** Event
  `{"type": "message", "subtype": "message_changed", "channel": "D1", "channel_type": "im", "message": {"text": "x"}}`
  with a fake `client` and a recording `say`: no exception, `say` not called,
  `client.mock_calls == []`, and `caplog` holds no record containing `Received DM`. This
  test must fail on the code as it is once 51 has landed.
- [x] **A deletion by a real user does nothing.** Event with `"user": "U1"`,
  `"subtype": "message_deleted"`, `channel_type` `im`: same assertions.
- [x] **A person's DM still works.** Event `{"user": "U1", "channel": "D1", "channel_type": "im", "ts": "1.1", "text": "help"}`
  produces exactly one `say` call whose text contains the help text (`blocks.get_help_message()`).
- [x] **A dropped PDF still reaches the drop handler.** Event with `"subtype": "file_share"`,
  `"channel_type": "channel"`, `"user": "U1"`, `"files": [{"name": "EPIF_x.pdf"}]`, and
  `lifecycle.handle_epif_drop` replaced by a recorder (monkeypatch — that function is not
  the code under test here, the routing is): the recorder is called once with
  `channel`, `thread_ts` (the event's `ts`) and `user_id` `"U1"`.

**Tests may fake:** the Slack client (`MagicMock`), `say`, and `lifecycle.handle_epif_drop`
in the last criterion only. **Must be real:** `app.on_direct_message` and the registry check.

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

Completed 2026-09-30:
- Added `config.HUMAN_MESSAGE_SUBTYPES = (None, "file_share", "thread_broadcast")`.
- Updated `app.on_direct_message` to return early when `event.get("user")` is empty or `event.get("subtype") not in config.HUMAN_MESSAGE_SUBTYPES`.
- Added `tests/test_62_ignore_slack_events.py` verifying real listener registry registration, link unfurl edit events with empty user, user deletion events, human DM routing, and channel PDF drop handling.
- Local gate passes completely (ruff, check_tests_first, full pytest suite 498 passed, 31 skipped).


