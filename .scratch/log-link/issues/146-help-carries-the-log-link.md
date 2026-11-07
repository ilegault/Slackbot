# 146: /purchasing-help carries the Log link

**Status:** ready-for-agent

**Runner:** any

**Auto-merge:** yes

**Blocked by:** 145

**Spec:** `.scratch/log-link/spec.md` (Implementation Decisions: Shared text in `blocks`, Help, The warning)
**Binding:** `docs/adr/0021-app-home-and-help-link-the-purchasing-log.md` (decisions 1, 4, 5); `docs/adr/0010-linked-cards-and-direct-message-help.md` decision 5 (help is packed into section blocks by `chunk_mrkdwn`); `docs/adr/0001-tests-first-and-no-muted-failures.md`
**Glossary:** `CONTEXT.md` — **Log link**

## What to build

`/purchasing-help` (and every other place that sends `blocks.get_help_message()`: the
`@Purchasing help` keyword and the DM help blocks) shows one clickable
"Purchasing Log" line directly under the bot's name, opening the **Log link**. When the
link is not set, the same line carries the not-set sentence instead. Help and App Home
use the same two strings and the same rule from ticket 145, so they cannot drift.

1. **`src/blocks.py` `get_help_message`** — call `_log_link()` (added in ticket 145) once.
   Insert one line directly after `"🤖 *Hirst Lab Purchasing Bot*\n\n"` and before
   `_INTERFACE_RULE`:
   - set: `f"*Purchasing Log:* <{url}|{_LOG_LINK_LABEL}>\n\n"`
   - not set: `"*Purchasing Log:* " + _LOG_LINK_NOT_SET + "\n\n"`
   Use the constants `_LOG_LINK_LABEL` and `_LOG_LINK_NOT_SET`; do not type either
   sentence a second time. Help stays plain mrkdwn text; nothing else in it changes.
   The warning for a malformed value comes from `_log_link()`, so help needs no logging
   code of its own.

## Acceptance criteria

New file `tests/test_146_log_link_help.py`. Set the setting only with
`monkeypatch.setattr(config, "PURCHASING_LOG_URL", ...)`. `nudge_settings.load` may be
faked as the existing help tests fake it; `blocks.get_help_message`, `blocks._log_link`
and `text_rules.log_link_url` must be the real ones.

- [ ] `test_help_links_the_log` — with `https://example.org/log?e=1`, `get_help_message()` contains `"*Purchasing Log:* <https://example.org/log?e=1|Open Purchasing Log>"`, and that line comes after `"🤖 *Hirst Lab Purchasing Bot*"` and before `blocks._INTERFACE_RULE` in the text (compare `str.index` positions).
- [ ] `test_help_not_set_shows_the_sentence` — parametrized over `""`, `"www.example.com/log"`, `"C:\\Users\\x\\Purchasing-Log.xlsx"`, `"https://exa mple.com"`: the text contains `"*Purchasing Log:* The Purchasing Log link isn't set up yet. Ask an admin."` and contains no `"<http"`.
- [ ] `test_help_and_app_home_share_the_log_link_strings` — with a good URL, `blocks._LOG_LINK_LABEL` appears in `get_help_message()` and equals the App Home Welcome button's `text.text`; with `""`, `blocks._LOG_LINK_NOT_SET` appears in both `get_help_message()` and the App Home Welcome section text (prior art: the shared-constant tests in `tests/test_09_app_home_help.py`).
- [ ] `test_help_malformed_setting_warns` — with `caplog` at `WARNING` and `www.example.com/log`, calling `get_help_message()` produces exactly one `WARNING` record whose message contains `PURCHASING_LOG_URL`; with `""` it produces none.
- [ ] `test_dm_help_blocks_carry_the_log_link` — with a good URL, joining the `text.text` of every section in `blocks.build_dm_help_blocks()` contains `"|Open Purchasing Log>"` (proves `chunk_mrkdwn` packing keeps the link intact).

No existing test is deleted, skipped or marked xfail.

## Gate

    ruff check .
    python scripts/check_tests_first.py
    python tools/type_gate.py
    pytest --tb=short -q -n auto --dist loadfile --durations=25

## Out of scope

App Home (ticket 145). The health screen and `docs/SETUP.md` (ticket 147). Rewording any
other help line. Thread cards, DMs other than help, nudges. Editing `docs/adr/`,
`CONTEXT.md` or `AGENTS.md`.

## Comments

