# 138: `@Purchasing template` is no longer a keyword

**Status:** done

**Runner:** any

**Auto-merge:** yes

**Blocked by:** None (can start immediately)

**Spec:** `.scratch/blank-template-private-kit/spec.md` (decision 1)
**Binding:** `docs/adr/0002-request-lifecycle-and-surfaces.md` (the interface rule); `docs/adr/0001-tests-first-and-no-muted-failures.md`
**Glossary:** `CONTEXT.md` — **Template kit**, **Keyword**

## What to build

The template kit comes only from `/blank-template` (ticket 139 makes it private). The
undocumented keyword that posts it publicly goes away entirely.

1. **`src/config.py`** — delete `TEMPLATE_KEYWORDS = ("template", "blank epif", "blank form")`
   and remove `TEMPLATE_KEYWORDS` from `ALL_KEYWORD_TUPLES`. `CANONICAL_KEYWORDS` is derived
   from `ALL_KEYWORD_TUPLES`, so it loses `"template"` with no further edit.
2. **`src/app.py`, `dispatch_command`** — delete the branch
   `elif cmd in config.TEMPLATE_KEYWORDS: ops.handle_template_command(...)`. Nothing replaces
   it: `template` then falls through to the existing unknown-word `else` branch at the end of
   `dispatch_command`.
3. No existing test references `TEMPLATE_KEYWORDS`, so no other test changes.
4. Leave `ops.handle_template_command` and the `/blank-template` slash handler exactly as
   they are. Ticket 139 replaces them.

## Acceptance criteria

- [x] New file `tests/test_138_template_keyword.py`, `test_template_is_not_a_keyword`:
  `config` has no attribute `TEMPLATE_KEYWORDS`; no tuple in `config.ALL_KEYWORD_TUPLES`
  contains `"template"`, `"blank epif"` or `"blank form"`; `"template"` is not in
  `config.CANONICAL_KEYWORDS`.
- [x] `test_template_mention_gets_the_unknown_word_reply`: call `app.dispatch_command` the way
  `tests/test_onboarding_and_commands.py::test_assign_keyword_dispatch` does (fake `client`
  and `say`, `channel="C_TEST"`, `thread_ts="5555.66"`, `event_ts="5555.67"`,
  `text="@Purchasing template"`). Assert `say` was called exactly once, its `text` contains
  `I don't know "template"`, and `client.files_upload_v2` was not called. Do not patch
  `ops.handle_template_command`; ticket 139 replaces it.

May fake: the Slack client and `say`. Must be real: `config`, `app.dispatch_command`,
`text_rules.closest_keyword` and `text_rules.format_unknown_keyword_message`.

## Gate

Run all four, in CI's order, and all must pass:

    ruff check .
    python scripts/check_tests_first.py
    python tools/type_gate.py
    pytest --tb=short -q -n auto --dist loadfile

Tests need `SLACK_BOT_TOKEN=xoxb-test-not-a-real-token`, `SLACK_APP_TOKEN=xapp-test-not-a-real-token` and `PYTHONUTF8=1` in the environment, as `.github/workflows/tests.yml` sets.

The gate holds a PR that adds a new test which already passes on today's code. Both new
tests fail on today's code (the keyword exists and the mention uploads the EPIF).

## Comments
Done 2026-10-20: removed TEMPLATE_KEYWORDS from config and the dispatch branch in app.dispatch_command. Both criteria covered by tests/test_138_template_keyword.py. Gate green (ruff, tests-first, type_gate ratchet 95, pytest 883 passed).
