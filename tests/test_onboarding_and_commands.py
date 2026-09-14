import json
import os
import sys
from unittest.mock import MagicMock, patch
import pytest

# Determine project root and src directory
_CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(_CURRENT_DIR) if os.path.basename(_CURRENT_DIR) == "tests" else _CURRENT_DIR
SRC_DIR = os.path.join(PROJECT_ROOT, "src")
for p in (PROJECT_ROOT, SRC_DIR):
    if p not in sys.path:
        sys.path.insert(0, p)

from src import admin, app, config, interview, roster


@pytest.fixture(autouse=True)
def setup_test_roster(tmp_path, monkeypatch):
    test_roster_file = str(tmp_path / "roster.json")
    monkeypatch.setattr(roster, "ROSTER_PATH", test_roster_file)
    roster.load_roster()
    return test_roster_file


def test_approver_gate_in_dispatch_command():
    client = MagicMock()
    say = MagicMock()

    # 1. Non-approver trying to approve
    app.dispatch_command(
        client=client,
        say=say,
        channel="C123",
        thread_ts="1234.56",
        user="UNONAPPROVER",
        event_ts="1234.57",
        text="@p-bot approved",
    )
    say.assert_called_once()
    assert "Only Charlie Hirst can approve purchase requests" in say.call_args[1]["text"]

    # 2. Non-approver sending direct file (bare PDF DM)
    say.reset_mock()
    fake_pdf = {"name": "test.pdf", "url_private": "https://slack.com/files/test.pdf"}
    app.dispatch_command(
        client=client,
        say=say,
        channel="D123",
        thread_ts="1234.58",
        user="UNONAPPROVER",
        event_ts="1234.59",
        text="",
        direct_file=fake_pdf,
    )
    say.assert_called_once()
    assert "Only Charlie Hirst can approve purchase requests" in say.call_args[1]["text"]


def test_admin_commands_permission_denial():
    client = MagicMock()
    say = MagicMock()

    # User not in admin list
    non_admin = "UNOTADMIN"

    # promote-admin
    app.dispatch_command(client, say, "C123", "ts", non_admin, "ts", "@p-bot promote-admin <@U123>")
    assert "restricted to bot administrators" in say.call_args[1]["text"]

    # add-approver
    say.reset_mock()
    app.dispatch_command(client, say, "C123", "ts", non_admin, "ts", "@p-bot add-approver <@U123>")
    assert "restricted to bot administrators" in say.call_args[1]["text"]

    # remove-approver
    say.reset_mock()
    app.dispatch_command(client, say, "C123", "ts", non_admin, "ts", "@p-bot remove-approver <@U123>")
    assert "restricted to bot administrators" in say.call_args[1]["text"]

    # remove vendor
    say.reset_mock()
    app.dispatch_command(client, say, "C123", "ts", non_admin, "ts", "@p-bot remove vendor Fisher Scientific")
    assert "restricted to bot administrators" in say.call_args[1]["text"]


def test_admin_commands_success(monkeypatch):
    client = MagicMock()
    say = MagicMock()
    admin_id = "UADMIN"
    roster.add_admin(admin_id)

    # 1. Add approver
    app.dispatch_command(client, say, "C123", "ts", admin_id, "ts", "@p-bot add-approver <@UNEWAPPROVER>")
    assert "added to purchase approvers" in say.call_args[1]["text"]
    assert "UNEWAPPROVER" in roster.get_approvers()

    # 2. Remove approver
    say.reset_mock()
    app.dispatch_command(client, say, "C123", "ts", admin_id, "ts", "@p-bot remove-approver <@UNEWAPPROVER>")
    assert "removed from purchase approvers" in say.call_args[1]["text"]
    assert "UNEWAPPROVER" not in roster.get_approvers()

    # 3. Remove vendor
    say.reset_mock()
    roster.add_vendor("Temporary Vendor Inc")
    assert "Temporary Vendor Inc" in roster.get_vendors()
    app.dispatch_command(client, say, "C123", "ts", admin_id, "ts", "@p-bot remove vendor Temporary Vendor Inc")
    assert "removed from `roster.json`" in say.call_args[1]["text"]
    assert "Temporary Vendor Inc" not in roster.get_vendors()

    # 4. Promote admin proposal
    say.reset_mock()
    monkeypatch.setattr(config, "ADMIN_ALERT_CHANNEL", "C_ALERTS")
    app.dispatch_command(client, say, "C123", "ts", admin_id, "ts", "@p-bot promote-admin <@UCANDIDATE>")
    client.chat_postMessage.assert_called_once()
    assert client.chat_postMessage.call_args[1]["channel"] == "C_ALERTS"
    assert "Admin promotion proposal" in say.call_args[1]["text"]


