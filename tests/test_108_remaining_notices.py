"""Tests for Ticket 108: the remaining request error DMs use slack_io.notify.

WHY THIS EXISTS:
----------------
ADR 0016 decisions 1-3: every request-related error DM goes through one function, so each
carries the `Open the thread` link. Two stragglers in src/lifecycle.py remained: the failed
quote attachment (thread line + DM to the requester) and the edit refusal on an approved card.
"""
import ast
import os
from unittest.mock import MagicMock

from src import lifecycle


def _client():
    client = MagicMock()
    client.auth_test.return_value = {"ok": True, "user_id": "B_BOT"}
    client.chat_getPermalink.return_value = {"permalink": "https://x/p"}
    return client


def _dms(client):
    return [
        c.kwargs for c in client.chat_postMessage.call_args_list
        if str(c.kwargs.get("channel", "")).startswith("U")
    ]


def test_failed_quote_attach_thread_line_and_dm_with_link():
    client = _client()
    client.files_info.side_effect = RuntimeError("boom")
    failed = lifecycle.post_attachments_to_thread(
        client, "C_CHAN", "100.0", [{"id": "F1", "name": "quote.pdf"}], "U_REQ"
    )
    assert failed == ["quote.pdf"]
    thread_posts = [
        c.kwargs for c in client.chat_postMessage.call_args_list if c.kwargs.get("channel") == "C_CHAN"
    ]
    assert len(thread_posts) == 1 and "quote.pdf" in thread_posts[0]["text"]
    assert thread_posts[0]["thread_ts"] == "100.0"
    dms = _dms(client)
    assert [d["channel"] for d in dms] == ["U_REQ"]
    assert "quote.pdf" in dms[0]["text"]
    assert dms[0]["text"].endswith("<https://x/p|Open the thread>")
    client.chat_getPermalink.assert_called_with(channel="C_CHAN", message_ts="100.0")


def test_edit_refusal_on_approved_card_dms_clicker_with_link(monkeypatch):
    client = _client()
    monkeypatch.setattr(
        lifecycle.slack_io, "get_card_payload", lambda *a, **k: {"state": "approved"}
    )
    ok = lifecycle.handle_items_update(client, "C_CHAN", "100.0", "101.0", [], 0.0, "U_CLICK")
    assert ok is False
    dms = _dms(client)
    assert [d["channel"] for d in dms] == ["U_CLICK"]
    assert dms[0]["text"].startswith(
        "⚠️ This purchase request has already been approved and line items can no longer be edited."
    )
    assert dms[0]["text"].endswith("<https://x/p|Open the thread>")
    client.chat_getPermalink.assert_called_with(channel="C_CHAN", message_ts="101.0")
    client.chat_update.assert_not_called()


def test_lifecycle_keeps_exactly_two_slack_io_tell_calls():
    path = os.path.join(os.path.dirname(__file__), "..", "src", "lifecycle.py")
    with open(path, "r", encoding="utf-8") as f:
        tree = ast.parse(f.read(), filename=path)
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            for child in ast.walk(node):
                fn = getattr(child, "func", None)
                if (
                    isinstance(child, ast.Call)
                    and isinstance(fn, ast.Attribute)
                    and fn.attr == "tell"
                    and isinstance(fn.value, ast.Name)
                    and fn.value.id == "slack_io"
                ):
                    found.append(child.lineno)
    assert len(set(found)) == 2, found
    src = open(path, encoding="utf-8").read().splitlines()
    texts = " ".join(src[n - 1] for n in set(found))
    assert "assignee_id, dm_text" in texts
    assert "awaiting approval" in texts
