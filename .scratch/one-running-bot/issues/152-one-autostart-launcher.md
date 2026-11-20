# 152: The autostart script installs one launcher and removes the old ones

**Status:** ready-for-agent

**Runner:** any

**Auto-merge:** yes

**Blocked by:** None (can start immediately)

**Spec:** `.scratch/one-running-bot/spec.md` (Implementation Decisions: The autostart script, Docs)
**Binding:** `docs/adr/0022-one-running-bot.md` (decision 4: one launcher); `docs/adr/0009-keywords-storage-settings-and-the-bot-name.md` (the bot's name; "P-Bot" stays out of `docs/`); `docs/adr/0001-tests-first-and-no-muted-failures.md`
**Glossary:** `CONTEXT.md` — **The server**, **Alert channel**
**Read first:** `scripts/setup_autostart.py` — `TASK_NAME`, `create_scheduled_task` (the PowerShell that unregisters then registers the task), `create_startup_shortcut` (removed by this ticket), `main`; `docs/SETUP.md` "Setup Auto-Start" (around line 75) and "Task Scheduler task not running" (around line 171); `tests/test_59_readme_and_docs.py` (forbids "P-Bot" anywhere under `docs/` outside `docs/adr/`)

## What to build

Running `python scripts/setup_autostart.py` on **the server** leaves exactly one way for
the bot to start at boot: a Task Scheduler task named `Purchasing-Bot`. Today the script
also creates a "backup" `P-Bot.lnk` in the Windows Startup folder, so every reboot starts
two bots. Rerunning the script repairs a server set up the old way: it removes the old
shortcuts and replaces the old `P-Bot` task.

1. **`scripts/setup_autostart.py`**
   - `TASK_NAME = "Purchasing-Bot"` (was `"P-Bot"`).
   - In `create_scheduled_task`'s PowerShell, the "Remove existing task" block unregisters
     `$taskName`, `"P-Bot"` and `"EPIF-Bot"`, each with `-Confirm:$false -ErrorAction SilentlyContinue`
     as the current lines do. `scripts/` is not under `docs/`, so the old name may appear here.
   - Delete `create_startup_shortcut` entirely.
   - Add `startup_dir() -> str`, returning
     `os.path.expandvars(r"%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup")` (the
     path `create_startup_shortcut` used).
   - Add `remove_startup_shortcuts(folder: str) -> list[str]`: for each of `P-Bot.lnk` and
     `EPIF-Bot.lnk` in `folder`, if it exists, delete it, `log.info` the removal, and add
     its path to the returned list. Touch nothing else in the folder. A missing folder
     returns `[]`.
   - `main()`: replace the "Also create startup shortcut" step with
     `remove_startup_shortcuts(startup_dir())`; the success message depends on the task
     alone; delete the "Bot will also start via Startup folder" line; the closing hints
     keep using `TASK_NAME`.
2. **`docs/SETUP.md`**
   - "Setup Auto-Start" / "What Gets Created": the script creates `run_bot.bat` and one
     Task Scheduler task, `Purchasing-Bot`, and removes any Startup-folder shortcut an
     older version left. Delete the "backup startup folder shortcut" step and the
     "Startup Shortcut — Fallback launcher" bullet. Add one sentence: only one Purchasing
     bot can run on a computer; a second copy refuses to start.
   - Troubleshooting: add an entry titled with the alert's words, `"A second Purchasing bot tried to start … and stopped"`,
     saying it means a second copy tried to start on that computer while one was running;
     check `Get-ScheduledTask | Where-Object TaskName -match 'Bot'` and the Startup folder
     for a second launcher, rerun `python scripts/setup_autostart.py`, and remember that
     starting `run_bot.bat` by hand while the bot runs causes the same alert.
   - Never write the old task or bot name anywhere in `docs/`.

## Acceptance criteria

New file `tests/test_152_one_launcher.py`. Import the script as `from scripts import setup_autostart`
after putting the repo root on `sys.path` as `tests/test_145_log_link_app_home.py` does.
May be faked: `setup_autostart.subprocess.run` (a recorder returning an object with
`returncode=0`, `stdout=""`, `stderr=""`, keeping each call's argument list — there is no
PowerShell on CI), `setup_autostart.startup_dir` (returning a folder under `tmp_path`;
`%APPDATA%` does not expand on Linux) and `setup_autostart.BOT_DIR` (a folder under
`tmp_path`, so `run_bot.bat` is never written into the repo). Must be real:
`remove_startup_shortcuts`, `main`, and the files on disk.

- [ ] Test `test_autostart_installs_no_startup_shortcut`: on an empty startup folder, `setup_autostart.main()` leaves the folder without `P-Bot.lnk`, and no recorded PowerShell script contains `CreateShortcut`.
- [ ] Test `test_autostart_removes_old_shortcuts`: with empty files `P-Bot.lnk`, `EPIF-Bot.lnk` and `Other.lnk` placed in the startup folder beforehand, after `setup_autostart.main()` the first two are gone and `Other.lnk` is still there.
- [ ] Test `test_autostart_registers_purchasing_bot_and_drops_p_bot`: the recorded PowerShell script passed to `subprocess.run` (the `-Command` argument) contains `$taskName = "Purchasing-Bot"`, `Register-ScheduledTask`, and `Unregister-ScheduledTask -TaskName "P-Bot"`.
- [ ] Test `test_setup_md_describes_one_launcher_and_the_refusal`: `docs/SETUP.md` contains `Purchasing-Bot` and `A second Purchasing bot tried to start`, and (case-insensitive) contains neither `startup shortcut` nor `backup startup folder`.
- [ ] Existing tests still pass, including the no-old-name check over `docs/`. (no test: CI's full suite)

No existing test is deleted, skipped or marked xfail. `tools/mypy_ratchet.txt` may not go up.

## Gate

    ruff check .
    python scripts/check_tests_first.py
    python tools/type_gate.py
    pytest --tb=short -q -n auto --dist loadfile --durations=25 --max-worker-restart=0 tests/test_152_one_launcher.py tests/test_59_readme_and_docs.py

Run pytest on the touched test files only (implement-ticket-parallel, section 4). CI runs the full suite on the PR.

## Out of scope

The lock and `main()` (ticket 151). Running the bot as a Windows service. Changing
`run_bot.bat`'s contents (it keeps its `pause`). Rewording the rest of `docs/SETUP.md`.
Editing `docs/adr/`, `CONTEXT.md` or `AGENTS.md`.

## Comments

