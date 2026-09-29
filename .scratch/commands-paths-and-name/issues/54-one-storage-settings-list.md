# 54: One list of storage settings, no default paths, and /blank-template fixed

**Status:** ready-for-agent

**Runner:** any

**Auto-merge:** yes

**Blocked by:** None (can start immediately)

**Spec:** `.scratch/commands-paths-and-name/spec.md`
**Binding:** `docs/adr/0009-keywords-storage-settings-and-the-bot-name.md` decisions 4, 5, 7, ADR 0001

## What to build

On the production server `/blank-template` replied "Template files missing: Could not
find Directory `C:\Users\<dev-account>\…\_TEMPLATE`" while the startup alert said all
clear. `ops.handle_template_command` reads `config.TEMPLATE_DIR`, which is not in the
server's `.env` and fell back to a default hard-coded to the developer's dev machine.
The startup check reads a different constant, `config.EPIF_TEMPLATE_PATH`. It also
refuses when `README.md` is missing. Every storage constant in `src/config.py` carries
the same kind of dev-machine default.

1. **`src/config.py`:** delete `TEMPLATE_DIR`. `WORKBOOK_PATH`, `EPIFS_DIR`,
   `CONFIRMATIONS_DIR`, `QUOTES_DIR`, `BOMS_DIR`, `EPIF_TEMPLATE_PATH` become
   `os.environ.get("<SETTING>", "")` — no hard-coded path, no `expanduser`. (The
   `.env` name for `WORKBOOK_PATH` stays `PURCHASING_LOG_PATH`.)
2. **One list.** Add to `src/config.py`:
   `STORAGE_SETTINGS: tuple[tuple[str, str, str], ...]` — `(env setting name, config
   attribute name, "file" | "folder")`, in this order: `PURCHASING_LOG_PATH`,
   `EPIFS_DIR`, `CONFIRMATIONS_DIR`, `QUOTES_DIR`, `BOMS_DIR`, `EPIF_TEMPLATE_PATH`.
   `path_validator.check_storage_paths` iterates `config.STORAGE_SETTINGS`, reading each
   value with `getattr(config, attr)`, instead of its own inline list. It keeps its
   current reasons (`not set`, placeholder, wrong kind, `does not exist`). Ticket 55 makes
   the health screen read the same list.
3. **`ops.handle_template_command`** uploads the file at `config.EPIF_TEMPLATE_PATH`
   (filename `EPIF_TEMPLATE_HIRST.pdf` in Slack) with the instruction text it already
   posts. It uploads no README and looks for none. If the setting is empty or the file
   does not exist, it replies in the thread (or channel) naming `EPIF_TEMPLATE_PATH`, the
   value (or `not set`), and `An admin needs to fix the server's .env.` Ticket 56 later
   moves that sentence into a shared builder; here, write it inline.
4. Update `path_validator`'s and `ops.handle_template_command`'s docstrings with the
   reason (the two-constant drift found on 2026-09-28).
5. Tests that relied on the old defaults set the setting explicitly to a temp path or to
   `tests/fixtures/EPIF_TEMPLATE_HIRST.pdf`. In
   `tests/test_46_epif_path_dm_attaches_epif.py` the `temp_epifs_dir` fixture sets
   `config.EPIF_TEMPLATE_PATH` to the fixture PDF instead of setting `TEMPLATE_DIR`.

## Acceptance criteria

- [ ] **No default path.** In `tests/test_54_storage_settings.py`: with none of the six
  settings in the environment, reload `config` (`importlib.reload`, restoring it after
  via a fixture) and assert all six attributes are `""` and `TEMPLATE_DIR` does not exist
  on the module. Assert no string attribute of `config` contains `IGLeg`.
- [ ] **One list drives the startup check.** Set `config.STORAGE_SETTINGS` (monkeypatch)
  to a list with one extra entry pointing at a missing temp path; assert
  `check_storage_paths` reports that entry. This fails if the function keeps its own list.
- [ ] **Rewrite in place:** `tests/test_onboarding_and_commands.py::test_template_command`
  asserts, with `EPIF_TEMPLATE_PATH` unset, one reply containing `EPIF_TEMPLATE_PATH` and
  `not set` and **no** `files_upload_v2` call; and with it pointing at a temp PDF and **no
  README anywhere**, exactly one uploaded file named `EPIF_TEMPLATE_HIRST.pdf` whose bytes
  are the temp PDF's bytes. Same test name; it no longer touches `TEMPLATE_DIR`.
- [ ] **Startup and `/blank-template` agree.** With `EPIF_TEMPLATE_PATH` pointing at a
  missing file, both `check_storage_paths()` and `handle_template_command` name
  `EPIF_TEMPLATE_PATH`; with it pointing at a real file, the first reports nothing for it
  and the second uploads it.
- [ ] Nothing in `src/` references `TEMPLATE_DIR` (a test greps the `src/` tree).

## Gate

Run in this order, exactly as CI does. Zero failures before you push.

```
ruff check .
python scripts/check_tests_first.py
pytest -q --tb=short --durations=25
```

## Comments

