# ADR 0009 — Keyword spelling, storage settings, and the bot's name

**Status:** accepted
**Date:** 2026-09-28

## Context

Four problems surfaced on the production server on 2026-09-28:

1. `@Purchasing remove-vendor thorlabs` crashed the bot. `remove-vendor` was not in
   `config.REMOVE_VENDOR_KEYWORDS` (the only admin command with no hyphen form), so it
   fell to the unknown-word branch of `app.dispatch_command`. That branch called
   `slack_io.deny(respond, …)`. Bolt always puts a `respond` object in the context, but
   an `app_mention` or `message` event carries no `response_url`, so calling it raises
   `ValueError`. **Every** unrecognised word in a mention or DM crashed the bot;
   `remove-vendor` was only the first one seen.
2. `/blank-template` reported the template folder missing while the startup alert and
   the health screen reported everything fine. `/blank-template` read
   `config.TEMPLATE_DIR`, which is not in the server's `.env` and so fell back to a
   default hard-coded to the developer's dev-machine account. The startup check read a
   different constant, `EPIF_TEMPLATE_PATH`, which is set. Two constants for one file
   drifted apart. All six storage settings carry the same kind of dev-machine default.
3. The health screen lists four locations and omits `BOMS_DIR` and `EPIF_TEMPLATE_PATH`.
   Its list and the startup check's list are separate copies.
4. The bot's Slack name is **Purchasing**. "P-Bot" survives in user-facing text and docs.

## Decision

1. **A hyphen and a space are the same in a multi-word keyword.** `parse_keyword`
   normalises the two before matching, for every multi-word keyword, so `remove-vendor`,
   `remove vendor`, `blank-epif` and `blank epif` all match. The hyphen form is the one
   taught in help text and examples; the App Home says in one line that either works.
   Keyword tuples in `config.py` list one spelling per phrase, not both. Handlers take
   their argument (the vendor name, etc.) from what follows the matched keyword, not
   from a second regex over the raw text.
2. **A mention or a DM never replies through `respond`.** Replies on those paths go
   through `say` in the thread. `slack_io.deny` is for slash commands and block
   actions only. `on_mention` and `on_direct_message` do not pass `respond` on.
3. **An unknown word gets a public, in-thread reply.** If the word is close to a real
   keyword it says "did you mean `<keyword>`?", marking admin-only keywords
   *(admin only)*. If nothing is close it says so and points to `@Purchasing help`.
   Public, because the thread teaches whoever reads it later.
4. **One setting per storage location, and no defaults.** The storage settings are
   exactly `PURCHASING_LOG_PATH`, `EPIFS_DIR`, `CONFIRMATIONS_DIR`, `QUOTES_DIR`,
   `BOMS_DIR`, `EPIF_TEMPLATE_PATH`. `TEMPLATE_DIR` is deleted. None has a default in
   `config.py`: an unset setting is empty and reported as "not set".
5. **One list of storage settings.** The startup check (`path_validator`) and the
   health screen (`admin`) both read the same single list. The health screen shows,
   per setting: status, the full path, and whether it came from `.env` or is not set.
   Anyone may run it; the paths are not secret.
6. **A missing storage location is reported where it is used, never created.** Every
   operation that reads or writes a storage setting — saving an EPIF, confirmation,
   quote or BOM; writing the workbook; sending the blank template — replies in the
   thread naming the setting, the path, and that an admin needs to fix the server's
   `.env`. The save functions stop creating a missing top-level folder with
   `os.makedirs`; a folder that has moved must fail loudly, not be recreated empty at the
   old path. (Creating the `Cancelled/` subfolder inside an existing folder is unchanged.)
7. **`/blank-template` sends the file at `EPIF_TEMPLATE_PATH`** — the same file the
   EPIF filler uses — plus the instructions already in its message. No README file is
   sent or required.
8. **The bot is "the Purchasing bot" in prose and `@Purchasing` in commands**, in every
   Slack message and every doc except accepted ADRs, which are a historical record.
   Names only the developer sees are not renamed: `p_bot.log`, `p_bot.spec`, the built
   executable, the autostart task, and logger names.

## Consequences

- The developer's dev `.env` needs `BOMS_DIR` and `EPIF_TEMPLATE_PATH` added.
- Tests that relied on the dev-machine defaults must set the setting explicitly (a temp
  path), since there is no longer a default to fall back to.
- `AGENTS.md` still says "P-Bot" and `@p-bot`; it is the developer's file and the
  developer edits it.
