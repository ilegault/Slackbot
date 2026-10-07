"""Tests for Ticket 102: A dropped EPIF gets an "EPIF read" reply, not a card.

WHY THIS EXISTS:
----------------
Per Ticket 102 and ADR 0015 (decisions 3 and 6):
Dropping an EPIF in a thread no longer posts a card with Approve / Decline buttons.
Instead, the bot validates it and replies in the thread in plain text:
  "📄 EPIF read: *{item}* — {vendor}, {price}. Waiting for approval."
If validation fails, the bot replies with the problems and DMs the uploader.
No card is posted, nothing is superseded, and no request-log entry is created until
an approver types `@Purchasing approved`.
At approval, `finalize_purchase_request` posts the card already in the `approved` state,
appends the row to the workbook, and creates the request log entry with `approved_at`.
"""
import os
from datetime import date
from unittest.mock import MagicMock, patch

import pytest

from src import config, lifecycle, roster, store
from tests.test_29_approval_archives_bom import create_test_workbook


@pytest.fixture
def temp_workbook(tmp_path, monkeypatch):
    """Create a temp copy of Purchasing-Log.xlsx and set config.WORKBOOK_PATH."""
    copy_path = str(tmp_path / "Purchasing-Log.xlsx")
    create_test_workbook(copy_path)
    monkeypatch.setattr(config, "WORKBOOK_PATH", copy_path)
    return copy_path


@pytest.fixture
def temp_epifs_dir(tmp_path, monkeypatch):
    """Create a temp EPIFs directory and set config.EPIFS_DIR."""
    epifs_path = str(tmp_path / "EPIFs")
    os.makedirs(epifs_path, exist_ok=True)
    monkeypatch.setattr(config, "EPIFS_DIR", epifs_path)
    return epifs_path


@pytest.fixture
def sync_queue(monkeypatch):
    """Execute queue write tasks synchronously."""
    from src import queue_worker

    def _sync_submit(action_fn, channel="", thread_ts="", user_id="", task_type="append",
                     description="", success_callback=None, failure_callback=None, client=None):
        try:
            res = action_fn()
            if success_callback:
                success_callback(res)
        except Exception as exc:
            if failure_callback:
                failure_callback(exc)

    monkeypatch.setattr(queue_worker, "submit_write_task", _sync_submit)
    return _sync_submit


def _valid_parsed(
    vendor="Thorlabs",
    total_price=2520.0,
    item_description="Optical Filter Mount",
    fund="133",
    project_id="PG000025831",
):
    return {
        "item_description": item_description,
        "purpose": "Laser test bench",
        "total_price": total_price,
        "vendor": vendor,
        "vendor_contact_name": "Sales Rep",
        "vendor_contact_email": "sales@thorlabs.com",
        "date_of_purchase": date(2026, 10, 7),
        "project_id": project_id,
        "fund": fund,
        "category": "Research/Lab Supplies (3105)",
        "delivery_room": "ERB 212",
        "payment_method": "Req/PO",
        "link": "https://thorlabs.com/filter-mount",
        "name_of_system": "",
        "asset_id": "",
    }


def test_valid_epif_drop_posts_reply_no_card_and_no_store_entry():
    """AC1: Dropping a valid EPIF posts exactly one chat_postMessage with the exact
    'EPIF read' text and NO blocks argument. chat_update is never called, and the
    request log (store) has no entry afterwards."""
    client = MagicMock()
    say = MagicMock()
    parsed = _valid_parsed(vendor="Thorlabs", total_price=2520.0, item_description="Optical Filter Mount")

    file_obj = {"name": "EPIF.pdf", "url_private_download": "https://fake"}

    with (
        patch.object(lifecycle.slack_io, "download", return_value=b"%PDF-fake"),
        patch.object(lifecycle.epif_parser, "parse_epif", return_value=parsed),
        patch.object(lifecycle.slack_io, "resolve_requester", return_value="Isaac"),
    ):
        lifecycle.handle_epif_drop(
            client=client,
            say=say,
            channel="C_PURCHASING",
            thread_ts="100.00",
            user_id="U_REQ",
            file_obj=file_obj,
            event_ts="100.00",
        )

    # Exactly one chat_postMessage call
    assert client.chat_postMessage.call_count == 1
    call_args = client.chat_postMessage.call_args
    call_kwargs = call_args[1] if call_args[1] else {}
    assert call_kwargs.get("channel") == "C_PURCHASING"
    assert call_kwargs.get("thread_ts") == "100.00"
    assert "blocks" not in call_kwargs or call_kwargs["blocks"] is None

    expected_text = "📄 EPIF read: *Optical Filter Mount* — Thorlabs, $2,520.00. Waiting for approval."
    assert call_kwargs.get("text") == expected_text

    # chat_update is never called
    client.chat_update.assert_not_called()

    # The store has no entry afterwards
    assert store.load_store() == {}


