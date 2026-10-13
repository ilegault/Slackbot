"""Tests for Ticket 112: files reach the buyer's DM, and the send is logged.

WHY THESE TESTS USE A REAL WebClient:
WebClient.files_upload_v2 raises SlackRequestError when handed both ``file`` and
``content``. A MagicMock client accepts any arguments, which is how two call sites
passing both stayed green. Here only the network methods are replaced.
"""
import logging
from types import SimpleNamespace
from unittest.mock import MagicMock

from slack_sdk import WebClient
from slack_sdk.web import SlackResponse

from src import lifecycle, slack_io

BUYER = "U_BUYER"


def _resp(data):
    return SlackResponse(
        client=None, http_verb="POST", api_url="https://slack.com/api/x",
        req_args={}, data=data, headers={}, status_code=200,
    )


def _real_client(monkeypatch):
    """A real WebClient with only its network methods replaced by canned successes."""
    client = WebClient(token="xoxb-test-not-a-real-token")
    upload_names: list[str] = []

    def get_url(**kwargs):
        upload_names.append(kwargs["filename"])
        n = len(upload_names)
        return _resp({"ok": True, "file_id": f"F{n}", "upload_url": f"https://files.example/{n}"})

    def complete(**kwargs):
        return _resp({"ok": True, "files": [{"id": f["id"]} for f in kwargs["files"]]})

    monkeypatch.setattr(client, "files_getUploadURLExternal", get_url)
    monkeypatch.setattr(client, "_upload_file", lambda **kw: SimpleNamespace(status=200, body="ok"))
    monkeypatch.setattr(client, "files_completeUploadExternal", complete)
    monkeypatch.setattr(client, "chat_postMessage", lambda **kw: _resp({"ok": True, "channel": "D_BUYER", "ts": "1.1"}))
    monkeypatch.setattr(client, "conversations_open", lambda **kw: _resp({"ok": True, "channel": {"id": "D_BUYER"}}))
    monkeypatch.setattr(
        client, "chat_getPermalink",
        lambda **kw: _resp({"ok": True, "permalink": "https://example.slack.com/archives/C1/p1"}),
    )
    return client, upload_names


def _send(client, route, tmp_path=None, row=7, **extra):
    return lifecycle._send_assignee_dm(
        client, BUYER, "Dylan", "draft text", "Shaft Couplings", row,
        route=route, parsed={"vendor": "V", "total_price": 5.0},
        thread_channel="C1", thread_ts="1.0", card_ts="1.1",
        request={"item_description": "Shaft Couplings"}, state="approved", **extra,
    )


def test_assignee_dm_uploads_pass_slacks_argument_check(tmp_path, monkeypatch, caplog):
    epif = tmp_path / "0007_EPIF.pdf"
    epif.write_bytes(b"%PDF-1.4 fake")
    bom = tmp_path / "0007_V_BOM.xlsx"
    bom.write_bytes(b"PK fake")
    client, names = _real_client(monkeypatch)
    with caplog.at_level(logging.INFO):
        _send(
            client, "epif", row=7,
            epif_path=str(epif), epif_fname="0007_EPIF.pdf",
            bom_path=str(bom), bom_fname="0007_V_BOM.xlsx",
        )
    assert not [r for r in caplog.records if "Could not upload" in r.getMessage()]
    assert names == ["0007_EPIF.pdf", "0007_V_BOM.xlsx"]


def test_archived_bom_upload_passes_slacks_argument_check(tmp_path, monkeypatch, caplog):
    bom = tmp_path / "0022_Fisher-Scientific_BOM.xlsx"
    bom.write_bytes(b"PK fake")
    client, names = _real_client(monkeypatch)
    with caplog.at_level(logging.INFO):
        ok = lifecycle.upload_archived_bom(
            client=client, channel="C1", thread_ts="1.0",
            file_path=str(bom), filename="0022_Fisher-Scientific_BOM.xlsx",
        )
    assert not [r for r in caplog.records if "Could not upload archived BOM" in r.getMessage()]
    assert ok is True
    assert names == ["0022_Fisher-Scientific_BOM.xlsx"]


def test_buyer_dm_send_is_logged_with_its_path(caplog, monkeypatch):
    def run(route):
        client = MagicMock()
        client.chat_postMessage.return_value = {"channel": "D1", "ts": "2.2"}
        client.chat_getPermalink.return_value = {"permalink": "https://x"}
        caplog.clear()
        with caplog.at_level(logging.INFO):
            _send(client, route, row=7)
        return [r.getMessage() for r in caplog.records]

    epif_msgs = run("epif")
    sent = [m for m in epif_msgs if "📨 Buyer DM sent" in m]
    assert sent == [f"📨 Buyer DM sent to {BUYER} for row 7 (epif path)"]
    assert len([m for m in epif_msgs if f"📨 DM card posted to {BUYER}" in m]) == 1

    workday_msgs = run("workday")
    assert any("for row 7 (workday path)" in m for m in workday_msgs)

    # When the DM text cannot be sent, nothing claims it was.
    def boom(*a, **k):
        raise RuntimeError("dm closed")

    monkeypatch.setattr(slack_io, "tell", boom)
    failed_msgs = run("epif")
    assert not [m for m in failed_msgs if "📨 Buyer DM sent" in m]
    assert any("Could not DM assignee" in m for m in failed_msgs)
