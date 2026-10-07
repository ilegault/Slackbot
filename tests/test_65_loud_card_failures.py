"""Tests for Ticket 65: A missing or failed card is reported loudly to the admin channel."""
import json
import logging
import os
from datetime import date
from unittest.mock import MagicMock

import pytest

from src import config, epif_parser, lifecycle, log_writer, queue_worker, roster, slack_io, text_rules, validators

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

    monkeypatch.setattr(log_writer, "save_bom", fake_save_bom)
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


def test_alert_admins_never_raises(monkeypatch, caplog):
    """AC 1: alert_admins posts when channel set, returns False when channel unset or post raises, never raises."""
    monkeypatch.setattr(config, "ADMIN_ALERT_CHANNEL", "C_ALERT")
    client = MagicMock()

    # Case 1: working client and set channel -> posts once and returns True
    res = slack_io.alert_admins(client, "Test alert message")
    assert res is True
    client.chat_postMessage.assert_called_once_with(channel="C_ALERT", text="Test alert message")

    # Case 2: channel is empty string -> returns False, posts nothing
    client.reset_mock()
    monkeypatch.setattr(config, "ADMIN_ALERT_CHANNEL", "")
    with caplog.at_level(logging.WARNING):
        res = slack_io.alert_admins(client, "Another alert")
    assert res is False
    client.chat_postMessage.assert_not_called()

    # Case 3: client is None -> returns False, posts nothing
    with caplog.at_level(logging.WARNING):
        res = slack_io.alert_admins(None, "Another alert")
    assert res is False

    # Case 4: chat_postMessage raises -> returns False, does not raise, logs warning
    monkeypatch.setattr(config, "ADMIN_ALERT_CHANNEL", "C_ALERT")
    client.reset_mock()
    client.chat_postMessage.side_effect = RuntimeError("Slack API failure")
    with caplog.at_level(logging.WARNING):
        res = slack_io.alert_admins(client, "Failing alert")
    assert res is False
    assert any("Slack API failure" in record.message for record in caplog.records)


def test_format_card_failure_alert():
    """AC 2: format_card_failure_alert produces required lines; omits File line when file_name is None."""
    msg = text_rules.format_card_failure_alert(
        "post the approval card", "C1", "111.222", "EPIF_x.pdf", "boom"
    )
    for expected in ["post the approval card", "C1", "111.222", "EPIF_x.pdf", "boom"]:
        assert expected in msg, f"Expected {expected} in alert message"

    assert "⚠️ *Purchase card problem*" in msg
    assert "• *Step:* post the approval card" in msg
    assert "• *Channel:* <#C1>" in msg
    assert "• *Thread:* 111.222" in msg
    assert "• *File:* EPIF_x.pdf" in msg
    assert "• *Error:* boom" in msg

    msg_no_file = text_rules.format_card_failure_alert(
        "post the approval card", "C1", "111.222", None, "boom"
    )
    assert "• *File:*" not in msg_no_file
    assert "File:" not in msg_no_file
    assert "• *Step:* post the approval card" in msg_no_file



def test_non_epif_pdf_parse_failure_stays_silent(monkeypatch, caplog):
    """AC 4: notes.pdf parse failure stays silent; EPIF_notes.pdf parse failure alerts admins."""
    monkeypatch.setattr(config, "ADMIN_ALERT_CHANNEL", "C_ALERT")
    monkeypatch.setattr(slack_io, "download", lambda f: b"fake_bytes")

    def failing_parse(b):
        raise RuntimeError("cannot parse AcroForm")

    monkeypatch.setattr(epif_parser, "parse_epif", failing_parse)

    client = MagicMock()
    say = MagicMock()

    # Part 1: notes.pdf (non-EPIF)
    with caplog.at_level(logging.INFO):
        lifecycle.handle_epif_drop(
            client=client,
            say=say,
            channel="C_THREAD",
            thread_ts="111.222",
            user_id="U_REQ",
            file_obj={"name": "notes.pdf", "id": "F1"},
            event_ts="111.222",
        )

    alert_posts = [
        c[1] for c in client.chat_postMessage.call_args_list
        if c[1].get("channel") == "C_ALERT"
    ]
    assert len(alert_posts) == 0, "Non-EPIF PDF must not alert admins"
    info_exits = [
        r.message for r in caplog.records
        if r.levelno == logging.INFO and "drop exit:" in r.message
    ]
    assert len(info_exits) == 1
    assert info_exits[0].endswith("drop exit: parse failed (not an EPIF name, ignored)")

    # Part 2: EPIF_notes.pdf (EPIF-named)
    client.reset_mock()
    caplog.clear()

    with caplog.at_level(logging.INFO):
        lifecycle.handle_epif_drop(
            client=client,
            say=say,
            channel="C_THREAD",
            thread_ts="111.222",
            user_id="U_REQ",
            file_obj={"name": "EPIF_notes.pdf", "id": "F2"},
            event_ts="111.222",
        )

    alert_posts = [
        c[1] for c in client.chat_postMessage.call_args_list
        if c[1].get("channel") == "C_ALERT"
    ]
    assert len(alert_posts) == 1, "EPIF-named PDF parse failure must alert admins"
    assert "EPIF_notes.pdf" in alert_posts[0]["text"]
    assert "parse the dropped EPIF" in alert_posts[0]["text"]
    assert "cannot parse AcroForm" in alert_posts[0]["text"]

    info_exits = [
        r.message for r in caplog.records
        if r.levelno == logging.INFO and "drop exit:" in r.message
    ]
    assert len(info_exits) == 1
    assert info_exits[0].endswith("drop exit: parse failed")

    # Part 3: Unexpected error on EPIF-named PDF
    client.reset_mock()
    caplog.clear()

    def unexpected_error(b):
        raise ValueError("corrupt structure")

    monkeypatch.setattr(epif_parser, "parse_epif", unexpected_error)

    with caplog.at_level(logging.INFO):
        lifecycle.handle_epif_drop(
            client=client,
            say=say,
            channel="C_THREAD",
            thread_ts="111.222",
            user_id="U_REQ",
            file_obj={"name": "EPIF_broken.pdf", "id": "F3"},
            event_ts="111.222",
        )

    alert_posts = [
        c[1] for c in client.chat_postMessage.call_args_list
        if c[1].get("channel") == "C_ALERT"
    ]
    assert len(alert_posts) == 1
    assert "EPIF_broken.pdf" in alert_posts[0]["text"]
    assert "corrupt structure" in alert_posts[0]["text"]
    info_exits = [
        r.message for r in caplog.records
        if r.levelno == logging.INFO and "drop exit:" in r.message
    ]
    assert len(info_exits) == 1
    assert info_exits[0].endswith("drop exit: unexpected error")


