"""Tests for Ticket 64: Approval always leaves a card in the thread."""
import json
import logging
import os
from datetime import date
from unittest.mock import MagicMock

import pytest

from src import blocks, config, lifecycle, log_writer, queue_worker, roster, slack_io, validators

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIXTURES = os.path.join(PROJECT_ROOT, "tests", "fixtures")


def _valid_request(total_price=50.0, category="Supplies"):
    return {
        "item_description": "Shaft Couplings",
        "purpose": "Motor test stand alignment",
        "total_price": total_price,
        "vendor": "Test Vendor",
        "vendor_contact_name": "Sales",
        "vendor_contact_email": "sales@ruland.com",
        "date_of_purchase": date(2026, 9, 22),
        "project_id": "PG000025831",
        "fund": "133",
        "category": category,
        "delivery_room": "ERB 212",
        "payment_method": "Workday",
        "link": "https://ruland.com",
        "name_of_system": "",
        "asset_id": "",
    }


@pytest.fixture(autouse=True)
def clean_roster(tmp_path, monkeypatch):
    roster_file = str(tmp_path / "roster.json")
    monkeypatch.setattr(roster, "ROSTER_PATH", roster_file)
    roster._DATA = None
    data = {
        "admins": ["U_ADMIN"],
        "approvers": ["U_CHARLIE"],
        "buyers": ["U_BUYER"],
        "requesters": {
            "U_ADMIN": "Isaac",
            "U_CHARLIE": "Charlie H.",
            "U_BUYER": "Dylan",
            "U_REQ": "Alex",
        },
        "vendors": [],
    }
    with open(roster_file, "w", encoding="utf-8") as f:
        json.dump(data, f)

    monkeypatch.setattr(validators, "validate", lambda *args, **kwargs: [])

    def fake_save_epif(content, archive_name):
        path = os.path.join(config.EPIFS_DIR, archive_name)
        with open(path, "wb") as f:
            f.write(content or b"")
        return path

    monkeypatch.setattr(log_writer, "save_epif", fake_save_epif)

    def fake_save_bom(xlsx_bytes, fname):
        path = os.path.join(config.BOMS_DIR, fname)
        with open(path, "wb") as f:
            f.write(xlsx_bytes or b"")
        return path

    from src import log_writer as lw_mod
    monkeypatch.setattr(lw_mod, "save_bom", fake_save_bom)

    monkeypatch.setattr(log_writer, "append_row", MagicMock(return_value=17))
    monkeypatch.setattr(log_writer, "build_row", lambda parsed, req: {})
    monkeypatch.setattr(log_writer, "update_row", lambda row, fields: None)
    monkeypatch.setattr(log_writer, "get_row_info", lambda row: {})


@pytest.fixture
def temp_epifs_dir(tmp_path, monkeypatch):
    d = str(tmp_path / "EPIFs")
    os.makedirs(d)
    monkeypatch.setattr(config, "EPIFS_DIR", d)
    monkeypatch.setattr(config, "EPIF_TEMPLATE_PATH", os.path.join(FIXTURES, "EPIF_TEMPLATE_HIRST.pdf"))
    return d


@pytest.fixture
def temp_boms_dir(tmp_path, monkeypatch):
    d = str(tmp_path / "BOMs")
    os.makedirs(d)
    monkeypatch.setattr(config, "BOMS_DIR", d)
    return d


@pytest.fixture
def sync_queue(monkeypatch):
    def fake_submit(action_fn, *args, **kwargs):
        result = action_fn()
        if "success_callback" in kwargs and kwargs["success_callback"]:
            kwargs["success_callback"](result)
        return result

    monkeypatch.setattr(queue_worker, "submit_write_task", fake_submit)


def _make_client_with_human_thread():
    client = MagicMock()
    client.conversations_open.return_value = {"channel": {"id": "D_BUYER"}}
    client.conversations_replies.return_value = {
        "messages": [
            {"text": "Can someone approve this purchase?", "ts": "111.000", "user": "U_REQ"}
        ]
    }
    return client