def test_invalid_epif_drop_posts_problem_reply_and_dms_uploader():
    """AC2: Dropping an EPIF whose parsed dict fails validation (e.g. blank vendor)
    posts the "can't be approved yet" reply with that problem's bullet, and DMs the
    uploader the same text. Assert the DM's channel is the uploader's id."""
    client = MagicMock()
    say = MagicMock()
    parsed = _valid_parsed(vendor="", total_price=2520.0)

    file_obj = {"name": "EPIF_broken.pdf", "url_private_download": "https://fake"}

    with (
        patch.object(lifecycle.slack_io, "download", return_value=b"%PDF-fake"),
        patch.object(lifecycle.epif_parser, "parse_epif", return_value=parsed),
        patch.object(lifecycle.slack_io, "resolve_requester", return_value="Isaac"),
    ):
        lifecycle.handle_epif_drop(
            client=client,
            say=say,
            channel="C_PURCHASING",
            thread_ts="100.00",
            user_id="U_REQ",
            file_obj=file_obj,
            event_ts="100.00",
        )

    # Must post to thread and DM uploader
    post_calls = client.chat_postMessage.call_args_list
    assert len(post_calls) == 2

    # Thread reply
    thread_call = next(c for c in post_calls if c.kwargs.get("thread_ts") == "100.00")
    assert thread_call.kwargs.get("channel") == "C_PURCHASING"
    assert "📄 I read *EPIF_broken.pdf* but it can't be approved yet:" in thread_call.kwargs.get("text")
    assert "  • Vendor is blank." in thread_call.kwargs.get("text")

    # DM to uploader
    dm_call = next(c for c in post_calls if c.kwargs.get("channel") == "U_REQ")
    assert dm_call.kwargs.get("channel") == "U_REQ"
    assert dm_call.kwargs.get("text") == thread_call.kwargs.get("text")

    # No chat_update
    client.chat_update.assert_not_called()
    assert store.load_store() == {}


def test_drop_leaves_older_posted_card_untouched_no_chat_update():
    """AC3: A thread with an older posted card from the same uploader and vendor:
    after a drop, chat_update is never called. The old card is left as it is."""
    client = MagicMock()
    say = MagicMock()
    parsed = _valid_parsed(vendor="Thorlabs")

    # Mock older card in thread replies
    from src import blocks
    old_payload = {
        "parsed": parsed,
        "requester": "Isaac",
        "user_id": "U_REQ",
        "is_pending_name": False,
        "thread_ts": "100.00",
        "source": "epif",
    }
    old_card_msg = {
        "ts": "100.10",
        "thread_ts": "100.00",
        "text": "🛒 Purchase Request (Posted)",
        "blocks": blocks.build_request_blocks("posted", old_payload),
        "metadata": {"event_type": "purchase_request", "event_payload": old_payload},
    }
    client.conversations_replies.return_value = {"ok": True, "messages": [old_card_msg]}

    file_obj = {"name": "EPIF.pdf", "url_private_download": "https://fake"}

    with (
        patch.object(lifecycle.slack_io, "download", return_value=b"%PDF-fake"),
        patch.object(lifecycle.epif_parser, "parse_epif", return_value=parsed),
        patch.object(lifecycle.slack_io, "resolve_requester", return_value="Isaac"),
    ):
        lifecycle.handle_epif_drop(
            client=client,
            say=say,
            channel="C_PURCHASING",
            thread_ts="100.00",
            user_id="U_REQ",
            file_obj=file_obj,
            event_ts="100.20",
        )

    # chat_update is never called!
    client.chat_update.assert_not_called()


