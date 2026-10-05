# 80: The 9:00 weekday timer

**Status:** in-progress

**Runner:** any

**Auto-merge:** yes

**Blocked by:** 78

**Spec:** `.scratch/buyer-handoff-and-nudge/spec.md` ("The nudge" → Scheduling)
**Binding:** `docs/adr/0011-buyers-hand-off-requests-and-the-request-log.md` decision 4, ADR 0001

## What to build

The bot runs the nudge once per weekday at 9:00 local server time (the production server is
in Central time). If it starts after 9:00 on a weekday and today's run hasn't happened, it
runs once at start-up. A restart never runs it twice in a day.

1. `src/nudge.py`: `NUDGE_RUN_PATH = os.path.join(config.BASE_DIR, "nudge_run.json")` holding
   `{"last_run": "YYYY-MM-DD"}`. Add `nudge_run.json` to `.gitignore` beside `requests.json`.
2. `run_if_due(client, now: datetime) -> bool`: returns `False` without calling `run_nudges`
   when `now` is Saturday/Sunday, `now.time() < time(9, 0)`, or the file's `last_run` equals
   `now.date().isoformat()`. Otherwise it calls `run_nudges(client, now.date())`, writes
   `last_run` (atomic write via `tempfile` + `os.replace`, as `store.save_store` does), and
   returns `True`. A missing or unreadable file counts as "never run". It takes `now` as an
   argument — a requirement, so it can be tested without a real clock.
3. `start_nudge_scheduler(client, interval_seconds: int = 60)`: starts a daemon
   `threading.Thread` named `NudgeSchedulerThread` whose loop calls
   `run_if_due(client, datetime.now())` inside `try/except` (log at ERROR, keep looping), then
   waits `interval_seconds` on a `threading.Event`. No other logic in the loop. Pattern:
   `heartbeat.HeartbeatMonitor.start` / `_run_loop`.
4. `app.main`: call `nudge.start_nudge_scheduler(app.client)` right after
   `heartbeat.start_heartbeat()`.

## Acceptance criteria

New test file `tests/test_80_nudge_timer.py`. `monkeypatch.setattr(nudge, "NUDGE_RUN_PATH", tmp)`
and monkeypatch `nudge.run_nudges` with a recorder (this ticket tests the timer, not the nudge).

- [ ] **Before 9 and weekends don't run.** `run_if_due(client, datetime(2026,10,8,8,59))` and
  `datetime(2026,10,10,10,0)` (Saturday) → `False`, recorder not called.
- [ ] **9:00 runs once a day.** `datetime(2026,10,8,9,0)` → `True`, recorder called once with
  `date(2026,10,8)`; a second call at `datetime(2026,10,8,15,0)` → `False`, still one call; the
  temp file reads `{"last_run": "2026-10-08"}`.
- [ ] **A late start catches up.** With the file saying `2026-10-07`, `datetime(2026,10,8,14,30)` →
  `True`, called once.
- [ ] **A missing or corrupt file counts as never run.** No file → runs; file containing `not json`
  → runs and the file is rewritten as valid JSON.
- [ ] **`.gitignore` lists `nudge_run.json`**, and `app.main`'s source calls
  `nudge.start_nudge_scheduler` (assert on `inspect.getsource(app.main)`).

**Tests may fake:** the Slack client, `nudge.run_nudges`. **Must be real:** `run_if_due` and its file
on a temp path.

## Gate

Run in this order, exactly as CI does (`.github/workflows/tests.yml`). Zero failures before
you push. If `tools/type_gate.py` exists on `master` when you start, also run
`python tools/type_gate.py` after `check_tests_first.py`, and use
`pytest --tb=short -q -n auto --dist loadfile` in place of the last line.

```
ruff check .
python scripts/check_tests_first.py
pytest -q --tb=short --durations=25
```

## Comments
