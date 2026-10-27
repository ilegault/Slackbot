"""Credentials stay on the server: not in the build, not in the log, not in Slack.

WHY THIS EXISTS: the PyInstaller spec used to copy the developer's `.env` (the Slack
bot and app tokens) and `roster.json` into `dist/`, so every copy of the build
folder carried live tokens. The heartbeat URL is a bearer secret too (anyone who
has it can fake "the bot is alive"), yet it was logged in full at startup and on
every failed ping, and `@Purchasing logs all` uploads that log into Slack.
These tests pin the fixes by what a reader of the artifact would see.
"""
import ast
import logging
import pathlib
import re

import pytest
import requests

from src import admin, config, heartbeat, text_rules

ROOT = pathlib.Path(__file__).resolve().parent.parent
SECRET_URL = "https://hc-ping.example/3f9c1c2e-aaaa-bbbb-cccc-0123456789ab"
SECRET_ID = "3f9c1c2e-aaaa-bbbb-cccc-0123456789ab"


def test_pyinstaller_spec_ships_no_env_or_roster():
    tree = ast.parse((ROOT / "p_bot.spec").read_text(encoding="utf-8"))
    shipped = [
        n.value for n in ast.walk(tree)
        if isinstance(n, ast.Constant) and isinstance(n.value, str)
    ]
    assert [s for s in shipped if s.endswith(".env") or s.endswith("roster.json")] == []


def test_redact_url_keeps_host_and_drops_the_secret_path():
    out = text_rules.redact_url(SECRET_URL)
    assert "hc-ping.example" in out
    assert SECRET_ID not in out
    assert text_rules.redact_url("") == ""


def test_failed_ping_does_not_log_the_url_or_the_exception_text(monkeypatch, caplog):
    def boom(url, timeout):
        raise requests.exceptions.ConnectionError(f"HTTPSConnectionPool: Max retries for url: {url}")

    monkeypatch.setattr(heartbeat.requests, "get", boom)
    caplog.set_level(logging.DEBUG)
    monitor = heartbeat.HeartbeatMonitor(url=SECRET_URL, interval=60)
    assert monitor.ping() is False
    assert SECRET_ID not in caplog.text
    assert "ConnectionError" in caplog.text


def test_heartbeat_start_does_not_log_the_url(monkeypatch, caplog):
    monkeypatch.setattr(heartbeat.requests, "get", lambda url, timeout: type("R", (), {"status_code": 200})())
    caplog.set_level(logging.DEBUG)
    monitor = heartbeat.HeartbeatMonitor(url=SECRET_URL, interval=60)
    monitor.start()
    monitor.stop()
    assert SECRET_ID not in caplog.text


def test_no_log_call_in_src_prints_the_raw_heartbeat_url():
    offenders = []
    for path in (ROOT / "src").glob("*.py"):
        for no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if re.search(r"\blog\w*\.\w+\(", line) and "config.HEALTHCHECK_URL" in line and "redact_url" not in line:
                offenders.append(f"{path.name}:{no}")
    assert offenders == []


@pytest.mark.parametrize("token", [
    "xoxb-123456789012-abcdefABCDEF",
    "xoxp-123456789012-abcdefABCDEF",
    "xoxe.xoxp-1-abcdefABCDEF",
    "xapp-1-A0123-456789-abcdef",
])
def test_log_masking_covers_every_slack_token_family(token):
    assert token not in admin.mask_sensitive_tokens(f"auth failed with {token} today")


def test_log_masking_hides_the_configured_heartbeat_url(monkeypatch):
    monkeypatch.setattr(config, "HEALTHCHECK_URL", SECRET_URL)
    masked = admin.mask_sensitive_tokens(f"GET {SECRET_URL} failed; retry {SECRET_URL}/fail")
    assert SECRET_ID not in masked