def test_drop_then_keyword_approval_end_to_end(temp_workbook, temp_epifs_dir, sync_queue):
    """AC4: End to end: drop an EPIF, then call the @Purchasing approved path
    (handle_epif_processing as the mention handler calls it). Exactly one card is
    posted, in the approved state, a row is written on the temp workbook, and the
    request log now has one entry with approved_at set."""
    client = MagicMock()
    say = MagicMock()

    roster.add_requester("U_CHARLIE", "Charlie H.")
    roster.add_approver("U_CHARLIE")
    roster.add_requester("U_REQ", "Isaac")

    file_obj = {"name": "EPIF.pdf", "url_private_download": "https://fake"}
    parsed = _valid_parsed(vendor="Thorlabs", total_price=250.0, item_description="Optical Lens")

    thread_messages = [
        {
            "user": "U_REQ",
            "ts": "100.00",
            "thread_ts": "100.00",
            "files": [file_obj],
        }
    ]

    def mock_post_message(channel, text, thread_ts=None, **kw):
        msg = {"channel": channel, "text": text, "ts": "100.99", "thread_ts": thread_ts, **kw}
        thread_messages.append(msg)
        return {"ok": True, "ts": "100.99"}

    client.chat_postMessage.side_effect = mock_post_message
    client.conversations_replies.side_effect = lambda channel, ts, limit=100, **kw: {"ok": True, "messages": list(thread_messages)}

    # 1. Drop the EPIF
    with (
        patch.object(lifecycle.slack_io, "download", return_value=b"%PDF-fake"),
        patch.object(lifecycle.epif_parser, "parse_epif", return_value=parsed),
        patch.object(lifecycle.slack_io, "resolve_requester", return_value="Isaac"),
    ):
        lifecycle.handle_epif_drop(
            client=client,
            say=say,
            channel="C_PURCHASING",
            thread_ts="100.00",
            user_id="U_REQ",
            file_obj=file_obj,
            event_ts="100.00",
        )

    # After drop: reply was posted, but NO card was posted
    card_posts_after_drop = [m for m in thread_messages if "blocks" in m and m.get("blocks")]
    assert len(card_posts_after_drop) == 0
    assert store.load_store() == {}

    # 2. Approver calls @Purchasing approved
    with (
        patch.object(lifecycle.slack_io, "download", return_value=b"%PDF-fake"),
        patch.object(lifecycle.epif_parser, "parse_epif", return_value=parsed),
        patch.object(lifecycle.epif_parser, "read_fields", return_value={"Amount of Purchase": "250.00", "Vendor": "Thorlabs"}),
        patch.object(lifecycle.slack_io, "resolve_requester", side_effect=lambda c, uid: "Charlie H." if uid == "U_CHARLIE" else "Isaac"),
        patch.object(lifecycle.log_writer, "save_epif", return_value="/lab/EPIFs/EPIF.pdf"),
    ):
        lifecycle.handle_epif_processing(
            client=client,
            say=say,
            channel="C_PURCHASING",
            thread_ts="100.00",
            approver="U_CHARLIE",
            event_ts="100.50",
        )

    # Exactly one card has been posted, in the "approved" state
    card_posts = [m for m in thread_messages if "blocks" in m and m.get("blocks")]
    assert len(card_posts) == 1
    card_msg = card_posts[0]
    payload = card_msg.get("metadata", {}).get("event_payload", {})
    assert payload.get("state") == "approved"

    # A row was written in the temp workbook
    from src import log_writer
    entries = store.load_store()
    assert len(entries) == 1
    req_entry = next(iter(entries.values()))
    assert req_entry.get("approved_at") is not None
    assert len(req_entry.get("rows", [])) == 1
    row_num = req_entry["rows"][0]
    row_info = log_writer.get_row_info(row_num, workbook_path=temp_workbook)
    assert row_info["requester"] == "Isaac"
    assert row_info["item_description"] == "Optical Lens"
