# Spec — Keyword spelling, the unknown-word crash, storage settings, and the bot's name

**Status:** ready-for-agent
**Binding:** `docs/adr/0009-keywords-storage-settings-and-the-bot-name.md`,
`docs/adr/0001-tests-first-and-no-muted-failures.md`
**Glossary:** `CONTEXT.md` — **Keyword** (updated), **The Purchasing bot** and
**Storage setting** (new)

## Why

Production, 2026-09-28:

- `@Purchasing remove-vendor thorlabs` crashed the bot with
  `ValueError: respond is unsupported here as there is no response_url`, raised from
  `slack_io.deny` inside the unknown-word branch at the end of `app.dispatch_command`.
  The cause is general: `on_mention` and `on_direct_message` pass Bolt's context
  `respond` into `dispatch_command`; on an event it exists but cannot be called. Any
  unrecognised word in a mention or DM crashes. `remove-vendor` hit that branch
  because `config.REMOVE_VENDOR_KEYWORDS` is `("remove vendor", "delete vendor")` —
  the only admin keyword with no hyphen form — and `ops.handle_remove_vendor`
  re-parses the text with its own regex that also lacks it.
- `/blank-template` replied "Template files missing: Could not find Directory
  `C:\Users\IGLeg\…\_TEMPLATE`". `ops.handle_template_command` reads
  `config.TEMPLATE_DIR`, whose default is hard-coded to the developer's dev machine
  and is not set in the server's `.env`. The startup alert
  (`heartbeat.send_startup_alert` → `path_validator.check_storage_paths`) checks
  `EPIF_TEMPLATE_PATH` instead, which is set, so it reported all clear. The handler
  also refuses when `README.md` is absent from that folder.
- `admin.get_system_health` / `admin.build_health_blocks` check four locations, omit
  `BOMS_DIR` and `EPIF_TEMPLATE_PATH`, show no paths, and keep their own list separate
  from `path_validator.check_storage_paths`.
- The Slack app is named **Purchasing**; "P-Bot" / `@p-bot` remain in Slack text
  (health header, startup and crash alerts, handler replies, the FAQ in
  `interview.py`, the manual-EPIF guide text in `ops.handle_template_command`) and in
  docs (`README.md`, `docs/*.md`, `CONTEXT.md`).
- `log_writer.save_epif`, `save_confirmation`, `save_quote`, `save_bom` call
  `os.makedirs(directory, exist_ok=True)`, so a storage folder that has moved is
  silently recreated empty at the old path.

## What is true afterward

### A. Keywords (ADR 0009 decisions 1–3)

1. `text_rules.parse_keyword` treats `-` and a space as the same inside multi-word
   keywords. `remove-vendor`, `remove vendor`, `add-vendor`, `add vendor`,
   `blank-epif`, `blank epif`, `promote-admin`, `promote admin`, etc. each resolve to
   one canonical keyword. `config` keyword tuples list one spelling per phrase (the
   hyphen form for admin ops); the duplicate spellings go.
2. `ops.handle_add_vendor` and `ops.handle_remove_vendor` take the vendor name from the
   text after the matched keyword, whichever spelling was typed, not from their own
   regex.
3. `on_mention` and `on_direct_message` no longer pass `respond` to
   `dispatch_command`. Every reply on the event path goes through `say` in the
   thread. `ops.handle_remove_member`'s `respond` branch is only reachable from a
   slash command or action, or is removed.
4. The unknown-word reply is public, in the thread. `text_rules` gains a pure function
   that, given the unknown word and the keyword vocabulary, returns the closest keyword
   or `None` (use `difflib.get_close_matches`; the cutoff is a named constant in
   `config.py`). The reply says "did you mean `@Purchasing <keyword>`?" — with
   *(admin only)* for admin keywords — or, with no close match, points to
   `@Purchasing help`.
5. The App Home (`blocks.build_app_home_view`) and `blocks.get_help_message` show the
   hyphen form everywhere (fix `remove vendor` in the help text) and one line:
   "Two-word commands work with a hyphen or a space: `remove-vendor` = `remove vendor`."

### B. Storage settings (ADR 0009 decisions 4–7)

6. `config.TEMPLATE_DIR` is deleted. `WORKBOOK_PATH`, `EPIFS_DIR`,
   `CONFIRMATIONS_DIR`, `QUOTES_DIR`, `BOMS_DIR`, `EPIF_TEMPLATE_PATH` read their
   `.env` value with an empty-string default — no hard-coded path.
