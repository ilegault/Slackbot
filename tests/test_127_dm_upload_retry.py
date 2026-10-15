"""Tests for Ticket 127: uploads to the buyer's DM retry before alerting.

Acceptance criteria:
- [ ] test_dm_upload_retries_then_succeeds: two timeouts then success -> three calls, no admin alert,
      waits [2.0, 5.0]; three timeouts -> exactly one alert naming the file.
- [ ] test_dm_upload_fallback_sends_content_only: the old `files_upload` fallback never sends file= with content=.
"""
import pytest

from src import config, lifecycle

ADMIN = "C_ADMIN_ALERTS"


class FakeClient:
    def __init__(self, failures):
        self.failures = failures
        self.upload_calls = []
        self.posts = []

    def conversations_open(self, **kw):
        return {"channel": {"id": "D_BUYER"}}

    def files_upload_v2(self, **kw):
        self.upload_calls.append(kw)
        if len(self.upload_calls) <= self.failures:
            raise TimeoutError("The read operation timed out")
        return {"ok": True}

    def chat_postMessage(self, **kw):
        self.posts.append(kw)
        return {"ok": True, "ts": "1.0"}

    def chat_getPermalink(self, **kw):
        return {"permalink": "https://example.test/p"}


@pytest.fixture
def epif_file(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "ADMIN_ALERT_CHANNEL", ADMIN)
    path = tmp_path / "0007_Ruland_EPIF.pdf"
    path.write_bytes(b"%PDF-1.4 test")
    return str(path), path.name


def _send(client, path, fname):
    lifecycle._send_assignee_dm(
        client, "U_BUYER", "Dylan", "draft", "Shaft Couplings", 7,
        epif_path=path, epif_fname=fname, route="epif",
    )


def _admin_alerts(client):
    return [p for p in client.posts if p["channel"] == ADMIN]


def test_dm_upload_retries_then_succeeds(epif_file, monkeypatch):
    path, fname = epif_file
    waits = []
    monkeypatch.setattr(lifecycle, "_sleep", waits.append)

    client = FakeClient(failures=2)
    _send(client, path, fname)
    assert len(client.upload_calls) == 3
    assert waits == [2.0, 5.0]
    assert _admin_alerts(client) == []

    waits.clear()
    client = FakeClient(failures=3)
    _send(client, path, fname)
    assert len(client.upload_calls) == 3
    alerts = _admin_alerts(client)
    assert len(alerts) == 1
    assert "Failed to attach" in alerts[0]["text"] and fname in alerts[0]["text"]


def test_dm_upload_fallback_sends_content_only(epif_file, monkeypatch):
    path, fname = epif_file
    monkeypatch.setattr(lifecycle, "_sleep", lambda s: None)
    calls = []

    class OldClient:
        """A client with only the old `files_upload` (no `files_upload_v2`)."""

        def __init__(self):
            self.posts = []

        def conversations_open(self, **kw):
            return {"channel": {"id": "D_BUYER"}}

        def files_upload(self, **kw):
            calls.append(kw)
            return {"ok": True}

        def chat_postMessage(self, **kw):
            self.posts.append(kw)
            return {"ok": True, "ts": "1.0"}

        def chat_getPermalink(self, **kw):
            return {"permalink": "https://example.test/p"}

    client = OldClient()
    _send(client, path, fname)
    assert len(calls) == 1
    assert "content" in calls[0] and "file" not in calls[0]