def test_template_command(tmp_path, monkeypatch):
    client = MagicMock()
    say = MagicMock()

    # Missing directory/files
    fake_temp_dir = str(tmp_path / "templates")
    monkeypatch.setattr(config, "TEMPLATE_DIR", fake_temp_dir)

    app.handle_template_command(client, say, "C123", "ts", "U123")
    assert "Template files missing" in say.call_args[1]["text"]

    # With files present
    os.makedirs(fake_temp_dir, exist_ok=True)
    with open(os.path.join(fake_temp_dir, "EPIF_TEMPLATE_HIRST.pdf"), "w") as f:
        f.write("dummy pdf")
    with open(os.path.join(fake_temp_dir, "README.md"), "w") as f:
        f.write("dummy readme")

    say.reset_mock()
    app.handle_template_command(client, say, "C123", "ts", "U123")
    assert "Manual EPIF Submission Kit" in say.call_args[1]["text"]
    assert client.files_upload_v2.call_count == 2


def test_build_interview_modal():
    # Known user modal
    modal_known = app.build_interview_modal(prefill_name_field=False, resolved_name="Dylan", user_id="U123")
    block_ids_known = [b["block_id"] for b in modal_known["blocks"]]
    assert "block_proposed_name" not in block_ids_known
    assert "block_item_description" in block_ids_known
    assert "block_vendor" in block_ids_known
    assert modal_known["callback_id"] == "purchase_interview_submit"

    # Unknown user modal (has name field at top)
    modal_unknown = app.build_interview_modal(prefill_name_field=True, resolved_name=None, user_id="U456")
    block_ids_unknown = [b["block_id"] for b in modal_unknown["blocks"]]
    assert block_ids_unknown[0] == "block_proposed_name"


def test_handle_interview_submission_validation_error():
    ack = MagicMock()
    body = {"user": {"id": "U123"}}
    client = MagicMock()

    # Incomplete modal state (missing required fields)
    view = {
        "state": {"values": {}},
        "private_metadata": json.dumps({"resolved_name": "Isaac", "user_id": "U123"}),
    }

    app.handle_interview_submission(ack, body, client, view)
    ack.assert_called_once()
    call_kwargs = ack.call_args[1]
    assert call_kwargs["response_action"] == "errors"
    assert "block_vendor" in call_kwargs["errors"]
    assert "block_item_description" in call_kwargs["errors"]


def test_handle_interview_submission_success(monkeypatch):
    ack = MagicMock()
    body = {"user": {"id": "U123"}}
    client = MagicMock()
    client.chat_postMessage.return_value = {"ts": "1234.56"}

    monkeypatch.setattr(config, "ADMIN_ALERT_CHANNEL", "C_ALERTS")

    view = {
        "state": {
            "values": {
                "block_item_description": {"item_description": {"value": "Box of Pipettes"}},
                "block_purpose": {"purpose": "Cell culture https://fishersci.com/pipettes"},
                "block_vendor": {"vendor_select": {"selected_option": {"value": "Fisher Scientific"}}},
                "block_total_price": {"total_price": {"value": "120.00"}},
                "block_vendor_contact_email": {"vendor_contact_email": {"value": "orders@fishersci.com"}},
                "block_date_of_purchase": {"date_of_purchase": {"selected_date": "2026-09-14"}},
                "block_delivery_room": {"delivery_room": {"selected_option": {"value": "ERB 212"}}},
                "block_project_id": {"project_id": {"selected_option": {"value": "PG000025831"}}},
                "block_fund": {"fund": {"selected_option": {"value": "133"}}},
                "block_category": {"category": {"selected_option": {"value": "Research/Lab Supplies (3105)"}}},
            }
        },
        "private_metadata": json.dumps({"resolved_name": "Isaac", "user_id": "U123"}),
    }

    app.handle_interview_submission(ack, body, client, view)
    ack.assert_called_once_with()
    client.chat_postMessage.assert_called()
    post_calls = client.chat_postMessage.call_args_list
    assert any("Box of Pipettes" in str(call) for call in post_calls)


def test_faq_routing_in_dm():
    client = MagicMock()
    say = MagicMock()

    # FAQ Question
    event_faq = {
        "channel_type": "im",
        "user": "U123",
        "channel": "D123",
        "ts": "1234.56",
        "text": "What is a project id?",
    }
    app.on_direct_message(event_faq, client, say)
    say.assert_called_once()
    assert "PG000025831" in say.call_args[1]["text"]

    # Command (not a question) -> should route to dispatch_command (e.g. @p-bot help)
    say.reset_mock()
    event_cmd = {
        "channel_type": "im",
        "user": "U123",
        "channel": "D123",
        "ts": "1234.57",
        "text": "help",
    }
    app.on_direct_message(event_cmd, client, say)
    say.assert_called_once()
    assert "Hirst Lab Purchasing Bot (P-Bot) Commands" in say.call_args[1]["text"]
