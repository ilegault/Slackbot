# 151: A second bot on the same computer refuses to start and says so

**Status:** ready-for-agent

**Runner:** any

**Auto-merge:** yes

**Blocked by:** None (can start immediately)

**Spec:** `.scratch/one-running-bot/spec.md` (Implementation Decisions: New module for the lock, The lock is held by the operating system, The held lock is kept for the life of the process, Waiting, Where the lock file lives, Where startup claims it, What a refused start does, `restart` and `update` are unchanged)
**Binding:** `docs/adr/0022-one-running-bot.md` (decisions 1–3); `docs/adr/0010-linked-cards-and-direct-message-help.md` (decision 7: failures go to the Alert channel); `docs/adr/0001-tests-first-and-no-muted-failures.md`
**Glossary:** `CONTEXT.md` — **The server**, **Alert channel**, **The lock queue**
**Read first:** `src/app.py` `main()` (the startup order) and its two import blocks near the top; `src/slack_io.py` `alert_admins`; `src/heartbeat.py` `send_startup_alert` (where `platform.node()` names the host); `src/admin.py` `execute_restart` (starts the new copy, then `os._exit(0)` — unchanged by this ticket); `tests/test_layering_and_isolation.py` `test_pure_layers_importable_without_app` (prior art for running a child `sys.executable` from a test)

## What to build

Exactly one Purchasing bot runs on a computer. At startup the bot claims a lock that the
operating system holds for as long as the process lives and releases the moment it dies
(clean exit, crash or power cut). A copy that finds the lock held waits up to 15 seconds
— long enough for `@Purchasing restart` and `update`, which start the new copy a moment
before the old one exits — then gives up: it logs the refusal, posts it to the **Alert
channel**, and exits with status 1 without starting the write queue, the heartbeat, the
nudge timer, the startup alert or the Socket Mode connection.

1. **`src/config.py`** — directly after the `HEALTHCHECK_URL` line, add
   `INSTANCE_LOCK_PATH = os.path.join(BASE_DIR, "purchasing_bot.lock")` and
   `INSTANCE_LOCK_WAIT_SECONDS = 15.0`, with a one-line comment naming ADR 0022.
2. **`src/single_instance.py`** (new) — imports only the standard library (`os`, `sys`,
   `time`, `logging`); never `config`, Slack or `app`, because it must be testable on its
   own against a real second process.
   - `class HeldLock` wrapping the open lock file, with `release() -> None` that unlocks
     and closes it (used by tests; the bot never calls it).
   - `acquire(path: str, wait_seconds: float, poll_seconds: float = 0.5) -> HeldLock | None`:
     open `path` with mode `"a+"` (creates it, never truncates), `seek(0)`, and try a
     non-blocking exclusive lock — on Windows `msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)`,
     elsewhere `fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)`; branch on
     `sys.platform == "win32"` so ruff and mypy are clean on Linux. An `OSError` means
     "held by someone else": close the file, sleep `poll_seconds`, retry until
     `wait_seconds` have passed since the first try, then return `None`. Always make at
     least one attempt, so `wait_seconds=0` means "try once". On success append the
     `HeldLock` to a module-level list so it is never garbage-collected, and return it.
   - The lock file's contents are never written or read and the file is never deleted.
     No process id anywhere. Do not make the handle inheritable (Python's default is
     non-inheritable — leave it).
3. **`src/app.py`** — add `single_instance` to both import blocks at the top (the
   `from . import (...)` list and the `except ImportError` list, the latter with
   `# type: ignore[no-redef]` as `nudge` has), and `import platform` with the standard
   imports. In `main()`, directly after the closing `log.info("=" * 70)` of the startup
   banner and **before** `path_validator.check_purchasing_channel()`: call
   `single_instance.acquire(config.INSTANCE_LOCK_PATH, config.INSTANCE_LOCK_WAIT_SECONDS)`,
   reading both `config` names at call time. If it returns `None`, build the text
   `🛑 A second Purchasing bot tried to start on <host> and stopped — one is already running.`
   with `<host>` = `platform.node() or "Unknown Host"` (as `heartbeat.send_startup_alert`
   does), `log.error(...)` that text, call `slack_io.alert_admins(app.client, text)`, and
   `sys.exit(1)`. Nothing after that point in `main()` may run. If it returns a lock,
   `main()` continues exactly as today.
