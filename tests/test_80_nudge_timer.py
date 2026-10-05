"""Tests for Ticket 80: The 9:00 weekday timer.

Covers:
- run_if_due returns False and does not call run_nudges before 9:00 or on weekends (Saturday, Sunday).
- run_if_due runs at 9:00 on weekdays, calls run_nudges(client, date), writes {"last_run": "YYYY-MM-DD"},
  and does not run again the same day.
- A late start (e.g. 14:30) catches up if today's run has not occurred yet.
- Missing or corrupt nudge_run.json counts as never run, runs, and rewrites valid JSON.
- .gitignore lists nudge_run.json and app.main source calls nudge.start_nudge_scheduler after heartbeat.start_heartbeat.
"""
import inspect
import json
import threading
from datetime import date, datetime
from pathlib import Path
from unittest.mock import MagicMock

from src import nudge
from src.nudge import run_if_due, start_nudge_scheduler


def test_before_9_and_weekends_dont_run(tmp_path, monkeypatch):
    """AC 1: Before 9:00 and weekends don't run.
    run_if_due(client, datetime(2026,10,8,8,59)) and datetime(2026,10,10,10,0) (Saturday)
    -> False, recorder not called.
    """
    run_file = tmp_path / "nudge_run.json"
    monkeypatch.setattr(nudge, "NUDGE_RUN_PATH", str(run_file))

    recorder = []
    monkeypatch.setattr(nudge, "run_nudges", lambda client, d: recorder.append(d))
    client = MagicMock()

    # Weekday before 9:00 (Thursday 2026-10-08 08:59:59)
    res_before_9 = run_if_due(client, datetime(2026, 10, 8, 8, 59))
    assert res_before_9 is False
    assert recorder == []
    assert not run_file.exists()

    # Saturday (2026-10-10 10:00:00)
    res_saturday = run_if_due(client, datetime(2026, 10, 10, 10, 0))
    assert res_saturday is False
    assert recorder == []
    assert not run_file.exists()

    # Sunday (2026-10-11 11:00:00)
    res_sunday = run_if_due(client, datetime(2026, 10, 11, 11, 0))
    assert res_sunday is False
    assert recorder == []
    assert not run_file.exists()


def test_9am_runs_once_a_day(tmp_path, monkeypatch):
    """AC 2: 9:00 runs once a day.
    datetime(2026,10,8,9,0) -> True, recorder called once with date(2026,10,8);
    a second call at datetime(2026,10,8,15,0) -> False, still one call;
    the temp file reads {"last_run": "2026-10-08"}.
    """
    run_file = tmp_path / "nudge_run.json"
    monkeypatch.setattr(nudge, "NUDGE_RUN_PATH", str(run_file))

    recorder = []
    monkeypatch.setattr(nudge, "run_nudges", lambda client, d: recorder.append(d))
    client = MagicMock()

    # First call at 09:00
    res_first = run_if_due(client, datetime(2026, 10, 8, 9, 0))
    assert res_first is True
    assert recorder == [date(2026, 10, 8)]

    assert run_file.exists()
    content = json.loads(run_file.read_text(encoding="utf-8"))
    assert content == {"last_run": "2026-10-08"}

    # Second call at 15:00 the same day
    res_second = run_if_due(client, datetime(2026, 10, 8, 15, 0))
    assert res_second is False
    assert recorder == [date(2026, 10, 8)]

    content_after = json.loads(run_file.read_text(encoding="utf-8"))
    assert content_after == {"last_run": "2026-10-08"}


