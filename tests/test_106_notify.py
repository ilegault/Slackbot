"""Tests for Ticket 106: One notify function for approval-path error DMs.

Tests cover:
- notice_recipients: pure recipient decision (table tests per Acceptance Criterion 1).
- notify: thread link appending via chat_getPermalink, fallback on permalink failure.
- Regression for 2026-10-05 failure: handle_epif_processing parse failure with bot-posted file
  sends exactly one DM to approver and none to bot id.
- Card validation failure at approval DMs both approver and requester, and posts thread reply.
- Source scan: verify replaced slack_io.tell calls in src/lifecycle.py are removed.
"""
import ast
import io
import os
from unittest.mock import MagicMock

import pytest
from pypdf import PdfWriter

from src import lifecycle, slack_io

# ---------------------------------------------------------------------------
# Criterion 1: Table tests on notice_recipients
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "actor_id,requester_id,requester_fix,bot_id,expected",
    [
        # actor only
        ("U_ACTOR", None, False, "B_BOT", ["U_ACTOR"]),
        # actor + requester with requester_fix
        ("U_ACTOR", "U_REQ", True, "B_BOT", ["U_ACTOR", "U_REQ"]),
        # requester ignored without requester_fix
        ("U_ACTOR", "U_REQ", False, "B_BOT", ["U_ACTOR"]),
        # requester == actor -> one id
        ("U_ACTOR", "U_ACTOR", True, "B_BOT", ["U_ACTOR"]),
        # requester == bot id -> actor only
        ("U_ACTOR", "B_BOT", True, "B_BOT", ["U_ACTOR"]),
        # actor == bot id and requester None -> []
        ("B_BOT", None, False, "B_BOT", []),
        ("B_BOT", None, True, "B_BOT", []),
        # actor == bot id and requester == bot id -> []
        ("B_BOT", "B_BOT", True, "B_BOT", []),
        # actor None and requester None -> []
        (None, None, False, "B_BOT", []),
        (None, None, True, "B_BOT", []),
        # actor is bot and requester is person with requester_fix -> [requester]
        ("B_BOT", "U_REQ", True, "B_BOT", ["U_REQ"]),
    ],
)
def test_notice_recipients_table(actor_id, requester_id, requester_fix, bot_id, expected):
    """Table tests for pure notice_recipients logic."""
    result = slack_io.notice_recipients(
        actor_id,
        requester_id=requester_id,
        requester_fix=requester_fix,
        bot_id=bot_id,
    )
    assert result == expected


# ---------------------------------------------------------------------------
# Criterion 2: notify with fake client (permalink success and failure)
# ---------------------------------------------------------------------------

def test_notify_success_appends_thread_link():
    """each DM's text ends with <https://x/p|Open the thread> when chat_getPermalink returns {"permalink": "https://x/p"}."""
    client = MagicMock()
    client.auth_test.return_value = {"ok": True, "user_id": "B_BOT"}
    client.chat_getPermalink.return_value = {"permalink": "https://x/p"}

    recipients = slack_io.notify(
        client,
        actor_id="U_ACTOR",
        requester_id="U_REQ",
        requester_fix=True,
        text="Something went wrong",
        channel="C_CHAN",
        link_ts="100.0",
    )

    assert recipients == ["U_ACTOR", "U_REQ"]
    assert client.chat_postMessage.call_count == 2

    call_args_list = client.chat_postMessage.call_args_list
    assert call_args_list[0].kwargs["channel"] == "U_ACTOR"
    assert call_args_list[0].kwargs["text"] == "Something went wrong\n<https://x/p|Open the thread>"

    assert call_args_list[1].kwargs["channel"] == "U_REQ"
    assert call_args_list[1].kwargs["text"] == "Something went wrong\n<https://x/p|Open the thread>"


def test_notify_permalink_raises_sends_text_alone():
    """When chat_getPermalink raises, the DM is still sent without the link."""
    client = MagicMock()
    client.auth_test.return_value = {"ok": True, "user_id": "B_BOT"}
    client.chat_getPermalink.side_effect = RuntimeError("Slack API error")

    recipients = slack_io.notify(
        client,
        actor_id="U_ACTOR",
        requester_id=None,
        requester_fix=False,
        text="Notice text only",
        channel="C_CHAN",
        link_ts="100.0",
    )

    assert recipients == ["U_ACTOR"]
    assert client.chat_postMessage.call_count == 1
    call = client.chat_postMessage.call_args_list[0]
    assert call.kwargs["channel"] == "U_ACTOR"
    assert call.kwargs["text"] == "Notice text alone" or call.kwargs["text"] == "Notice text only"


# ---------------------------------------------------------------------------
# Criterion 3: Regression for 2026-10-05 failure
# ---------------------------------------------------------------------------

def _make_flattened_pdf_bytes() -> bytes:
    """Generate real field-less PDF bytes that cause parse_epif to raise FlattenedPdfError."""
    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