4. **`.gitignore`** — add `purchasing_bot.lock` on its own line in the group with
   `roster.json`, `requests.json`, `nudge_run.json`.

## Acceptance criteria

New file `tests/test_151_one_running_bot.py`. Every lock file lives under `tmp_path`. The
second process is a real child: `subprocess.Popen([sys.executable, "-c", <inline script>, <path>, <seconds>], cwd=<repo root>, stdout=PIPE, text=True)` whose script puts the repo root on
`sys.path`, calls `single_instance.acquire(path, 0)`, prints `held` (flushed) and sleeps
the given seconds; the test reads that first line and asserts it is `held` before going
on, and kills the child in a `finally`. `single_instance.acquire` must be the real one in
both processes — never faked. In the `main()` tests only the Slack call and the start
functions are faked.

- [ ] Test `test_second_start_waits_then_is_refused`: while the child holds the lock, `single_instance.acquire(path, 1.0)` returns `None` and takes at least 0.9 s (`time.monotonic()`).
- [ ] Test `test_killed_holder_releases_the_lock`: the child holds the lock; `child.kill()` then `child.wait()` (the power-cut case, not a clean exit); `single_instance.acquire(path, 0)` then returns a `HeldLock` in under 1 s.
- [ ] Test `test_holder_exiting_during_the_wait_hands_over`: the child holds the lock and exits on its own after about 1 s; `single_instance.acquire(path, 10.0)` started while it still holds returns a `HeldLock` and takes under 10 s (the `restart` case).
- [ ] Test `test_refused_start_alerts_and_starts_nothing`: with the child holding the lock at `tmp_path/"purchasing_bot.lock"`, `monkeypatch` `config.INSTANCE_LOCK_PATH` to that path, `config.INSTANCE_LOCK_WAIT_SECONDS` to `1.0`, `app.setup_logging` to a no-op, and replace `queue_worker.start_queue_worker`, `heartbeat.start_heartbeat`, `nudge.start_nudge_scheduler`, `heartbeat.send_startup_alert`, `path_validator.check_purchasing_channel`, `app.SocketModeHandler` and `slack_io.alert_admins` with recorders. Calling `app.main()` raises `SystemExit` with code 1; `slack_io.alert_admins` was called exactly once and its text contains `A second Purchasing bot tried to start on`, `platform.node()`, and `one is already running`; `caplog` has an `ERROR` record containing `A second Purchasing bot tried to start`; and none of the other six recorders was called.
- [ ] Test `test_free_lock_starts_everything_once`: same fakes, lock path a fresh file under `tmp_path`, no child. `app.main()` returns normally; each of the six start recorders was called exactly once (the `SocketModeHandler` recorder's instance had `start()` called once); `slack_io.alert_admins` was never called with text containing `A second Purchasing bot`. Release the lock in teardown via the `HeldLock` the module holds, or leave it — the file is the test's own.
- [ ] Test `test_lock_file_is_ignored_by_git`: `subprocess.run(["git", "check-ignore", "-q", "purchasing_bot.lock"], cwd=<repo root>)` exits 0.
- [ ] Existing tests still pass, including `restart` and `update` behaviour. (no test: CI's full suite)

No existing test is deleted, skipped or marked xfail. `tools/mypy_ratchet.txt` may not go up.

## Gate

    ruff check .
    python scripts/check_tests_first.py
    python tools/type_gate.py
    pytest --tb=short -q -n auto --dist loadfile --durations=25 --max-worker-restart=0 tests/test_151_one_running_bot.py

Run pytest on the touched test files only (implement-ticket-parallel, section 4). CI runs the full suite on the PR.

## Out of scope

`scripts/setup_autostart.py` and `docs/SETUP.md` (ticket 152). Changing `admin.execute_restart`
or `ops.handle_update`. Making `nudge.run_if_due` safe on its own. A copy on another
computer. Showing host, process or start time on the health screen. Editing `docs/adr/`,
`CONTEXT.md` or `AGENTS.md`.

## Comments

