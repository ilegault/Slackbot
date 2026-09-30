# 56: A missing storage location is reported, never recreated — quotes, confirmations, template

**Status:** done

**Runner:** any

**Auto-merge:** yes

**Blocked by:** 54

**Spec:** `.scratch/commands-paths-and-name/spec.md`
**Binding:** `docs/adr/0009-keywords-storage-settings-and-the-bot-name.md` decision 6, ADR 0001

## What to build

`log_writer.save_epif`, `save_confirmation`, `save_quote` and `save_bom` call
`os.makedirs(directory, exist_ok=True)`. If a OneDrive folder moves, the bot quietly
creates a new empty folder at the old path and keeps saving there. And when a save
fails, `lifecycle.handle_quote` and the confirm `write_action` in
`lifecycle.handle_confirmation` only log a warning.

1. **`src/log_writer.py`:** add `class StorageLocationError(Exception)` carrying
   `setting`, `path`, `reason`. The four `save_*` functions no longer `makedirs` the
   top-level folder: when the target folder is empty-string or does not exist they raise
   `StorageLocationError` with the matching setting name (`EPIFS_DIR`,
   `CONFIRMATIONS_DIR`, `QUOTES_DIR`, `BOMS_DIR`) and reason `not set` / `does not
   exist`. Creating `Cancelled/` inside an existing folder (`lifecycle` cancel helpers)
   is unchanged. The workbook functions raise it with `PURCHASING_LOG_PATH` when
   `config.WORKBOOK_PATH` is empty or missing (ticket 57 wires the approval path).
2. **One message.** Pure function in `src/text_rules.py`:
   `storage_problem_message(setting: str, path: str, reason: str) -> str` returning,
   verbatim:
   `⚠️ I can't reach a storage location. *<SETTING>* <reason>: \`<path or "not set">\`. An admin needs to fix the server's .env.`
3. **Callers reply in the thread.** `lifecycle.handle_quote` and the confirmation save
   catch `StorageLocationError` and `say` that message in the thread (once per
   operation, not once per file). Other exceptions keep today's behaviour.
   `ops.handle_template_command` replaces ticket 54's inline sentence with
   `storage_problem_message("EPIF_TEMPLATE_PATH", …)`.
4. `log_writer`'s module docstring records why the save functions stopped creating
   folders.

## Acceptance criteria

- [x] **Never recreated.** In `tests/test_56_storage_problems.py`: for each of the four
  `save_*` functions, point its setting at a non-existent temp folder, call it, assert
  `StorageLocationError` with the right `setting`, **and assert the folder still does not
  exist afterward**. With the folder existing, the file is written (read it back).
- [x] **The message is pure and exact**: `storage_problem_message("QUOTES_DIR", "", "not set")`
  contains `QUOTES_DIR`, `not set`, and `An admin needs to fix the server's .env.`
- [x] **Quote with a missing folder.** Call the real `lifecycle.handle_quote` with a fake
  client whose file download returns bytes, a recording `say`, and `QUOTES_DIR` pointing
  at a missing temp folder: exactly one `say` in the thread containing `QUOTES_DIR` and
  that path; no `reactions_add` call; the folder still does not exist.
- [x] **Confirmation with a missing folder.** Same shape for the confirmation path with
  `CONFIRMATIONS_DIR` missing: a thread reply naming `CONFIRMATIONS_DIR`. Use the real
  handler and run the queued write synchronously as existing confirmation tests do; the
  workbook is a temp copy, never the real one.
- [x] **`/blank-template` uses the same builder**: its reply for a missing
  `EPIF_TEMPLATE_PATH` equals `storage_problem_message("EPIF_TEMPLATE_PATH", <path>, "does not exist")`.

## Gate

Run in this order, exactly as CI does. Zero failures before you push.

```
ruff check .
python scripts/check_tests_first.py
pytest -q --tb=short --durations=25
```

## Comments

### Landed 2026-09-29
- `src/log_writer.py`: Added `StorageLocationError(setting, path, reason)` exception and updated module docstring explaining why top-level storage directories must not be recreated silently.
- `src/log_writer.py`: Removed `os.makedirs` from `save_epif`, `save_confirmation`, `save_quote`, and `save_bom`; each raises `StorageLocationError` with its setting name (`EPIFS_DIR`, `CONFIRMATIONS_DIR`, `QUOTES_DIR`, `BOMS_DIR`) and reason `not set` or `does not exist`.
- `src/log_writer.py`: Added `_check_workbook_path` to `append_row`, `blank_row`, `update_row`, and `get_row_info`, raising `StorageLocationError` for `PURCHASING_LOG_PATH` when empty or missing.
- `src/text_rules.py`: Added pure `storage_problem_message(setting, path, reason)` returning the exact user-facing warning.
- `src/lifecycle.py`: Updated `handle_quote` and `handle_confirmation` (`write_action` + `on_failure`) to catch `StorageLocationError` and reply with `storage_problem_message` once in the thread without advancing state or adding reactions.
- `src/ops.py`: Updated `handle_template_command` to use `text_rules.storage_problem_message` for missing or unset `EPIF_TEMPLATE_PATH`.
- `tests/test_56_storage_problems.py`: Added comprehensive tests verifying criteria 1–5.
- `tests/test_pipeline.py`: Explicitly created target directories in tests covering `save_*`.
- Full gate passed (ruff, check_tests_first, full pytest 478 passed).

