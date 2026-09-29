# 58: Slack text says "the Purchasing bot" and `@Purchasing`

**Status:** ready-for-agent

**Runner:** any

**Auto-merge:** yes

**Blocked by:** 52, 53, 55, 56, 57

**Spec:** `.scratch/commands-paths-and-name/spec.md`
**Binding:** `docs/adr/0009-keywords-storage-settings-and-the-bot-name.md` decision 8, ADR 0001

## What to build

The Slack app is named **Purchasing**. "P-Bot" and `@p-bot` still appear in what the bot
sends. Replace them: **"the Purchasing bot"** in prose, **`@Purchasing`** in commands.
This ticket runs last because every earlier ticket in this set edits the same strings.

Change every string the bot sends to Slack, including:
- `admin.build_health_blocks` header (`🩺 P-Bot System Health & Status`) and
  `ops.handle_health_status`'s fallback text;
- `heartbeat.send_startup_alert` headers and fallback text (`P-Bot Online …`), its context
  line (`Send \`@p-bot health\` …`), and the crash alert text (`P-Bot Critical Error / Crash Alert`)
  → e.g. `🟢 Purchasing bot online`, `🚨 *Purchasing bot — crash alert*`;
- every `@p-bot` usage example in `src/ops.py`, `src/app.py`, `src/lifecycle.py`;
- the manual-EPIF guide text in `ops.handle_template_command` (`P-Bot will validate …`);
- `interview.FAQ` answers: the answer text says `@Purchasing`; add an `"@purchasing"`
  key with the same answer and keep the `"@p-bot"` key as a silent alias so the old
  question still gets an answer.

**Unchanged on purpose:** `p_bot.log`, `p_bot.spec`, `config.LOG_FILE`, logger names
(`getLogger("p-bot…")`), the executable and autostart names, `docs/adr/`, `AGENTS.md`.
Module docstrings may be updated but need not be.

## Acceptance criteria

- [ ] **Scan what is sent.** In `tests/test_58_bot_name.py`, build with their real
  builders: the help message, the App Home view, the health blocks, the startup alert
  (clean and with a problem, via a fake client capturing `chat_postMessage` kwargs), the
  crash alert text, the unknown-word reply, and `/blank-template`'s guide text. Serialise
  each to a string and assert none contains `p-bot` or `P-Bot` (case-insensitive), and
  the health header and startup alert contain `Purchasing bot`.
- [ ] **Every `@…` example in `src/` says `@Purchasing`.** A test reads every `.py` in
  `src/` and asserts no string literal contains `@p-bot` (use `ast` to walk string
  constants so comments and logger names are not caught). Logger names
  `getLogger("p-bot…")` are allowed because they are not `@p-bot`.
- [ ] **FAQ.** `interview.match_faq("what does @purchasing do?")` and
  `match_faq("what does @p-bot do?")` both return the answer, and that answer contains
  `@Purchasing` and not `@p-bot`.
- [ ] **Rewrite in place, same names, header strings only:**
  `tests/test_24_startup_storage_check.py::test_startup_alert_all_clean`,
  `::test_startup_alert_with_placeholder`, `::test_startup_alert_missing_folder`,
  `tests/test_26_line_items_and_bom.py::test_startup_alert_names_missing_boms_dir`,
  `tests/test_monitoring_and_queue.py::test_get_system_health_and_build_blocks`,
  `::test_send_startup_alert` — each asserts the new header text. No other assertion in
  them changes.
- [ ] `p_bot.log` is still the log file name (`config.LOG_FILE` ends with `p_bot.log`).

## Gate

Run in this order, exactly as CI does. Zero failures before you push.

```
ruff check .
python scripts/check_tests_first.py
pytest -q --tb=short --durations=25
```

## Comments

