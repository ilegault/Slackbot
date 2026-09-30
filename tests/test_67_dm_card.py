"""Tests for Ticket 67: The assigned buyer's DM carries a card with the next-step button."""
import json
import logging
import os
from datetime import date
from unittest.mock import MagicMock

import pytest

from src import blocks, config, lifecycle, log_writer, queue_worker, roster, validators

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
        "buyers": ["U_BUYER", "U_BUYER2"],
        "requesters": {
            "U_ADMIN": "Isaac",
            "U_CHARLIE": "Charlie H.",
            "U_BUYER": "Dylan",
            "U_BUYER2": "Lisa",
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

    monkeypatch.setattr(log_writer, "append_row", lambda row_vals: 17)
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


def test_dm_card_blocks_shape():
    """Criterion 1: The DM card's shape for approved, processed, confirmed, delivered."""
    req = {
        "parsed": {
            "item_description": "Widget",
            "vendor": "Acme",
            "total_price": 12.50,
        },
        "row": 17,
    }

    # approved -> Mark Processed, dm_req_processed
    blks_appr = blocks.build_dm_card_blocks(
        state="approved",
        request=req,
        thread_channel="C123",
        thread_ts="111.222",
        card_ts="333.444",
        thread_link=None,
    )
    assert len(blks_appr) == 2
    sec_text = blks_appr[0]["text"]["text"]
    assert "Widget" in sec_text
    assert "Acme" in sec_text
    assert "$12.50" in sec_text
    assert "Row 17" in sec_text
    assert "Stage: *approved*" in sec_text
    assert "<http" not in sec_text

    actions_appr = blks_appr[1]
    assert actions_appr["type"] == "actions"
    assert len(actions_appr["elements"]) == 1
    btn_appr = actions_appr["elements"][0]
    assert btn_appr["text"]["text"] == "Mark Processed"
    assert btn_appr["action_id"] == config.ACTION_DM_REQ_PROCESSED
    assert btn_appr["style"] == "primary"
    val_appr = json.loads(btn_appr["value"])
    assert set(val_appr.keys()) == {"thread_channel", "thread_ts", "card_ts"}
    assert val_appr["thread_channel"] == "C123"
    assert val_appr["thread_ts"] == "111.222"
    assert val_appr["card_ts"] == "333.444"

    # With thread_link
    blks_link = blocks.build_dm_card_blocks(
        state="approved",
        request=req,
        thread_channel="C123",
        thread_ts="111.222",
        card_ts="333.444",
        thread_link="https://slack.com/archives/C123/p111222",
    )
    sec_link_text = blks_link[0]["text"]["text"]
    assert "<https://slack.com/archives/C123/p111222|Open the request thread>" in sec_link_text

    # processed -> Mark Confirmed, dm_req_confirmed
    blks_proc = blocks.build_dm_card_blocks(
        state="processed",
        request=req,
        thread_channel="C123",
        thread_ts="111.222",
        card_ts="333.444",
    )
    assert len(blks_proc) == 2
    btn_proc = blks_proc[1]["elements"][0]
    assert btn_proc["text"]["text"] == "Mark Confirmed"
    assert btn_proc["action_id"] == config.ACTION_DM_REQ_CONFIRMED
    assert btn_proc["style"] == "primary"

    # confirmed -> Mark Delivered, dm_req_delivered
    blks_conf = blocks.build_dm_card_blocks(
        state="confirmed",
        request=req,
        thread_channel="C123",
        thread_ts="111.222",
        card_ts="333.444",
    )
    assert len(blks_conf) == 2
    btn_conf = blks_conf[1]["elements"][0]
    assert btn_conf["text"]["text"] == "Mark Delivered"
    assert btn_conf["action_id"] == config.ACTION_DM_REQ_DELIVERED
    assert btn_conf["style"] == "primary"

    # delivered -> no actions block
    blks_del = blocks.build_dm_card_blocks(
        state="delivered",
        request=req,
        thread_channel="C123",
        thread_ts="111.222",
        card_ts="333.444",
    )
    assert len(blks_del) == 1
    assert blks_del[0]["type"] == "section"

    # No state has a Cancel button
    for blks in (blks_appr, blks_proc, blks_conf, blks_del):
        for b in blks:
            if b.get("type") == "actions":
                for elem in b.get("elements", []):
                    assert elem.get("text", {}).get("text") != "Cancel"
                    assert "cancel" not in elem.get("action_id", "").lower()


def test_approval_with_buyer_posts_card_after_draft_and_records_where(
    temp_epifs_dir, temp_boms_dir, sync_queue
):
    """Criterion 2: Approval with a buyer posts the card after draft & upload, recording dm_channel & dm_ts."""
    client = MagicMock()

    def fake_post_message(*args, **kwargs):
        chan = kwargs.get("channel")
        if chan == "U_BUYER":
            return {"channel": "D_BUYER", "ts": "9.9"}
        if chan == "C123":
            return {"channel": "C123", "ts": "5.5"}
        return {"channel": chan or "C_OTHER", "ts": "1.1"}

    client.chat_postMessage.side_effect = fake_post_message
    client.conversations_open.return_value = {"channel": {"id": "D_BUYER"}}
    client.chat_getPermalink.return_value = {"permalink": "https://slack.com/archives/C123/p55"}
    say = MagicMock()

    parsed = _valid_request(total_price=50.0, category="Supplies")
    pdf_bytes = b"fake_pdf_content"

    lifecycle.finalize_purchase_request(
        client=client,
        say=say,
        channel="C123",
        thread_ts="111.222",
        event_ts="111.333",
        parsed=parsed,
        requester="U_REQ",
        notify_target="U_REQ",
        assignee_id="U_BUYER",
        assignee_name="Dylan",
        approver="U_CHARLIE",
        pdf_bytes=pdf_bytes,
        file_name="uploaded_epif.pdf",
    )

    # Check call ordering in client.mock_calls:
    # 1. Plain draft call to U_BUYER (text only, no blocks)
    # 2. files_upload_v2
    # 3. DM card call to U_BUYER (has blocks)
    calls = client.mock_calls
    draft_idx = None
    upload_idx = None
    dm_card_idx = None

    for i, c in enumerate(calls):
        call_name, call_args, call_kwargs = c
        if "chat_postMessage" in call_name and call_kwargs.get("channel") == "U_BUYER":
            if call_kwargs.get("blocks"):
                dm_card_idx = i
            else:
                draft_idx = i
        elif "files_upload_v2" in call_name:
            upload_idx = i

    assert draft_idx is not None, "Draft DM must be sent"
    assert upload_idx is not None, "EPIF file must be uploaded"
    assert dm_card_idx is not None, "DM card must be posted"
    assert draft_idx < upload_idx < dm_card_idx, (
        f"Call order must be draft ({draft_idx}) -> upload ({upload_idx}) -> DM card ({dm_card_idx})"
    )

    # The DM card's button value holds card_ts equal to the thread card's ts ("5.5")
    dm_card_call = calls[dm_card_idx]
    dm_blocks = dm_card_call[2]["blocks"]
    btn_val = json.loads(dm_blocks[1]["elements"][0]["value"])
    assert btn_val["card_ts"] == "5.5"
    assert btn_val["thread_channel"] == "C123"

    # The last chat_update of the thread card has button value holding dm_channel == "D_BUYER" and dm_ts == "9.9"
    update_calls = [c for c in client.chat_update.call_args_list if c[1].get("channel") == "C123"]
    assert update_calls, "Thread card must be updated with DM card reference"
    last_update = update_calls[-1]
    thread_blks = last_update[1]["blocks"]
    thread_btn_val = json.loads(thread_blks[-1]["elements"][0]["value"])
    assert thread_btn_val["request"]["dm_channel"] == "D_BUYER"
    assert thread_btn_val["request"]["dm_ts"] == "9.9"


def test_approval_workday_path_posts_dm_card(temp_epifs_dir, temp_boms_dir, sync_queue):
    """Criterion 3: Workday-path approval posts DM card and does not call files_upload_v2."""
    client = MagicMock()

    def fake_post_message(*args, **kwargs):
        chan = kwargs.get("channel")
        if chan == "U_BUYER":
            return {"channel": "D_BUYER", "ts": "9.9"}
        if chan == "C123":
            return {"channel": "C123", "ts": "5.5"}
        return {"channel": chan or "C_OTHER", "ts": "1.1"}

    client.chat_postMessage.side_effect = fake_post_message
    client.conversations_open.return_value = {"channel": {"id": "D_BUYER"}}
    client.chat_getPermalink.return_value = {"permalink": "https://slack.com/archives/C123/p55"}
    say = MagicMock()

    parsed = _valid_request(total_price=50.0, category="Supplies")
    parsed["payment_method"] = "Workday"

    lifecycle.finalize_purchase_request(
        client=client,
        say=say,
        channel="C123",
        thread_ts="111.222",
        event_ts="111.333",
        parsed=parsed,
        requester="U_REQ",
        notify_target="U_REQ",
        assignee_id="U_BUYER",
        assignee_name="Dylan",
        approver="U_CHARLIE",
        pdf_bytes=None,
        file_name=None,
    )

    client.files_upload_v2.assert_not_called()

    # DM card posted to U_BUYER
    dm_card_calls = [
        c for c in client.chat_postMessage.call_args_list
        if c[1].get("channel") == "U_BUYER" and c[1].get("blocks")
    ]
    assert len(dm_card_calls) == 1

    # Thread card updated with DM reference
    update_calls = [c for c in client.chat_update.call_args_list if c[1].get("channel") == "C123"]
    assert update_calls
    last_update = update_calls[-1]
    thread_blks = last_update[1]["blocks"]
    thread_btn_val = json.loads(thread_blks[-1]["elements"][0]["value"])
    assert thread_btn_val["request"]["dm_channel"] == "D_BUYER"
    assert thread_btn_val["request"]["dm_ts"] == "9.9"


def test_handle_assign_posts_dm_card_and_cardless_thread_does_not(caplog):
    """Criterion 4: Later assignment posts DM card; card-less thread does not and logs warning."""
    client = MagicMock()

    def fake_post_message(*args, **kwargs):
        chan = kwargs.get("channel")
        if chan == "U_BUYER2":
            return {"channel": "D_BUYER2", "ts": "8.8"}
        return {"channel": chan or "C_OTHER", "ts": "1.1"}

    client.chat_postMessage.side_effect = fake_post_message
    client.conversations_open.return_value = {"channel": {"id": "D_BUYER2"}}
    client.chat_getPermalink.return_value = {"permalink": "https://slack.com/archives/C123/p44"}
    say = MagicMock()

    existing_req = {
        "parsed": _valid_request(total_price=50.0),
        "assignee_id": "U_BUYER",
        "assignee": "Dylan",
    }
    existing_button_val = json.dumps({
        "state": "approved",
        "request": existing_req,
        "history": ["Approved by Charlie on 09/22/26 10:00"],
    }, default=str)

    client.conversations_replies.return_value = {
        "messages": [
            {
                "ts": "44.44",
                "blocks": [
                    {
                        "type": "actions",
                        "elements": [
                            {"type": "button", "value": existing_button_val},
                        ],
                    }
                ],
            }
        ]
    }

    # 1. With an approved card present in thread:
    success = lifecycle.handle_assign(
        client=client,
        say=say,
        channel="C123",
        thread_ts="111.222",
        user_id="U_CHARLIE",
        event_ts="222.333",
        target_user_id="U_BUYER2",
    )
    assert success is True

    # DM card posted to U_BUYER2
    dm_card_calls = [
        c for c in client.chat_postMessage.call_args_list
        if c[1].get("channel") == "U_BUYER2" and c[1].get("blocks")
    ]
    assert len(dm_card_calls) == 1
    dm_btn_val = json.loads(dm_card_calls[0][1]["blocks"][1]["elements"][0]["value"])
    assert dm_btn_val["card_ts"] == "44.44"

    # Thread card updated with DM reference
    update_calls = [c for c in client.chat_update.call_args_list if c[1].get("ts") == "44.44"]
    assert len(update_calls) >= 2  # first update for new assignee, second for DM reference
    last_update = update_calls[-1]
    thread_blks = last_update[1]["blocks"]
    thread_btn_val = json.loads(thread_blks[-1]["elements"][0]["value"])
    assert thread_btn_val["request"]["dm_channel"] == "D_BUYER2"
    assert thread_btn_val["request"]["dm_ts"] == "8.8"

    # 2. With no card found in thread:
    client.reset_mock()
    client.conversations_replies.return_value = {"messages": []}
    caplog.clear()

    with caplog.at_level(logging.WARNING):
        lifecycle.handle_assign(
            client=client,
            say=say,
            channel="C123",
            thread_ts="111.222",
            user_id="U_CHARLIE",
            event_ts="222.333",
            target_user_id="U_BUYER2",
        )

    # No DM card posted
    dm_card_calls_no_card = [
        c for c in client.chat_postMessage.call_args_list
        if c[1].get("channel") == "U_BUYER2" and c[1].get("blocks")
    ]
    assert not dm_card_calls_no_card
    assert any("card_ts" in rec.message or "card" in rec.message.lower() for rec in caplog.records if rec.levelno >= logging.WARNING)


def test_failed_dm_card_never_undoes_approval(temp_epifs_dir, temp_boms_dir, sync_queue, monkeypatch):
    """Criterion 5: post_dm_card returning None doesn't undo approval and alerts admin channel."""
    monkeypatch.setattr(config, "ADMIN_ALERT_CHANNEL", "C_ADMIN_ALERT")
    client = MagicMock()

    # Track append_row calls
    row_append_count = 0
    def fake_append_row(row_vals):
        nonlocal row_append_count
        row_append_count += 1
        return 17
    monkeypatch.setattr(log_writer, "append_row", fake_append_row)

    # chat_postMessage succeeds for draft and C123, raises for U_BUYER with blocks
    def fake_post_message(*args, **kwargs):
        chan = kwargs.get("channel")
        blocks_arg = kwargs.get("blocks")
        if chan == "U_BUYER" and blocks_arg:
            raise RuntimeError("chat.postMessage failed for DM card")
        if chan == "U_BUYER":
            return {"channel": "D_BUYER", "ts": "9.9"}
        if chan == "C123":
            return {"channel": "C123", "ts": "5.5"}
        return {"channel": chan or "C_OTHER", "ts": "1.1"}

    client.chat_postMessage.side_effect = fake_post_message
    client.conversations_open.return_value = {"channel": {"id": "D_BUYER"}}
    client.chat_getPermalink.return_value = {"permalink": "https://slack.com/archives/C123/p55"}
    say = MagicMock()

    parsed = _valid_request(total_price=50.0, category="Supplies")

    lifecycle.finalize_purchase_request(
        client=client,
        say=say,
        channel="C123",
        thread_ts="111.222",
        event_ts="111.333",
        parsed=parsed,
        requester="U_REQ",
        notify_target="U_REQ",
        assignee_id="U_BUYER",
        assignee_name="Dylan",
        approver="U_CHARLIE",
        pdf_bytes=None,
        file_name=None,
    )

    # Row-append was called once
    assert row_append_count == 1

    # Thread card exists with no dm_channel
    update_calls = [c for c in client.chat_update.call_args_list if c[1].get("channel") == "C123"]
    # There should be no second chat_update containing dm_channel
    for call in update_calls:
        blks = call[1].get("blocks", [])
        for b in blks:
            if b.get("type") == "actions":
                for elem in b.get("elements", []):
                    v = json.loads(elem["value"])
                    assert "dm_channel" not in v.get("request", {})

    # Alert posted to admin alert channel
    alert_calls = [
        c for c in client.chat_postMessage.call_args_list
        if c[1].get("channel") == "C_ADMIN_ALERT"
    ]
    assert len(alert_calls) == 1
    alert_text = alert_calls[0][1]["text"]
    assert "post the buyer's DM card" in alert_text
