"""Tests for Ticket 151 / ADR 0022: One running bot per computer.

Verifies the OS-backed single-instance lock against a real child process
(refusal, crash/kill release, handover during restart wait), startup refusal
behaviour in app.main(), happy-path startup, and .gitignore coverage.
"""
import logging
import os
import platform
import subprocess
import sys
import time

import pytest

from src import app, config, heartbeat, nudge, path_validator, queue_worker, single_instance, slack_io

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

_CHILD_SCRIPT = (
    "import sys, time\n"
    "sys.path.insert(0, sys.argv[1])\n"
    "from src import single_instance\n"
    "lock = single_instance.acquire(sys.argv[2], 0)\n"
    "assert lock is not None, 'child failed to acquire lock'\n"
    "print('held', flush=True)\n"
    "time.sleep(float(sys.argv[3]))\n"
)


def _spawn_lock_holder(lock_path: str, hold_seconds: float) -> subprocess.Popen[str]:
    """Start a real child Python process that holds the OS lock for ``hold_seconds``."""
    proc = subprocess.Popen(
        [sys.executable, "-c", _CHILD_SCRIPT, REPO_ROOT, str(lock_path), str(hold_seconds)],
        cwd=REPO_ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    assert proc.stdout is not None
    line = proc.stdout.readline().strip()
    if line != "held":
        stderr = proc.stderr.read() if proc.stderr else ""
        proc.kill()
        proc.wait()
        raise AssertionError(f"Child did not print 'held' (got {line!r}, stderr={stderr!r})")
    return proc


def test_second_start_waits_then_is_refused(tmp_path):
    """While a child process holds the lock, acquire waits and returns None."""
    lock_path = str(tmp_path / "purchasing_bot.lock")
    child = _spawn_lock_holder(lock_path, 5.0)
    try:
        start = time.monotonic()
        lock = single_instance.acquire(lock_path, 1.0)
        elapsed = time.monotonic() - start
        assert lock is None
        assert elapsed >= 0.9
    finally:
        child.kill()
        child.wait()


def test_killed_holder_releases_the_lock(tmp_path):
    """Killing the lock holder (power-cut case) releases the OS lock immediately."""
    lock_path = str(tmp_path / "purchasing_bot.lock")
    child = _spawn_lock_holder(lock_path, 30.0)
    try:
        child.kill()
        child.wait()
        start = time.monotonic()
        lock = single_instance.acquire(lock_path, 0)
        elapsed = time.monotonic() - start
        assert isinstance(lock, single_instance.HeldLock)
        assert elapsed < 1.0
        lock.release()
    finally:
        if child.poll() is None:
            child.kill()
            child.wait()


def test_holder_exiting_during_the_wait_hands_over(tmp_path):
    """When the holder exits partway through the wait, acquire succeeds (restart case)."""
    lock_path = str(tmp_path / "purchasing_bot.lock")
    child = _spawn_lock_holder(lock_path, 1.0)
    try:
        start = time.monotonic()
        lock = single_instance.acquire(lock_path, 10.0)
        elapsed = time.monotonic() - start
        assert isinstance(lock, single_instance.HeldLock)
        assert elapsed < 10.0
        lock.release()
    finally:
        if child.poll() is None:
            child.kill()
            child.wait()


def _install_startup_recorders(monkeypatch):
    """Replace startup side effects and slack_io.alert_admins with recorders."""
    calls: dict[str, list] = {
        "check_purchasing_channel": [],
        "start_queue_worker": [],
        "start_heartbeat": [],
        "start_nudge_scheduler": [],
        "send_startup_alert": [],
        "socket_start": [],
        "alert_admins": [],
    }

    monkeypatch.setattr(app, "setup_logging", lambda: None)
    monkeypatch.setattr(
        path_validator, "check_purchasing_channel",
        lambda *a, **kw: calls["check_purchasing_channel"].append((a, kw)),
    )
    monkeypatch.setattr(
        queue_worker, "start_queue_worker",
        lambda *a, **kw: calls["start_queue_worker"].append((a, kw)),
    )
    monkeypatch.setattr(
        heartbeat, "start_heartbeat",
        lambda *a, **kw: calls["start_heartbeat"].append((a, kw)),
    )
    monkeypatch.setattr(
        nudge, "start_nudge_scheduler",
        lambda *a, **kw: calls["start_nudge_scheduler"].append((a, kw)),
    )
    monkeypatch.setattr(
        heartbeat, "send_startup_alert",
        lambda *a, **kw: calls["send_startup_alert"].append((a, kw)),
    )
    monkeypatch.setattr(
        slack_io, "alert_admins",
        lambda client, text: calls["alert_admins"].append((client, text)) or True,
    )

    class _FakeSocketModeHandler:
        def __init__(self, bolt_app, app_token):
            self.bolt_app = bolt_app
            self.app_token = app_token

        def start(self):
            calls["socket_start"].append((self.bolt_app, self.app_token))

    monkeypatch.setattr(app, "SocketModeHandler", _FakeSocketModeHandler)
    return calls


def test_refused_start_alerts_and_starts_nothing(monkeypatch, tmp_path, caplog):
    """A second start while the lock is held alerts admins, logs ERROR, exits 1, and starts nothing."""
    lock_path = tmp_path / "purchasing_bot.lock"
    monkeypatch.setattr(config, "INSTANCE_LOCK_PATH", str(lock_path))
    monkeypatch.setattr(config, "INSTANCE_LOCK_WAIT_SECONDS", 1.0)
    calls = _install_startup_recorders(monkeypatch)

    child = _spawn_lock_holder(str(lock_path), 10.0)
    try:
        with caplog.at_level(logging.ERROR):
            with pytest.raises(SystemExit) as exc_info:
                app.main()
        assert exc_info.value.code == 1
    finally:
        child.kill()
        child.wait()

    assert len(calls["alert_admins"]) == 1
    alert_text = calls["alert_admins"][0][1]
    expected_host = platform.node() or "Unknown Host"
    assert "A second Purchasing bot tried to start on" in alert_text
    assert expected_host in alert_text
    assert "one is already running" in alert_text

    assert any(
        rec.levelno == logging.ERROR and "A second Purchasing bot tried to start" in rec.getMessage()
        for rec in caplog.records
    )

    for name in (
        "check_purchasing_channel",
        "start_queue_worker",
        "start_heartbeat",
        "start_nudge_scheduler",
        "send_startup_alert",
        "socket_start",
    ):
        assert calls[name] == [], f"{name} should not have been called on refused start"


def test_free_lock_starts_everything_once(monkeypatch, tmp_path):
    """When the lock is free, app.main() acquires it and starts all services once."""
    lock_path = tmp_path / "purchasing_bot.lock"
    monkeypatch.setattr(config, "INSTANCE_LOCK_PATH", str(lock_path))
    monkeypatch.setattr(config, "INSTANCE_LOCK_WAIT_SECONDS", 1.0)
    calls = _install_startup_recorders(monkeypatch)

    held_before = len(single_instance._HELD_LOCKS)
    try:
        app.main()
    finally:
        for lock in single_instance._HELD_LOCKS[held_before:]:
            lock.release()
        del single_instance._HELD_LOCKS[held_before:]

    for name in (
        "check_purchasing_channel",
        "start_queue_worker",
        "start_heartbeat",
        "start_nudge_scheduler",
        "send_startup_alert",
        "socket_start",
    ):
        assert len(calls[name]) == 1, f"{name} should have been called exactly once"

    for _client, text in calls["alert_admins"]:
        assert "A second Purchasing bot" not in text


def test_lock_file_is_ignored_by_git():
    """purchasing_bot.lock is ignored by git."""
    res = subprocess.run(
        ["git", "check-ignore", "-q", "purchasing_bot.lock"],
        cwd=REPO_ROOT,
    )
    assert res.returncode == 0