def test_no_card_in_thread_posts_approved_card(temp_epifs_dir, temp_boms_dir, sync_queue):
    """AC 1: No card in thread -> exactly one chat_postMessage card carrying approved state and buttons."""
    client = _make_client_with_human_thread()
    say = MagicMock()
    parsed = _valid_request()
    pdf_bytes = b"fake_pdf_data"

    lifecycle.finalize_purchase_request(
        client=client,
        say=say,
        channel="C_PURCHASING",
        thread_ts="111.222",
        event_ts="111.333",
        parsed=parsed,
        requester="Alex",
        notify_target="U_REQ",
        assignee_id="U_BUYER",
        assignee_name="Dylan",
        approver="U_CHARLIE",
        pdf_bytes=pdf_bytes,
        file_name="order.pdf",
    )

    card_posts = [
        c[1] for c in client.chat_postMessage.call_args_list
        if c[1].get("metadata", {}).get("event_type") == "purchase_request"
    ]
    assert len(card_posts) == 1, f"Expected exactly one card postMessage, got {len(card_posts)}"
    post = card_posts[0]
    assert post.get("thread_ts") == "111.222"
    assert post.get("channel") == "C_PURCHASING"
    assert post.get("metadata", {}).get("event_payload", {}).get("state") == "approved"

    # Verify buttons in blocks
    actions = [b for b in post.get("blocks", []) if b.get("type") == "actions"]
    assert len(actions) == 1
    buttons = actions[0].get("elements", [])
    primary_btns = [
        b for b in buttons
        if b.get("action_id") == "req_processed" and b.get("text", {}).get("text") == "Mark Processed"
    ]
    assert len(primary_btns) == 1
    cancel_btns = [
        b for b in buttons
        if b.get("action_id") == "req_cancel" and b.get("text", {}).get("text") == "Cancel"
    ]
    assert len(cancel_btns) == 1

    log_writer.append_row.assert_called_once()


def test_history_and_buyer_are_on_the_card(temp_epifs_dir, temp_boms_dir, sync_queue):
    """AC 2: With an assignee, section text contains Buyer: <name>, context contains Approved by and Assigned to, payload holds assignee_id."""
    client = _make_client_with_human_thread()
    say = MagicMock()
    parsed = _valid_request()

    lifecycle.finalize_purchase_request(
        client=client,
        say=say,
        channel="C_PURCHASING",
        thread_ts="111.222",
        event_ts="111.333",
        parsed=parsed,
        requester="Alex",
        notify_target="U_REQ",
        assignee_id="U_BUYER",
        assignee_name="Dylan",
        approver="U_CHARLIE",
        pdf_bytes=b"fake_pdf_data",
        file_name="order.pdf",
    )

    card_posts = [
        c[1] for c in client.chat_postMessage.call_args_list
        if c[1].get("metadata", {}).get("event_type") == "purchase_request"
    ]
    assert len(card_posts) == 1
    post = card_posts[0]

    # Section text contains Buyer: Dylan
    sections = [b for b in post.get("blocks", []) if b.get("type") == "section"]
    assert any("Buyer:" in s.get("text", {}).get("text", "") and "Dylan" in s.get("text", {}).get("text", "") for s in sections)

    # Context block contains Approved by and Assigned to
    contexts = [b for b in post.get("blocks", []) if b.get("type") == "context"]
    assert any(
        "Approved by" in elem.get("text", "") and "Assigned to" in elem.get("text", "")
        for c in contexts for elem in c.get("elements", [])
    )

    assert post.get("metadata", {}).get("event_payload", {}).get("assignee_id") == "U_BUYER"