7. One list of the six storage settings (setting name, `config` attribute, file or
   folder) lives in one place and is read by both `path_validator.check_storage_paths`
   and the health screen.
8. The health screen shows all six, each with: status icon, the full path in code
   format, and whether the value came from `.env` or is not set. Any user may run it.
9. `ops.handle_template_command` uploads the file at `config.EPIF_TEMPLATE_PATH` with
   the existing instruction text. It sends no README and does not look for one. If
   the file is missing or the setting is empty, it replies with the shared
   storage-problem message (item 10).
10. One pure function builds the storage-problem message from a setting name, its
    value and the reason ("not set", "does not exist", …): the setting, the path, and
    "an admin needs to fix the server's `.env`". Every operation that reads or writes a
    storage setting uses it when that setting is unusable, and replies in the request
    thread: EPIF save, confirmation save, quote save, BOM save, the workbook write
    (through the lock queue's failure path), and the blank template.
11. `log_writer.save_*` no longer create a missing top-level storage folder; they
    raise a named exception the caller turns into item 10's message. Creating
    `Cancelled/` inside an existing folder is unchanged.

### C. The name (ADR 0009 decision 8)

12. Every Slack-facing string says "the Purchasing bot" in prose and `@Purchasing` in
    commands: the health header, startup and crash alerts in `heartbeat.py`, handler
    replies and usage examples in `ops.py`, `app.py`, `lifecycle.py`, the FAQ entries
    in `interview.py`, and the manual-EPIF guide text.
13. `README.md` is rewritten for the current bot: `@Purchasing`, current command names
    (`assign`, not `claim`; `processed`, not `submitted`), and the admin and vendor
    commands. `docs/*.md` (not `docs/adr/`) say the Purchasing bot.
14. Unchanged on purpose: `p_bot.log`, `p_bot.spec`, the executable name, the
    autostart task, logger names, accepted ADRs, `AGENTS.md` (the developer's file).

## Testing decisions

- Fake the Slack client; drive the real `dispatch_command`, the real Bolt listener
  registry for `on_mention`, and the real `parse_keyword`.
- **The crash regression:** an `app_mention` whose context holds a `respond` that
  raises when called (as Bolt's does without a `response_url`), with an unknown word,
  produces one threaded `say` and no exception. It must fail on today's code.
- `remove-vendor X` and `remove vendor X` both remove vendor `X` from a temp roster;
  the same for `add-vendor`. Assert on the roster file, not on a reply string alone.
- The close-match function is tested directly with a typo, an exact word, and a word
  with no close match.
- Storage: tests point settings at temp paths. A missing folder produces the shared
  message naming the setting and path **and** the folder still does not exist
  afterward (assert the absence). An unset `EPIF_TEMPLATE_PATH` makes `/blank-template`
  reply with the message and upload nothing.
- The health screen test sets one of the six unset and asserts all six setting names
  and both real paths appear in the blocks, and the unset one says "not set".
- The rename test: no Slack-facing string produced by the help text, App Home, health
  blocks, startup alert and crash alert contains `P-Bot` or `@p-bot`
  (case-insensitive).
- Tests that previously leaned on the dev-machine defaults set the setting explicitly.

## Suggested seams for `/to-tickets`

Numbering continues from 51.

- A — keyword normalisation + vendor handlers + App Home/help line (items 1, 2, 5)
- A — event-path replies + unknown-word "did you mean" (items 3, 4)
- B — one settings list, no defaults, `TEMPLATE_DIR` removed, `/blank-template` fixed
  (items 6, 7, 9)
- B — health screen with paths (item 8), after the settings list
- B — shared storage-problem message and no silent `makedirs` (items 10, 11), after
  the settings list
- C — Slack text rename (item 12); last, since A and B edit the same strings
- C — README and docs (item 13)
- Human: add `BOMS_DIR` and `EPIF_TEMPLATE_PATH` to the dev `.env`; after deploy,
  confirm the server's startup alert and `@Purchasing health` show all six green;
  update `AGENTS.md`.

## Out of scope

- Renaming `p_bot.log`, `p_bot.spec`, the executable, the autostart task, loggers.
- Making `@Purchasing status` admin-only.
- The interactive prompts in `path_validator.validate_and_configure`.
- The lifecycle keywords' own aliases (`processed`/`submitted`, etc.) beyond the
  hyphen/space rule.