def test_regression_2026_10_05_bot_posted_flattened_epif(monkeypatch):
    """handle_epif_processing called with approver="U_APPROVER".

    Thread's only PDF is a flattened file named X_EPIF.pdf posted by the bot's own id (fake auth_test returns it).
    Exactly one DM is sent, to U_APPROVER, and none to the bot id.
    """
    flat_bytes = _make_flattened_pdf_bytes()
    file_obj = {"id": "F_FLAT", "name": "X_EPIF.pdf"}

    client = MagicMock()
    client.auth_test.return_value = {"ok": True, "user_id": "B_BOT"}
    client.chat_getPermalink.return_value = {"permalink": "https://slack.com/archives/C1/p1"}
    client.conversations_replies.return_value = {
        "messages": [
            {"user": "B_BOT", "ts": "100.0", "files": [file_obj]}
        ]
    }

    # download returns real flattened PDF bytes
    monkeypatch.setattr(slack_io, "download", lambda f: flat_bytes)
    monkeypatch.setattr(slack_io, "resolve_requester", lambda cl, uid: "Approver User" if uid == "U_APPROVER" else None)
    monkeypatch.setattr(slack_io, "find_card_in_thread", lambda *a, **kw: (None, None, [], None))
    # Fallback / mock so handle_epif_processing inspects X_EPIF.pdf posted by the bot
    monkeypatch.setattr(slack_io, "find_epif_in_thread", lambda cl, ch, ts: (file_obj, "B_BOT"))
    monkeypatch.setattr(slack_io, "thread_files", lambda cl, ch, ts: {"epifs": [], "boms": [], "quotes": [], "flattened_epifs": [{"file": file_obj, "user": "B_BOT", "ts": "100.0"}]})

    say = MagicMock()
    lifecycle.handle_epif_processing(
        client=client,
        say=say,
        channel="C_PURCHASING",
        thread_ts="100.0",
        approver="U_APPROVER",
        event_ts="100.1",
    )

    # Exactly one DM is sent, to U_APPROVER, and none to the bot id
    dms_sent = [call.kwargs for call in client.chat_postMessage.call_args_list if call.kwargs.get("thread_ts") is None]
    assert len(dms_sent) == 1
    assert dms_sent[0]["channel"] == "U_APPROVER"
    assert "Open the thread" in dms_sent[0]["text"]
    assert all(d["channel"] != "B_BOT" for d in dms_sent)

    # say() posts error in thread
    say.assert_called_once()
    assert "Error processing X_EPIF.pdf:" in say.call_args[1]["text"]


# ---------------------------------------------------------------------------
# Criterion 4: Card validation failure DMs both approver and requester
# ---------------------------------------------------------------------------

def test_card_validation_failure_dms_approver_and_requester():
    """Approving a card whose data fails validators.validate DMs both the approver and the requester,

    and still posts the 'Not logged' thread reply.
    """
    client = MagicMock()
    client.auth_test.return_value = {"ok": True, "user_id": "B_BOT"}
    client.chat_getPermalink.return_value = {"permalink": "https://slack.com/archives/C1/p2"}

    # Payload with invalid vendor (blank) and missing item_description to trigger validation failure
    invalid_parsed = {
        "item_description": "",
        "purpose": "",
        "total_price": 50.0,
        "vendor": "",
        "vendor_contact_email": "",
        "date_of_purchase": "01/01/26",
        "project_id": "123456",
        "fund": "101",
        "delivery_room": "100",
        "payment_method": "P-card",
    }

    say = MagicMock()
    lifecycle.finalize_purchase_request(
        client=client,
        say=say,
        channel="C_PURCHASING",
        thread_ts="200.0",
        event_ts="200.1",
        parsed=invalid_parsed,
        requester="Requester Person",
        notify_target="U_REQ",
        approver="U_APPROVER",
    )

    # Two DMs sent: one to approver, one to requester
    dms_sent = [call.kwargs for call in client.chat_postMessage.call_args_list if call.kwargs.get("thread_ts") is None]
    dm_channels = [d["channel"] for d in dms_sent]
    assert "U_APPROVER" in dm_channels
    assert "U_REQ" in dm_channels
    assert len(dm_channels) == 2

    for d in dms_sent:
        assert "<https://slack.com/archives/C1/p2|Open the thread>" in d["text"]
        assert "I couldn't log" in d["text"]

    # say() posts "Not logged" thread reply
    say.assert_called_once()
    assert say.call_args[1]["text"].startswith("Not logged - ")
    assert "requester DM'd" in say.call_args[1]["text"]


# ---------------------------------------------------------------------------
# Criterion 5: Source scan ensuring replaced slack_io.tell calls are removed
# ---------------------------------------------------------------------------

def test_source_scan_no_approval_error_tell_calls_in_lifecycle():
    """grep -n 'slack_io.tell(' src/lifecycle.py no longer lists the call sites named in step 2.

    Specifically, finalize_purchase_request, handle_epif_processing, and handle_epif_drop
    must contain zero slack_io.tell calls.
    """
    lifecycle_path = os.path.join(os.path.dirname(__file__), "..", "src", "lifecycle.py")
    with open(lifecycle_path, "r", encoding="utf-8") as f:
        tree = ast.parse(f.read(), filename=lifecycle_path)

    target_funcs = {
        "finalize_purchase_request",
        "handle_epif_processing",
        "handle_epif_drop",
    }

    violations = []
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name in target_funcs:
            for child in ast.walk(node):
                if isinstance(child, ast.Call):
                    # Check for slack_io.tell(...)
                    func = child.func
                    if (
                        isinstance(func, ast.Attribute)
                        and func.attr == "tell"
                        and isinstance(func.value, ast.Name)
                        and func.value.id == "slack_io"
                    ):
                        violations.append(f"{node.name} at line {child.lineno}")

    assert not violations, f"slack_io.tell found in refactored functions: {violations}"