def test_posted_card_is_readable_by_next_handler(temp_epifs_dir, temp_boms_dir, sync_queue):
    """AC 3: Feed chat_postMessage kwargs back into fake conversations_replies; find_card_in_thread returns approved state with same assignee_id."""
    client = _make_client_with_human_thread()
    say = MagicMock()
    parsed = _valid_request()

    lifecycle.finalize_purchase_request(
        client=client,
        say=say,
        channel="C_PURCHASING",
        thread_ts="111.222",
        event_ts="111.333",
        parsed=parsed,
        requester="Alex",
        notify_target="U_REQ",
        assignee_id="U_BUYER",
        assignee_name="Dylan",
        approver="U_CHARLIE",
        pdf_bytes=b"fake_pdf_data",
        file_name="order.pdf",
    )

    card_posts = [
        c[1] for c in client.chat_postMessage.call_args_list
        if c[1].get("metadata", {}).get("event_type") == "purchase_request"
    ]
    assert len(card_posts) == 1
    post_kwargs = card_posts[0]

    # Feed kwargs back as the only message
    fake_msg = dict(post_kwargs)
    fake_msg["ts"] = "111.999"
    read_client = MagicMock()
    read_client.conversations_replies.return_value = {
        "messages": [fake_msg]
    }

    req_data, found_ts, history, state = slack_io.find_card_in_thread(read_client, "C_PURCHASING", "111.222")
    assert state == "approved"
    assert found_ts == "111.999"
    assert req_data.get("assignee_id") == "U_BUYER"


def test_thread_with_existing_card_is_updated_not_duplicated(temp_epifs_dir, temp_boms_dir, sync_queue):
    """AC 4: When a card already exists in the thread, chat_update is called once on that card, and no card chat_postMessage is sent."""
    client = MagicMock()
    client.conversations_open.return_value = {"channel": {"id": "D_BUYER"}}

    parsed = _valid_request()
    existing_payload = {
        "parsed": parsed,
        "requester": "Alex",
        "user_id": "U_REQ",
        "state": "posted",
        "thread_ts": "111.222",
    }
    existing_blocks = blocks.build_request_blocks("posted", existing_payload)
    existing_msg = {
        "ts": "111.555",
        "blocks": existing_blocks,
        "metadata": {
            "event_type": "purchase_request",
            "event_payload": existing_payload,
        },
    }
    client.conversations_replies.return_value = {
        "messages": [existing_msg]
    }

    say = MagicMock()
    lifecycle.finalize_purchase_request(
        client=client,
        say=say,
        channel="C_PURCHASING",
        thread_ts="111.222",
        event_ts="111.333",
        parsed=parsed,
        requester="Alex",
        notify_target="U_REQ",
        assignee_id="U_BUYER",
        assignee_name="Dylan",
        approver="U_CHARLIE",
        pdf_bytes=b"fake_pdf_data",
        file_name="order.pdf",
    )

    assert client.chat_update.call_count == 2
    assert client.chat_update.call_args[1]["ts"] == "111.555"

    card_posts = [
        c[1] for c in client.chat_postMessage.call_args_list
        if c[1].get("metadata", {}).get("event_type") == "purchase_request"
    ]
    assert len(card_posts) == 0, f"Expected no card postMessage when updating existing card, got {len(card_posts)}"


def test_failing_card_post_does_not_undo_approval(temp_epifs_dir, temp_boms_dir, sync_queue, caplog):
    """AC 5: chat_postMessage raising for the card post only: row written, assignee DM sent, error in caplog, no exception escapes."""
    client = _make_client_with_human_thread()

    def post_side_effect(**kwargs):
        if kwargs.get("metadata", {}).get("event_type") == "purchase_request":
            raise RuntimeError("Slack card post simulated failure")
        return {"ok": True, "ts": "111.888"}

    client.chat_postMessage.side_effect = post_side_effect
    say = MagicMock()
    parsed = _valid_request()

    with caplog.at_level(logging.ERROR):
        lifecycle.finalize_purchase_request(
            client=client,
            say=say,
            channel="C_PURCHASING",
            thread_ts="111.222",
            event_ts="111.333",
            parsed=parsed,
            requester="Alex",
            notify_target="U_REQ",
            assignee_id="U_BUYER",
            assignee_name="Dylan",
            approver="U_CHARLIE",
            pdf_bytes=b"fake_pdf_data",
            file_name="order.pdf",
        )

    log_writer.append_row.assert_called_once()
    client.files_upload_v2.assert_called_once()
    assert any("Failed to post purchase request card" in r.message for r in caplog.records)