def test_late_start_catches_up(tmp_path, monkeypatch):
    """AC 3: A late start catches up.
    With the file saying 2026-10-07, datetime(2026,10,8,14,30) -> True, called once.
    """
    run_file = tmp_path / "nudge_run.json"
    run_file.write_text(json.dumps({"last_run": "2026-10-07"}), encoding="utf-8")
    monkeypatch.setattr(nudge, "NUDGE_RUN_PATH", str(run_file))

    recorder = []
    monkeypatch.setattr(nudge, "run_nudges", lambda client, d: recorder.append(d))
    client = MagicMock()

    res = run_if_due(client, datetime(2026, 10, 8, 14, 30))
    assert res is True
    assert recorder == [date(2026, 10, 8)]

    content = json.loads(run_file.read_text(encoding="utf-8"))
    assert content == {"last_run": "2026-10-08"}


def test_missing_or_corrupt_file_counts_as_never_run(tmp_path, monkeypatch):
    """AC 4: A missing or corrupt file counts as never run.
    No file -> runs; file containing 'not json' -> runs and the file is rewritten as valid JSON.
    """
    run_file = tmp_path / "nudge_run.json"
    monkeypatch.setattr(nudge, "NUDGE_RUN_PATH", str(run_file))

    recorder = []
    monkeypatch.setattr(nudge, "run_nudges", lambda client, d: recorder.append(d))
    client = MagicMock()

    # Case A: Missing file
    assert not run_file.exists()
    res_missing = run_if_due(client, datetime(2026, 10, 8, 9, 30))
    assert res_missing is True
    assert recorder == [date(2026, 10, 8)]
    assert json.loads(run_file.read_text(encoding="utf-8")) == {"last_run": "2026-10-08"}

    # Case B: Corrupt file (e.g. 'not json')
    run_file.write_text("not json", encoding="utf-8")
    recorder.clear()

    res_corrupt = run_if_due(client, datetime(2026, 10, 9, 10, 0))
    assert res_corrupt is True
    assert recorder == [date(2026, 10, 9)]
    assert json.loads(run_file.read_text(encoding="utf-8")) == {"last_run": "2026-10-09"}


def test_gitignore_and_app_main_scheduler():
    """AC 5: .gitignore lists nudge_run.json, and app.main's source calls
    nudge.start_nudge_scheduler right after heartbeat.start_heartbeat.
    """
    repo_root = Path(__file__).resolve().parent.parent
    gitignore_path = repo_root / ".gitignore"
    assert gitignore_path.exists(), "Expected .gitignore to exist at repository root"
    gitignore_text = gitignore_path.read_text(encoding="utf-8")

    lines = [line.strip() for line in gitignore_text.splitlines()]
    assert "nudge_run.json" in lines, "Expected nudge_run.json in .gitignore"

    from src import app
    source = inspect.getsource(app.main)
    assert "nudge.start_nudge_scheduler" in source, "Expected app.main to call nudge.start_nudge_scheduler"
    assert "heartbeat.start_heartbeat" in source, "Expected app.main to call heartbeat.start_heartbeat"

    heartbeat_pos = source.find("heartbeat.start_heartbeat")
    scheduler_pos = source.find("nudge.start_nudge_scheduler")
    assert heartbeat_pos < scheduler_pos, "nudge.start_nudge_scheduler must be called after heartbeat.start_heartbeat"


def test_start_nudge_scheduler_loop(monkeypatch):
    """Test start_nudge_scheduler starts a daemon thread named NudgeSchedulerThread
    whose loop calls run_if_due inside try/except and waits on an event.
    """
    client = MagicMock()
    called = threading.Event()
    stop_event = threading.Event()

    def fake_run_if_due(c, now):
        called.set()
        return True

    monkeypatch.setattr(nudge, "run_if_due", fake_run_if_due)

    thread = start_nudge_scheduler(client, interval_seconds=1, stop_event=stop_event)
    assert thread.name == "NudgeSchedulerThread"
    assert thread.daemon is True
    assert thread.is_alive()

    # Wait for fake_run_if_due to be invoked
    assert called.wait(timeout=2.0)

    # Stop scheduler thread cleanly
    stop_event.set()
    thread.join(timeout=2.0)
    assert not thread.is_alive()
