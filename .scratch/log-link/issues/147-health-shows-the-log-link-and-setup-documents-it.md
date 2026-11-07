# 147: The health screen shows whether the Log link is set, and SETUP.md documents it

**Status:** ready-for-agent

**Runner:** any

**Auto-merge:** yes

**Blocked by:** 145

**Spec:** `.scratch/log-link/spec.md` (Implementation Decisions: Health screen, Docs)
**Binding:** `docs/adr/0021-app-home-and-help-link-the-purchasing-log.md` (decisions 2–4); `docs/adr/0009-keywords-storage-settings-and-the-bot-name.md` (the six storage settings stay six; health screen); `docs/adr/0001-tests-first-and-no-muted-failures.md`
**Glossary:** `CONTEXT.md` — **Log link**, **storage setting**

## What to build

`@Purchasing health` shows one line, `Log link: set` or `Log link: not set`, outside the
storage section, so an admin can see after a restart whether `PURCHASING_LOG_URL` took.
The URL itself is never shown. `docs/SETUP.md` tells whoever sets up the server that the
setting exists, what it is for, and that it is not a storage path.

1. **`src/admin.py` imports** — add `text_rules` to both import branches
   (`from . import config, queue_worker, roster, text_rules` and the bare `import text_rules`
   fallback).
2. **`src/admin.py` `get_system_health`** — add the key
   `"log_link_set": text_rules.log_link_url(getattr(config, "PURCHASING_LOG_URL", "")) is not None`
   to the returned dict, read at call time. Use the same rule as App Home and help
   (`text_rules.log_link_url`, ticket 145); do not write a second check.
3. **`src/admin.py` `build_health_blocks`** — directly after `*storage_blocks` and before
   the "Excel Write Queue" section, insert one block
   `{"type": "section", "text": {"type": "mrkdwn", "text": "Log link: set"}}`, or
   `"Log link: not set"` when `h.get("log_link_set")` is falsy. Use `h.get(...)`, not
   `h[...]`, so hand-built health dicts in existing tests still render (they show
   `not set`). The storage section is unchanged and still lists exactly the entries of
   `config.STORAGE_SETTINGS`.
4. **`docs/SETUP.md`** — in "### 2. Set Environment Variables", after the storage-path
   code block, add a sentence and a code block:
   `Optionally, give the browser link to the Purchasing Log so App Home and /purchasing-help can show it:`
   then a fenced block holding `PURCHASING_LOG_URL=https://<the workbook's sharing link>`.
   Under the "## Storage Path Configuration" table (leave that table and its
   "five OneDrive-synced locations" sentence untouched), add a subsection
   `### Purchasing Log link (optional)` with a one-row table
   `| Setting | Purpose | Example |` →
   `| **PURCHASING_LOG_URL** | Browser link that opens the Purchasing Log from App Home and /purchasing-help. Not a storage path: the bot never reads or writes through it. Missing or not a web address shows "isn't set up yet" and \`@Purchasing health\` says \`Log link: not set\`. | \`https://<the workbook's sharing link>\` |`.
   Do not name SharePoint or OneDrive in the new text.

## Acceptance criteria

New file `tests/test_147_log_link_health_and_setup.py`. Point the storage settings at
`tmp_path` files and folders exactly as `tests/test_55_health_paths.py::test_all_six_from_one_list`
does; set the link only with `monkeypatch.setattr(config, "PURCHASING_LOG_URL", ...)`.
`admin.get_system_health`, `admin.build_health_blocks` and `text_rules.log_link_url` must
be the real ones; read the real `docs/SETUP.md` from the repo.

- [ ] `test_health_says_log_link_set` — with `https://example.org/log?e=1`, the text of the blocks from `admin.build_health_blocks(admin.get_system_health())` contains `"Log link: set"`, does not contain `"Log link: not set"`, and does not contain `example.org` anywhere.
- [ ] `test_health_says_log_link_not_set` — parametrized over `""`, `"www.example.com/log"`, `"https://exa mple.com"`: the block text contains `"Log link: not set"`.
- [ ] `test_log_link_line_sits_outside_storage` — with a good URL, the block whose text is `"Log link: set"` is not one of the blocks containing `"Storage & OneDrive Directory Health"` or any storage setting name, and the storage text still names every setting in `config.STORAGE_SETTINGS` and not `PURCHASING_LOG_URL`.
- [ ] `test_hand_built_health_dict_still_renders` — `admin.build_health_blocks(h)` for a dict with the keys `host, os, uptime, disk, memory, bot_version`, `storage=[]`, `queue={"pending_count": 0}` and no `log_link_set` returns blocks containing `"Log link: not set"` and raises nothing.
- [ ] `test_setup_documents_purchasing_log_url` — `docs/SETUP.md` contains `PURCHASING_LOG_URL=https://`, contains `### Purchasing Log link (optional)`, contains a table row starting `| **PURCHASING_LOG_URL** |` that includes `Not a storage path`, and the five original storage rows (`PURCHASING_LOG_PATH`, `EPIFS_DIR`, `CONFIRMATIONS_DIR`, `QUOTES_DIR`, `BOMS_DIR`) are still present.

No existing test is deleted, skipped or marked xfail. If an existing health test breaks,
fix the code, not the test.

## Gate

    ruff check .
    python scripts/check_tests_first.py
    python tools/type_gate.py
    pytest --tb=short -q -n auto --dist loadfile --durations=25

## Out of scope

App Home (145) and help (146). Adding the Log link to the startup path check, the admin
startup alert or `config.STORAGE_SETTINGS`. Showing the URL anywhere on the health
screen. Rewording other parts of `docs/SETUP.md`. Editing `docs/adr/`, `CONTEXT.md` or
`AGENTS.md`.

## Comments