def test_failed_card_update_at_approval_alerts(temp_epifs_dir, temp_boms_dir, sync_queue, monkeypatch):
    """AC 5: A failed card update at approval alerts and does not undo the approval."""
    monkeypatch.setattr(config, "ADMIN_ALERT_CHANNEL", "C_ALERT")

    client = MagicMock()
    client.conversations_open.return_value = {"channel": {"id": "D_BUYER"}}
    client.conversations_replies.return_value = {
        "messages": [
            {
                "text": "Card",
                "ts": "111.222",
                "metadata": {
                    "event_type": "purchase_request",
                    "event_payload": {
                        "parsed": _valid_request(),
                        "state": "posted",
                        "requester": "Alex",
                        "user_id": "U_REQ",
                    },
                },
            }
        ]
    }
    client.chat_update.side_effect = RuntimeError("Slack update failed")

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
        file_name="EPIF_test.pdf",
        card_ts="111.222",
    )

    # 1. Alert message posted to C_ALERT containing "update the approval card"
    alert_posts = [
        c[1] for c in client.chat_postMessage.call_args_list
        if c[1].get("channel") == "C_ALERT"
    ]
    assert len(alert_posts) == 1
    assert "update the approval card" in alert_posts[0]["text"]
    assert "Slack update failed" in alert_posts[0]["text"]

    # 2. Row append was still called once
    log_writer.append_row.assert_called_once()

    # 3. Buyer DM was still sent
    dm_posts = [
        c[1] for c in client.chat_postMessage.call_args_list
        if c[1].get("channel") == "U_BUYER"
    ]
    assert len(dm_posts) >= 1


def test_failed_fallback_card_post_at_approval_alerts(temp_epifs_dir, temp_boms_dir, sync_queue, monkeypatch):
    """AC 5 extension: A failed fallback card post at approval alerts and does not undo the approval."""
    monkeypatch.setattr(config, "ADMIN_ALERT_CHANNEL", "C_ALERT")

    client = MagicMock()
    client.conversations_open.return_value = {"channel": {"id": "D_BUYER"}}
    # Human message only -> no existing card
    client.conversations_replies.return_value = {
        "messages": [
            {"text": "Human message", "ts": "111.000", "user": "U_REQ"}
        ]
    }

    def fake_post_message(channel, **kwargs):
        if channel == "C_PURCHASING":
            raise RuntimeError("fallback card post failed")
        return {"ts": "999.000"}

    client.chat_postMessage.side_effect = fake_post_message

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
        file_name="EPIF_test.pdf",
    )

    # Alert message posted to C_ALERT containing "post the approval card"
    alert_posts = [
        c[1] for c in client.chat_postMessage.call_args_list
        if c[1].get("channel") == "C_ALERT"
    ]
    assert len(alert_posts) == 1
    assert "post the approval card" in alert_posts[0]["text"]
    assert "fallback card post failed" in alert_posts[0]["text"]

    # Row append was still called once
    log_writer.append_row.assert_called_once()

    # Buyer DM was still sent
    dm_posts = [
        c[1] for c in client.chat_postMessage.call_args_list
        if c[1].get("channel") == "U_BUYER"
    ]
    assert len(dm_posts) >= 1
