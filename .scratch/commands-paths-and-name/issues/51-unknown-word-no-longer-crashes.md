# 51: An unknown word no longer crashes the bot

**Status:** in-progress

**Runner:** any

**Auto-merge:** yes

**Blocked by:** None (can start immediately)

**Spec:** `.scratch/commands-paths-and-name/spec.md`
**Binding:** `docs/adr/0009-keywords-storage-settings-and-the-bot-name.md` decision 2, ADR 0001

## What to build

Today any word the bot does not recognise in an `@Purchasing` mention or a DM crashes
it with `ValueError: respond is unsupported here as there is no response_url`, and
the crash alert fires. `on_mention` and `on_direct_message` in `src/app.py` take
`respond` out of Bolt's `context` and pass it to `dispatch_command`. On an event Bolt
still puts a `respond` there, but calling it raises because an event has no
`response_url`. The unknown-word branch at the end of `dispatch_command` checks
`if respond and callable(respond)` — which is true — and calls `slack_io.deny`.

Fix: `on_mention` and `on_direct_message` stop passing `respond` to
`dispatch_command`. `dispatch_command`'s unknown-word branch always replies with
`say(text=..., thread_ts=thread_ts)`. Any other branch of `dispatch_command` that
forwards `respond` into a handler (for example `ops.handle_remove_member`) receives
`None` from the event path and uses its existing `say` fallback. Do not change the
reply text in this ticket; ticket 53 does. Update `slack_io.deny`'s docstring to say
it is for slash commands and block actions only, never the event path, and why.

## Acceptance criteria

- [ ] **The crash regression.** In `tests/test_51_unknown_word_no_crash.py`: find the
  real `app_mention` listener in Bolt's listener registry (copy how an existing test
  finds a registered listener; do not call a monkeypatched stand-in), and invoke it with
  an event whose text is `<@BOT> flurb`, a fake client, a fake `say` that records calls,
  and a context whose `respond` raises `ValueError("respond is unsupported here as there
  is no response_url")` when called — exactly as Bolt's does on an event. Assert no
  exception, exactly one `say` call, `thread_ts` equal to the event's `ts`, and text
  containing `flurb`. This test must fail on today's code.
- [ ] **The same for a DM.** Invoke the real `message` listener with `channel_type`
  `im`, text `flurb`, and the same raising `respond`. Assert no exception and one `say`
  call.
- [ ] **A slash command still replies privately.** An existing test that asserts
  `/purchasing-help` or `/roster-list` replies through `respond` with
  `response_type="ephemeral"` still passes unchanged (name it in the PR description).
- [ ] **A denial on the event path goes to the thread.** A non-admin sends
  `@Purchasing remove-member <@U2>` through the real `app_mention` listener with the
  raising `respond`: no exception, one `say` containing `Only bot administrators`, and
  the temp roster file still lists `U2` (assert the absence of the removal). Use a temp
  copy of the roster, never the real `roster.json`.
- [ ] `slack_io.deny`'s docstring states it is not for the `app_mention` / `message`
  event path and why.

## Gate

Run in this order, exactly as CI does. Zero failures before you push.

```
ruff check .
python scripts/check_tests_first.py
pytest -q --tb=short --durations=25
```

## Comments

