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

from src import admin, app, blocks, config, interview, lifecycle, ops, roster


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

    ops.handle_template_command(client, say, "C123", "ts", "U123")
    assert "Template files missing" in say.call_args[1]["text"]

    # With files present
    os.makedirs(fake_temp_dir, exist_ok=True)
    with open(os.path.join(fake_temp_dir, "EPIF_TEMPLATE_HIRST.pdf"), "w") as f:
        f.write("dummy pdf")
    with open(os.path.join(fake_temp_dir, "README.md"), "w") as f:
        f.write("dummy readme")

    say.reset_mock()
    ops.handle_template_command(client, say, "C123", "ts", "U123")
    assert "Manual EPIF Submission Kit" in say.call_args[1]["text"]
    assert client.files_upload_v2.call_count == 2


def test_command_registration():
    """Verify all 5 slash command listeners are registered on Bolt app."""
    expected = {"/new-purchase", "/purchasing-help", "/blank-template", "/roster-set-name", "/roster-list"}
    registered_commands = set()
    for listener in app.app._listeners:
        for matcher in listener.matchers:
            if matcher.func.__closure__:
                for cell in matcher.func.__closure__:
                    if isinstance(cell.cell_contents, str) and cell.cell_contents in expected:
                        registered_commands.add(cell.cell_contents)
    assert expected.issubset(registered_commands)


def test_screen1_to_screen2_routing():
    """Workday vendor omits payment_method block; EPIF route renders required payment_method block."""
    # 1. Workday vendor route
    meta_workday = {
        "resolved_name": "Isaac",
        "user_id": "U123",
        "vendor_choice": "Fisher Scientific",
        "vendor_custom": "",
        "route": "workday",
    }
    view_workday = blocks.build_stage2_view(meta_workday)
    block_ids_workday = [b["block_id"] for b in view_workday["blocks"]]
    assert "block_payment_method" not in block_ids_workday
    assert "block_item_description" in block_ids_workday
    assert view_workday["callback_id"] == config.STAGE2_CALLBACK_ID

    # 2. EPIF / Other vendor route
    meta_epif = {
        "resolved_name": "Isaac",
        "user_id": "U123",
        "vendor_choice": config.VENDOR_OTHER_OPTION,
        "vendor_custom": "Acme Widgets",
        "route": "epif",
    }
    view_epif = blocks.build_stage2_view(meta_epif)
    block_ids_epif = [b["block_id"] for b in view_epif["blocks"]]
    assert "block_payment_method" in block_ids_epif
    pm_block = next(b for b in view_epif["blocks"] if b["block_id"] == "block_payment_method")
    assert pm_block.get("optional") is not True


def test_screen1_validation():
    """Screen 1 validates vendor choice and requires custom name when Other or Suggest is chosen."""
    ack = MagicMock()
    body = {"user": {"id": "U123"}}
    client = MagicMock()

    # 1. Other vendor with blank custom name -> validation error
    view_blank_custom = {
        "state": {
            "values": {
                "block_vendor": {"vendor_select": {"selected_option": {"value": config.VENDOR_OTHER_OPTION}}},
                "block_vendor_custom": {"vendor_custom": {"value": ""}},
            }
        },
        "private_metadata": json.dumps({"resolved_name": "Isaac", "user_id": "U123"}),
    }
    app.handle_stage1_submit(ack, body, client, view_blank_custom)
    ack.assert_called_once()
    assert ack.call_args[1]["response_action"] == "errors"
    assert "block_vendor_custom" in ack.call_args[1]["errors"]

    # 2. Suggest vendor with whitespace custom name -> validation error
    ack.reset_mock()
    view_ws_custom = {
        "state": {
            "values": {
                "block_vendor": {"vendor_select": {"selected_option": {"value": config.VENDOR_SUGGEST_OPTION}}},
                "block_vendor_custom": {"vendor_custom": {"value": "   "}},
            }
        },
        "private_metadata": json.dumps({"resolved_name": "Isaac", "user_id": "U123"}),
    }
    app.handle_stage1_submit(ack, body, client, view_ws_custom)
    ack.assert_called_once()
    assert ack.call_args[1]["response_action"] == "errors"
    assert "block_vendor_custom" in ack.call_args[1]["errors"]

    # 3. Workday vendor without custom name -> updates to stage 2 view
    ack.reset_mock()
    view_valid = {
        "state": {
            "values": {
                "block_vendor": {"vendor_select": {"selected_option": {"value": "Fisher Scientific"}}},
                "block_vendor_custom": {"vendor_custom": {"value": ""}},
            }
        },
        "private_metadata": json.dumps({"resolved_name": "Isaac", "user_id": "U123"}),
    }
    app.handle_stage1_submit(ack, body, client, view_valid)
    ack.assert_called_once()
    assert ack.call_args[1]["response_action"] == "update"
    assert ack.call_args[1]["view"]["callback_id"] == config.STAGE2_CALLBACK_ID


def test_vendor_contact_name_required_on_screen2():
    """Vendor Contact Name must not be marked optional on screen 2."""
    meta = {
        "resolved_name": "Isaac",
        "user_id": "U123",
        "vendor_choice": "Fisher Scientific",
        "vendor_custom": "",
        "route": "workday",
    }
    view = blocks.build_stage2_view(meta)
    name_block = next(b for b in view["blocks"] if b["block_id"] == "block_vendor_contact_name")
    assert name_block.get("optional") is not True


def test_screen2_to_screen3_or_finalize(monkeypatch):
    """Fabrication category advances to screen 3; non-fabrication finalizes immediately."""
    ack = MagicMock()
    body = {"user": {"id": "U123"}}
    client = MagicMock()
    monkeypatch.setattr(config, "ADMIN_ALERT_CHANNEL", "C_ALERTS")

    # 1. Fabrication category -> updates view to Screen 3
    view_fab = {
        "state": {
            "values": {
                "block_item_description": {"item_description": {"value": "Flange Part"}},
                "block_purpose": {"purpose": "Vacuum chamber upgrade"},
                "block_total_price": {"total_price": {"value": "250.00"}},
                "block_vendor_contact_name": {"vendor_contact_name": {"value": "Rep"}},
                "block_vendor_contact_email": {"vendor_contact_email": {"value": "rep@vendor.com"}},
                "block_date_of_purchase": {"date_of_purchase": {"selected_date": "2026-09-14"}},
                "block_delivery_room": {"delivery_room": {"selected_option": {"value": "ERB 212"}}},
                "block_project_id": {"project_id": {"selected_option": {"value": "PG000025831"}}},
                "block_fund": {"fund": {"selected_option": {"value": "133"}}},
                "block_category": {"category": {"selected_option": {"value": "Fabrication Component (4670) > $200"}}},
            }
        },
        "private_metadata": json.dumps({
            "resolved_name": "Isaac",
            "user_id": "U123",
            "vendor_choice": "Fisher Scientific",
            "vendor_custom": "",
            "route": "workday",
        }),
    }
    app.handle_stage2_submit(ack, body, client, view_fab)
    ack.assert_called_once()
    assert ack.call_args[1]["response_action"] == "update"
    assert ack.call_args[1]["view"]["callback_id"] == config.STAGE3_CALLBACK_ID
    client.chat_postMessage.assert_not_called()

    # 2. Non-fabrication category -> finalizes and posts directly
    ack.reset_mock()
    client.reset_mock()
    view_non_fab = {
        "state": {
            "values": {
                "block_item_description": {"item_description": {"value": "Box of Gloves"}},
                "block_purpose": {"purpose": "General lab use"},
                "block_total_price": {"total_price": {"value": "120.00"}},
                "block_vendor_contact_name": {"vendor_contact_name": {"value": "Rep"}},
                "block_vendor_contact_email": {"vendor_contact_email": {"value": "rep@vendor.com"}},
                "block_date_of_purchase": {"date_of_purchase": {"selected_date": "2026-09-14"}},
                "block_delivery_room": {"delivery_room": {"selected_option": {"value": "ERB 212"}}},
                "block_project_id": {"project_id": {"selected_option": {"value": "PG000025831"}}},
                "block_fund": {"fund": {"selected_option": {"value": "133"}}},
                "block_category": {"category": {"selected_option": {"value": "Research/Lab Supplies (3105)"}}},
            }
        },
        "private_metadata": json.dumps({
            "resolved_name": "Isaac",
            "user_id": "U123",
            "vendor_choice": "Fisher Scientific",
            "vendor_custom": "",
            "route": "workday",
        }),
    }
    app.handle_stage2_submit(ack, body, client, view_non_fab)
    ack.assert_called_once_with()
    client.chat_postMessage.assert_called()


def test_screen3_to_finalize(monkeypatch):
    """Submitting Screen 3 finalizes request with asset_id and name_of_system populated."""
    ack = MagicMock()
    body = {"user": {"id": "U123"}}
    client = MagicMock()
    monkeypatch.setattr(config, "ADMIN_ALERT_CHANNEL", "C_ALERTS")

    view_stage3 = {
        "state": {
            "values": {
                "block_asset_id": {"asset_id": {"value": "TAG-44556"}},
                "block_name_of_system": {"name_of_system": {"value": "Target Chamber Alpha"}},
            }
        },
        "private_metadata": json.dumps({
            "resolved_name": "Isaac",
            "user_id": "U123",
            "vendor_choice": "Fisher Scientific",
            "vendor_custom": "",
            "route": "workday",
            "stage2": {
                "item_description": "Beamline Flange",
                "purpose": "Laser line upgrade",
                "total_price": "350.00",
                "vendor_contact_name": "Rep",
                "vendor_contact_email": "rep@vendor.com",
                "date_of_purchase": "2026-09-14",
                "delivery_room": "ERB 212",
                "project_id": "PG000025831",
                "fund": "133",
                "category": "Fabrication Component (4670) > $200",
                "payment_method": "Workday",
            }
        }),
    }

    app.handle_stage3_submit(ack, body, client, view_stage3)
    ack.assert_called_once_with()
    client.chat_postMessage.assert_called()

    # Check that channel post payload contains asset details
    channel_call = next(c for c in client.chat_postMessage.call_args_list if "metadata" in c[1])
    parsed = channel_call[1]["metadata"]["event_payload"]["parsed"]
    assert parsed["asset_id"] == "TAG-44556"
    assert parsed["name_of_system"] == "Target Chamber Alpha"
    assert parsed["payment_method"] == "Workday"
    assert len(parsed) == 20  # 19 keys + date_of_purchase string format in payload


def test_private_metadata_budget():
    """Worst-case metadata with max field lengths stays comfortably under Slack's 3000-char limit."""
    max_desc = "x" * config.MAX_ITEM_DESCRIPTION_LEN
    max_purpose = "y" * config.MAX_PURPOSE_LEN

    worst_case_meta = {
        "resolved_name": "Alexander Longname-Student",
        "user_id": "U0123456789ABCDEF",
        "vendor_choice": config.VENDOR_OTHER_OPTION,
        "vendor_custom": "A Very Long Custom Vendor Name Incorporated LLC",
        "route": "epif",
        "is_pending_name": False,
        "stage2": {
            "item_description": max_desc,
            "purpose": max_purpose,
            "total_price": "999,999.99",
            "vendor_contact_name": "Long Contact Representative Name",
            "vendor_contact_email": "long.contact.representative@verylongcompanydomainname.com",
            "date_of_purchase": "2026-12-31",
            "delivery_room": "Engineering Research Building Room 839",
            "project_id": "PG000025831",
            "fund": "133",
            "category": "Fabrication Component (4670) > $200",
            "payment_method": "P-card",
        },
    }

    view_stage3 = blocks.build_stage3_view(worst_case_meta)
    meta_json = view_stage3["private_metadata"]
    assert len(meta_json) < 3000
    assert len(meta_json) < 2000  # Should even be comfortably under 2000 chars


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

    # FAQ Question about slash vs @p-bot
    say.reset_mock()
    event_faq_slash = {
        "channel_type": "im",
        "user": "U123",
        "channel": "D123",
        "ts": "1234.565",
        "text": "Should I use slash command or @p-bot?",
    }
    app.on_direct_message(event_faq_slash, client, say)
    say.assert_called_once()
    assert "If the action needs a target" in say.call_args[1]["text"]

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
    assert "Hirst Lab Purchasing Bot (P-Bot)" in say.call_args[1]["text"]


def test_every_command_acks_before_client_calls():
    """Assert every slash command handler acks before calling any client method."""
    # 1. /new-purchase
    ack = MagicMock()
    client = MagicMock()
    app.handle_new_purchase_command(ack, {"trigger_id": "trig1", "user_id": "U1"}, client)
    ack.assert_called_once()

    # 2. /purchasing-help
    ack.reset_mock()
    respond = MagicMock()
    app.handle_purchasing_help_command(ack, respond)
    ack.assert_called_once()

    # 3. /blank-template
    ack.reset_mock()
    with patch.object(ops, "handle_template_command") as mock_tmpl:
        app.handle_blank_template_command(ack, {"channel_id": "C1", "user_id": "U1"}, client)
        ack.assert_called_once()
        mock_tmpl.assert_called_once()

    # 4. /roster-list
    ack.reset_mock()
    respond.reset_mock()
    app.handle_roster_list_command(ack, {"channel_id": "C1", "user_id": "U1"}, respond)
    ack.assert_called_once()

    # 5. /roster-set-name
    ack.reset_mock()
    app.handle_roster_set_name_command(ack, {"trigger_id": "trig2", "user_id": "U1", "channel_id": "C1"}, client)
    ack.assert_called_once()


def test_no_slash_command_calls_chat_post_ephemeral():
    """Assert no slash command handler invokes client.chat_postEphemeral (regression guard for T1)."""
    client = MagicMock()
    ack = MagicMock()
    respond = MagicMock()

    # 1. /new-purchase
    app.handle_new_purchase_command(ack, {"trigger_id": "trig", "user_id": "U1"}, client)
    # 2. /purchasing-help
    app.handle_purchasing_help_command(ack, respond)
    # 3. /blank-template
    with patch.object(ops, "handle_template_command"):
        app.handle_blank_template_command(ack, {"channel_id": "C1", "user_id": "U1"}, client)
    # 4. /roster-list
    app.handle_roster_list_command(ack, {"user_id": "U1"}, respond)
    # 5. /roster-set-name
    app.handle_roster_set_name_command(ack, {"trigger_id": "trig", "user_id": "U1", "channel_id": "C1"}, client)

    client.chat_postEphemeral.assert_not_called()


def test_middleware_logging_start_and_completion(caplog):
    """Assert Bolt middleware logs both incoming request and completion with duration."""
    body = {
        "command": "/roster-list",
        "user_id": "UTESTUSER",
        "channel_id": "CTESTCHAN",
    }
    next_called = False

    def fake_next():
        nonlocal next_called
        next_called = True

    with caplog.at_level("INFO"):
        app.log_request(body, fake_next)

    assert next_called is True
    records = [r.message for r in caplog.records]
    assert any("Incoming command [/roster-list] from UTESTUSER in CTESTCHAN" in msg for msg in records)
    assert any("Completed command [/roster-list] from UTESTUSER" in msg for msg in records)


def test_middleware_logging_on_exception(caplog):
    """Assert Bolt middleware logs incoming request, exception, and completion even if handler raises."""
    body = {
        "type": "block_actions",
        "actions": [{"action_id": "req_claim"}],
        "user": {"id": "UERRUSER"},
        "channel": {"id": "CERRCHAN"},
    }

    def failing_next():
        raise RuntimeError("Something blew up in handler")

    with pytest.raises(RuntimeError):
        with caplog.at_level("INFO"):
            app.log_request(body, failing_next)

    records = [r.message for r in caplog.records]
    assert any("Incoming block_actions [req_claim] from UERRUSER in CERRCHAN" in msg for msg in records)
    assert any("Handler raised exception for block_actions [req_claim]" in msg for msg in records)
    assert any("Completed block_actions [req_claim] from UERRUSER" in msg for msg in records)


def test_build_request_blocks_buttons_per_state():
    """Verify build_request_blocks returns 1 button per non-final state and 0 for delivered."""
    sample_req = {
        "item_description": "Resistors",
        "total_price": 45.00,
        "vendor": "DigiKey",
        "payment_method": "P-card",
        "category": "Research/Lab Supplies (3105)",
        "project_id": "PG000025831",
        "fund": "133",
        "delivery_room": "ERB 212",
        "purpose": "Circuit testing",
        "requester": "Isaac",
        "user_id": "U123",
    }

    # posted/approved/claimed get a primary + secondary (Decline or Cancel) button
    two_button_states = {
        "posted": ("req_approve", "req_decline"),
        "approved": ("req_claim", "req_cancel"),
        "claimed": ("req_processed", "req_cancel"),
    }
    for state, (primary_id, secondary_id) in two_button_states.items():
        blocks_list = blocks.build_request_blocks(state, sample_req)
        action_blocks = [b for b in blocks_list if b.get("type") == "actions"]
        assert len(action_blocks) == 1, f"state={state}: expected 1 actions block"
        elements = action_blocks[0].get("elements", [])
        assert len(elements) == 2, f"state={state}: expected 2 buttons (primary + secondary)"
        assert elements[0].get("action_id") == primary_id, f"state={state}: primary button"
        assert elements[1].get("action_id") == secondary_id, f"state={state}: secondary button"

    # processed/confirmed get only the primary button (cancel not allowed after processed)
    one_button_states = {
        "processed": "req_confirmed",
        "confirmed": "req_delivered",
    }
    for state, expected_action in one_button_states.items():
        blocks_list = blocks.build_request_blocks(state, sample_req)
        action_blocks = [b for b in blocks_list if b.get("type") == "actions"]
        assert len(action_blocks) == 1, f"state={state}: expected 1 actions block"
        elements = action_blocks[0].get("elements", [])
        assert len(elements) == 1, f"state={state}: expected 1 button"
        assert elements[0].get("action_id") == expected_action

    # delivered/declined/cancelled -> 0 buttons
    for terminal_state in ("delivered", "declined", "cancelled"):
        blocks_term = blocks.build_request_blocks(terminal_state, sample_req)
        action_blocks_term = [b for b in blocks_term if b.get("type") == "actions"]
        assert len(action_blocks_term) == 0, f"state={terminal_state}: expected no action buttons"


def test_req_approve_non_approver_denial():
    """A req_approve click from a non-approver responds ephemerally, does not process EPIF, does not update message."""
    ack = MagicMock()
    respond = MagicMock()
    client = MagicMock()
    body = {
        "user": {"id": "UNONAPPROVER"},
        "channel": {"id": "C123"},
        "message": {"ts": "1111.22"},
        "container": {"message_ts": "1111.22", "thread_ts": "1111.22"},
        "actions": [{"value": json.dumps({"request": {}, "history": []})}],
    }
    with patch.object(lifecycle, "handle_epif_processing") as mock_epif:
        app.handle_req_approve_action(ack, body, respond, client)
        ack.assert_called_once()
        respond.assert_called_once()
        assert "Only authorized approvers" in respond.call_args[1]["text"]
        mock_epif.assert_not_called()
        client.chat_update.assert_not_called()


def test_req_claim_and_keyword_dispatch_same_args():
    """A req_claim click and an @p-bot claim mention call handle_claim with matching channel and thread_ts."""
    ack = MagicMock()
    respond = MagicMock()
    client = MagicMock()
    say = MagicMock()
    roster.add_requester("UGRADBUYER", "Dylan")
    roster.add_buyer("UGRADBUYER")

    # 1. Button click req_claim
    button_body = {
        "user": {"id": "UGRADBUYER"},
        "channel": {"id": "C_TEST"},
        "message": {"ts": "5555.66"},
        "container": {"message_ts": "5555.66", "thread_ts": "5555.66"},
        "actions": [{"value": json.dumps({"request": {"item_description": "Bolts"}, "history": []})}],
    }
    with patch.object(lifecycle, "handle_claim") as mock_claim:
        app.handle_req_claim_action(ack, button_body, respond, client)
        ack.assert_called_once()
        mock_claim.assert_called_once()
        btn_channel = mock_claim.call_args[1]["channel"]
        btn_thread = mock_claim.call_args[1]["thread_ts"]

    # 2. Keyword mention @p-bot claim
    with patch.object(lifecycle, "handle_claim") as mock_claim_kw:
        app.dispatch_command(
            client=client,
            say=say,
            channel="C_TEST",
            thread_ts="5555.66",
            user="UGRADBUYER",
            event_ts="5555.67",
            text="@p-bot claim",
        )
        mock_claim_kw.assert_called_once()
        kw_channel = mock_claim_kw.call_args[0][2]
        kw_thread = mock_claim_kw.call_args[0][3]

    assert btn_channel == kw_channel == "C_TEST"
    assert btn_thread == kw_thread == "5555.66"


def test_roster_set_name_modal_submission(monkeypatch):
    """Verify /roster-set-name validation, existing member handling, and alert creation."""
    ack = MagicMock()
    client = MagicMock()
    monkeypatch.setattr(config, "ADMIN_ALERT_CHANNEL", "C_ALERTS")

    # 1. Name outside VALID_REQUESTERS -> modal error, no alert
    view_invalid = {
        "state": {"values": {"block_proposed_name": {"proposed_name": {"value": "InvalidNonExistentName"}}}},
        "private_metadata": json.dumps({"user_id": "U_NEW", "channel_id": "C_MAIN"}),
    }
    app.handle_roster_set_name_submit(ack, {"user": {"id": "U_NEW"}}, client, view_invalid)
    ack.assert_called_once()
    assert ack.call_args[1]["response_action"] == "errors"
    client.chat_postMessage.assert_not_called()

    # 2. User already in roster -> responds ephemerally/DM, no alert
    roster.add_requester("U_EXISTING", "Isaac")
    ack.reset_mock()
    client.reset_mock()
    view_existing = {
        "state": {"values": {"block_proposed_name": {"proposed_name": {"value": "Isaac"}}}},
        "private_metadata": json.dumps({"user_id": "U_EXISTING", "channel_id": "C_MAIN"}),
    }
    app.handle_roster_set_name_submit(ack, {"user": {"id": "U_EXISTING"}}, client, view_existing)
    ack.assert_called_once_with()
    client.chat_postMessage.assert_not_called()
    client.chat_postEphemeral.assert_called_once()
    assert "already registered" in client.chat_postEphemeral.call_args[1]["text"]

    # 3. Valid new user -> posts alert to ADMIN_ALERT_CHANNEL with approve_new_requester button
    ack.reset_mock()
    client.reset_mock()
    view_valid_new = {
        "state": {"values": {"block_proposed_name": {"proposed_name": {"value": "Dylan"}}}},
        "private_metadata": json.dumps({"user_id": "U_BRAND_NEW", "channel_id": "C_MAIN"}),
    }
    app.handle_roster_set_name_submit(ack, {"user": {"id": "U_BRAND_NEW"}}, client, view_valid_new)
    ack.assert_called_once_with()
    alert_call = next(c for c in client.chat_postMessage.call_args_list if c[1].get("channel") == "C_ALERTS")
    alert_args = alert_call[1]
    assert alert_args["channel"] == "C_ALERTS"
    actions_block = next(b for b in alert_args["blocks"] if b["type"] == "actions")
    btn = actions_block["elements"][0]
    assert btn["action_id"] == "approve_new_requester"
    val = json.loads(btn["value"])
    assert val["slack_id"] == "U_BRAND_NEW"
    assert val["name"] == "Dylan"


# ==============================================================================
# PHASE 1 FOLLOW-UP TESTS
# ==============================================================================

def test_approver_gate_allowed_for_approvers():
    """Verify Charlie or an approved reviewer from roster passes the gate in dispatch_command."""
    client = MagicMock()
    say = MagicMock()

    # Charlie (hardcoded approver in roster)
    with patch.object(lifecycle, "handle_epif_processing") as mock_epif:
        app.dispatch_command(
            client=client,
            say=say,
            channel="C123",
            thread_ts="1234.56",
            user="U07L2RFEPJ9",
            event_ts="1234.57",
            text="@p-bot approved",
        )
        mock_epif.assert_called_once()

    # Added approver in roster
    roster.add_approver("U_CUSTOM_APPROVER")
    say.reset_mock()
    with patch.object(lifecycle, "handle_epif_processing") as mock_epif:
        app.dispatch_command(
            client=client,
            say=say,
            channel="C123",
            thread_ts="1234.56",
            user="U_CUSTOM_APPROVER",
            event_ts="1234.57",
            text="@p-bot approved",
        )
        mock_epif.assert_called_once()


def test_finalize_purchase_request_without_pdf(monkeypatch):
    """Verify finalize_purchase_request handles modal-derived requests (pdf_bytes=None) cleanly."""
    client = MagicMock()
    say = MagicMock()
    monkeypatch.setattr(config, "ADMIN_ALERT_CHANNEL", "C_ALERTS")

    stage1 = {
        "resolved_name": "Isaac",
        "user_id": "U123",
        "vendor_choice": config.VENDOR_OTHER_OPTION,
        "vendor_custom": "Thorlabs",
        "route": "epif",
    }
    stage2 = {
        "item_description": "Laser Diode 532nm",
        "purpose": "Optical alignment",
        "total_price": "$85.00",
        "vendor_contact_name": "Sales",
        "vendor_contact_email": "sales@thorlabs.com",
        "date_of_purchase": "09/15/26",
        "delivery_room": "ERB 212",
        "project_id": "PG000025831",
        "fund": "133",
        "category": "Research/Lab Supplies (3105)",
        "payment_method": "P-card",
    }
    parsed = interview.build_parsed_from_stages(stage1, stage2, stage3=None)

    with patch.object(lifecycle.log_writer, "save_epif") as mock_save_epif:
        with patch.object(lifecycle.log_writer, "append_row", return_value=17) as mock_append:
            with patch.object(lifecycle.queue_worker, "submit_write_task") as mock_submit:
                lifecycle.finalize_purchase_request(
                    client=client,
                    say=say,
                    channel="C_PURCHASING",
                    thread_ts="1234.56",
                    event_ts="1234.56",
                    parsed=parsed,
                    requester="Isaac",
                    notify_target="U123",
                    pdf_bytes=None,
                    file_name=None,
                )
                mock_submit.assert_called_once()
                # Run the action_fn and verify save_epif was skipped
                action_fn = mock_submit.call_args[1]["action_fn"]
                row_num, saved_path = action_fn()
                assert saved_path is None
                mock_save_epif.assert_not_called()
                mock_append.assert_called_once()

                # Trigger success_callback and verify channel notification
                success_cb = mock_submit.call_args[1]["success_callback"]
                success_cb((row_num, saved_path))
                say.assert_called_once()
                assert "Logged to row 17" in say.call_args[1]["text"]


# ==============================================================================
# PHASE 2 FOLLOW-UP TESTS
# ==============================================================================

def test_approve_new_requester_action_admin_vs_non_admin():
    """Non-admin gets denied; admin adds requester, updates alert message, and DMs user."""
    ack = MagicMock()
    respond = MagicMock()
    client = MagicMock()

    body_non_admin = {
        "user": {"id": "U_NON_ADMIN"},
        "channel": {"id": "C_ALERTS"},
        "message": {"ts": "9999.01"},
        "actions": [{"value": json.dumps({"slack_id": "U_TARGET", "name": "Dylan"})}],
    }

    # 1. Non-admin attempt
    app.handle_approve_new_requester_action(ack, body_non_admin, respond, client)
    ack.assert_called_once()
    respond.assert_called_once()
    assert "Only bot administrators" in respond.call_args[1]["text"]
    assert "U_TARGET" not in roster.get_requesters()

    # 2. Admin attempt
    roster.add_admin("U_ADMIN_ACTOR")
    ack.reset_mock()
    respond.reset_mock()
    body_admin = {
        "user": {"id": "U_ADMIN_ACTOR"},
        "channel": {"id": "C_ALERTS"},
        "message": {"ts": "9999.01"},
        "actions": [{"value": json.dumps({"slack_id": "U_TARGET", "name": "Dylan"})}],
    }
    app.handle_approve_new_requester_action(ack, body_admin, respond, client)
    ack.assert_called_once()
    assert roster.get_requesters().get("U_TARGET") == "Dylan"
    client.chat_update.assert_called_once()
    client.chat_postMessage.assert_called()  # tell() DM to user


def test_approve_new_admin_action_admin_vs_non_admin():
    """Non-admin gets denied; admin promotes user, updates alert message, and DMs target."""
    ack = MagicMock()
    respond = MagicMock()
    client = MagicMock()

    body_non_admin = {
        "user": {"id": "U_NON_ADMIN"},
        "channel": {"id": "C_ALERTS"},
        "message": {"ts": "9999.02"},
        "actions": [{"value": json.dumps({"slack_id": "U_PROMOTEE"})}],
    }

    # Non-admin
    app.handle_approve_new_admin_action(ack, body_non_admin, respond, client)
    assert "U_PROMOTEE" not in roster.get_admins()

    # Admin
    roster.add_admin("U_ADMIN_ACTOR")
    body_admin = {
        "user": {"id": "U_ADMIN_ACTOR"},
        "channel": {"id": "C_ALERTS"},
        "message": {"ts": "9999.02"},
        "actions": [{"value": json.dumps({"slack_id": "U_PROMOTEE"})}],
    }
    app.handle_approve_new_admin_action(ack, body_admin, respond, client)
    assert "U_PROMOTEE" in roster.get_admins()
    client.chat_update.assert_called_once()


def test_approve_new_vendor_action_admin_vs_non_admin():
    """Non-admin gets denied; admin adds vendor and updates alert message."""
    ack = MagicMock()
    respond = MagicMock()
    client = MagicMock()

    body_non_admin = {
        "user": {"id": "U_NON_ADMIN"},
        "channel": {"id": "C_ALERTS"},
        "message": {"ts": "9999.03"},
        "actions": [{"value": json.dumps({"vendor": "Acme Laser Labs"})}],
    }

    # Non-admin
    app.handle_approve_new_vendor_action(ack, body_non_admin, respond, client)
    assert "Acme Laser Labs" not in roster.get_vendors()

    # Admin
    roster.add_admin("U_ADMIN_ACTOR")
    body_admin = {
        "user": {"id": "U_ADMIN_ACTOR"},
        "channel": {"id": "C_ALERTS"},
        "message": {"ts": "9999.03"},
        "actions": [{"value": json.dumps({"vendor": "Acme Laser Labs"})}],
    }
    app.handle_approve_new_vendor_action(ack, body_admin, respond, client)
    assert "Acme Laser Labs" in roster.get_vendors()
    client.chat_update.assert_called_once()


def test_remove_vendor_close_matches():
    """When a vendor is not found, list close/partial matches rather than crashing or silent no-op."""
    client = MagicMock()
    say = MagicMock()
    roster.add_admin("U_ADMIN_ACTOR")
    roster.add_vendor("Fisher Scientific")

    # Non-existent vendor with partial match
    app.dispatch_command(client, say, "C123", "ts", "U_ADMIN_ACTOR", "ts", "@p-bot remove vendor Fisher")
    say.assert_called_once()
    msg = say.call_args[1]["text"]
    assert "not found" in msg
    assert "Fisher Scientific" in msg


# ==============================================================================
# PHASE 3 FOLLOW-UP TESTS
# ==============================================================================

def test_template_command_single_file_missing(tmp_path, monkeypatch):
    """Clear error message if only one template file is missing."""
    client = MagicMock()
    say = MagicMock()
    fake_temp_dir = str(tmp_path / "templates_partial")
    os.makedirs(fake_temp_dir, exist_ok=True)
    monkeypatch.setattr(config, "TEMPLATE_DIR", fake_temp_dir)

    # Only PDF exists, README missing
    with open(os.path.join(fake_temp_dir, "EPIF_TEMPLATE_HIRST.pdf"), "w") as f:
        f.write("pdf")

    ops.handle_template_command(client, say, "C123", "ts", "U123")
    assert "Template files missing" in say.call_args[1]["text"]
    assert "README.md" in say.call_args[1]["text"]


# ==============================================================================
# PHASE 4 FOLLOW-UP TESTS
# ==============================================================================

def test_screen1_unresolved_user_shows_name_input():
    """Screen 1 shows name input only when prefill_name_field is True."""
    # 1. Known user
    view_known = blocks.build_stage1_view(prefill_name_field=False, resolved_name="Isaac", user_id="U123")
    assert "block_proposed_name" not in [b.get("block_id") for b in view_known["blocks"]]

    # 2. Unresolved user
    view_unknown = blocks.build_stage1_view(prefill_name_field=True, resolved_name=None, user_id="UUNKNOWN")
    assert "block_proposed_name" in [b.get("block_id") for b in view_unknown["blocks"]]


def test_screen2_validation_errors():
    """Screen 2 returns response_action: 'errors' when invalid money is entered."""
    ack = MagicMock()
    body = {"user": {"id": "U123"}}
    client = MagicMock()

    view_invalid_price = {
        "state": {
            "values": {
                "block_item_description": {"item_description": {"value": "Box of Gloves"}},
                "block_purpose": {"purpose": "General lab use"},
                "block_total_price": {"total_price": {"value": "NOT_A_PRICE"}},
                "block_vendor_contact_name": {"vendor_contact_name": {"value": "Rep"}},
                "block_vendor_contact_email": {"vendor_contact_email": {"value": "rep@vendor.com"}},
                "block_date_of_purchase": {"date_of_purchase": {"selected_date": "2026-09-14"}},
                "block_delivery_room": {"delivery_room": {"selected_option": {"value": "ERB 212"}}},
                "block_project_id": {"project_id": {"selected_option": {"value": "PG000025831"}}},
                "block_fund": {"fund": {"selected_option": {"value": "133"}}},
                "block_category": {"category": {"selected_option": {"value": "Research/Lab Supplies (3105)"}}},
            }
        },
        "private_metadata": json.dumps({
            "resolved_name": "Isaac",
            "user_id": "U123",
            "vendor_choice": "Fisher Scientific",
            "vendor_custom": "",
            "route": "workday",
        }),
    }
    app.handle_stage2_submit(ack, body, client, view_invalid_price)
    ack.assert_called_once()
    assert ack.call_args[1]["response_action"] == "errors"


# ==============================================================================
# PHASE 5 FOLLOW-UP TESTS
# ==============================================================================

def test_roster_list_output_admin_vs_non_admin():
    """Non-admin sees members and vendors, but approvers/admins/buyers are hidden; admin sees all."""
    ack = MagicMock()
    respond = MagicMock()

    roster.add_requester("U_REQ1", "Isaac")
    roster.add_admin("U_ADMIN1")
    roster.add_approver("U07L2RFEPJ9")
    roster.add_buyer("U_BUYER1")

    # 1. Non-admin
    app.handle_roster_list_command(ack, {"user_id": "U_REQ1"}, respond)
    non_admin_text = respond.call_args[1]["text"]
    assert "Lab Members" in non_admin_text
    assert "Workday Punchout Vendors" in non_admin_text
    assert "Administrators" not in non_admin_text
    assert "Authorized Approvers" not in non_admin_text
    assert "Purchase Buyers" not in non_admin_text

    # 2. Admin
    respond.reset_mock()
    app.handle_roster_list_command(ack, {"user_id": "U_ADMIN1"}, respond)
    admin_text = respond.call_args[1]["text"]
    assert "Administrators" in admin_text
    assert "Purchase Approvers" in admin_text
    assert "Purchase Buyers" in admin_text
    assert "<@U_BUYER1>" in admin_text


def test_roster_list_empty_requesters_prompt(monkeypatch, tmp_path):
    """When requesters is empty, /roster-list points user to /roster-set-name."""
    ack = MagicMock()
    respond = MagicMock()

    # Empty roster
    test_empty_roster = str(tmp_path / "empty_roster.json")
    with open(test_empty_roster, "w") as f:
        json.dump({"requesters": {}, "admins": [], "approvers": [], "vendors": []}, f)
    monkeypatch.setattr(roster, "ROSTER_PATH", test_empty_roster)

    app.handle_roster_list_command(ack, {"user_id": "U123"}, respond)
    msg = respond.call_args[1]["text"]
    assert "No members registered yet" in msg
    assert "/roster-set-name" in msg


def test_all_lifecycle_buttons_state_machine(monkeypatch):
    """Test full sequential lifecycle: posted -> approved -> claimed -> processed -> confirmed -> delivered."""
    ack = MagicMock()
    respond = MagicMock()
    client = MagicMock()
    roster.add_requester("U_CHARLIE", "Charlie H.")
    roster.add_approver("U_CHARLIE")
    roster.add_requester("U_BUYER", "Dylan")
    roster.add_buyer("U_BUYER")

    base_req = {
        "item_description": "Microcontroller Board",
        "total_price": 25.00,
        "vendor": "DigiKey",
        "payment_method": "P-card",
        "category": "Research/Lab Supplies (3105)",
        "project_id": "PG000025831",
        "fund": "133",
        "delivery_room": "ERB 212",
        "purpose": "Sensor readout",
        "requester": "Isaac",
    }

    # 1. Approve (by Charlie)
    body_approve = {
        "user": {"id": "U_CHARLIE"},
        "channel": {"id": "C_PURCHASE"},
        "message": {"ts": "100.00"},
        "container": {"message_ts": "100.00", "thread_ts": "100.00"},
        "actions": [{"value": json.dumps({"request": base_req, "history": []})}],
    }
    with patch.object(lifecycle, "handle_epif_processing"):
        app.handle_req_approve_action(ack, body_approve, respond, client)
        update_call = client.chat_update.call_args[1]
        blocks_res = update_call["blocks"]
        # Next button must be req_claim
        actions = next(b for b in blocks_res if b.get("type") == "actions")
        assert actions["elements"][0]["action_id"] == "req_claim"

    # 2. Claim (by Dylan)
    ack.reset_mock()
    client.reset_mock()
    body_claim = {
        "user": {"id": "U_BUYER"},
        "channel": {"id": "C_PURCHASE"},
        "message": {"ts": "100.00"},
        "container": {"message_ts": "100.00", "thread_ts": "100.00"},
        "actions": [{"value": actions["elements"][0]["value"]}],
    }
    with patch.object(lifecycle, "handle_claim"):
        app.handle_req_claim_action(ack, body_claim, respond, client)
        update_call = client.chat_update.call_args[1]
        blocks_res = update_call["blocks"]
        actions = next(b for b in blocks_res if b.get("type") == "actions")
        assert actions["elements"][0]["action_id"] == "req_processed"

    # 3. Processed (by Dylan)
    ack.reset_mock()
    client.reset_mock()
    body_sub = {
        "user": {"id": "U_BUYER"},
        "channel": {"id": "C_PURCHASE"},
        "message": {"ts": "100.00"},
        "container": {"message_ts": "100.00", "thread_ts": "100.00"},
        "actions": [{"value": actions["elements"][0]["value"]}],
    }
    with patch.object(lifecycle, "handle_processed"):
        app.handle_req_processed_action(ack, body_sub, respond, client)
        update_call = client.chat_update.call_args[1]
        blocks_res = update_call["blocks"]
        actions = next(b for b in blocks_res if b.get("type") == "actions")
        assert actions["elements"][0]["action_id"] == "req_confirmed"

    # 4. Confirmed (by Dylan)
    ack.reset_mock()
    client.reset_mock()
    body_conf = {
        "user": {"id": "U_BUYER"},
        "channel": {"id": "C_PURCHASE"},
        "message": {"ts": "100.00"},
        "container": {"message_ts": "100.00", "thread_ts": "100.00"},
        "actions": [{"value": actions["elements"][0]["value"]}],
    }
    with patch.object(lifecycle, "handle_confirmation"):
        app.handle_req_confirmed_action(ack, body_conf, respond, client)
        update_call = client.chat_update.call_args[1]
        blocks_res = update_call["blocks"]
        actions = next(b for b in blocks_res if b.get("type") == "actions")
        assert actions["elements"][0]["action_id"] == "req_delivered"

    # 5. Delivered (by Dylan)
    ack.reset_mock()
    client.reset_mock()
    body_deliv = {
        "user": {"id": "U_BUYER"},
        "channel": {"id": "C_PURCHASE"},
        "message": {"ts": "100.00"},
        "container": {"message_ts": "100.00", "thread_ts": "100.00"},
        "actions": [{"value": actions["elements"][0]["value"]}],
    }
    with patch.object(lifecycle, "handle_delivery"):
        app.handle_req_delivered_action(ack, body_deliv, respond, client)
        update_call = client.chat_update.call_args[1]
        blocks_res = update_call["blocks"]
        # No more action buttons on delivered
        assert not any(b.get("type") == "actions" for b in blocks_res)


# ==============================================================================
# BUYER ROSTER & ADMIN COMMAND TESTS (TICKET 02)
# ==============================================================================

def test_add_buyer_non_admin_refused(monkeypatch, tmp_path):
    """A non-admin user running add-buyer is refused and nothing is written."""
    client = MagicMock()
    say = MagicMock()
    roster.add_requester("U_NONADMIN", "Casey")
    assert not admin.is_admin_user("U_NONADMIN")

    from src import ops
    ops.handle_add_buyer(client, say, channel="C_OPS", thread_ts="111.22", user_id="U_NONADMIN", text="@p-bot add-buyer <@U_TARGET>")

    say.assert_called_once()
    assert "restricted to bot administrators" in say.call_args[1]["text"]
    assert not roster.is_buyer("U_TARGET")


def test_add_buyer_admin_warns_no_requester_entry(monkeypatch, tmp_path):
    """Admin adding a buyer who has no requesters entry adds them and surfaces warning to admin in Slack."""
    client = MagicMock()
    say = MagicMock()
    roster.add_admin("U_ADMIN")
    assert admin.is_admin_user("U_ADMIN")

    # U_NEWBUYER has no requester mapping
    requesters = roster.get_requesters()
    assert "U_NEWBUYER" not in requesters

    from src import ops
    ops.handle_add_buyer(client, say, channel="C_OPS", thread_ts="111.22", user_id="U_ADMIN", text="@p-bot add-buyer <@U_NEWBUYER>")

    say.assert_called_once()
    reply = say.call_args[1]["text"]
    # Buyer was added
    assert roster.is_buyer("U_NEWBUYER")
    assert "added to purchase buyers" in reply
    # Warning naming user and telling admin to run /roster-set-name
    assert "<@U_NEWBUYER>" in reply
    assert "/roster-set-name" in reply


def test_add_buyer_admin_no_warning_when_in_requesters(monkeypatch, tmp_path):
    """Admin adding a buyer who already has a requester mapping succeeds without warning."""
    client = MagicMock()
    say = MagicMock()
    roster.add_admin("U_ADMIN")
    roster.add_requester("U_MAPPEDBUYER", "Dylan")

    from src import ops
    ops.handle_add_buyer(client, say, channel="C_OPS", thread_ts="111.22", user_id="U_ADMIN", text="@p-bot add-buyer <@U_MAPPEDBUYER>")

    say.assert_called_once()
    reply = say.call_args[1]["text"]
    assert roster.is_buyer("U_MAPPEDBUYER")
    assert "added to purchase buyers" in reply
    assert "/roster-set-name" not in reply


def test_remove_buyer_admin_vs_non_admin(monkeypatch, tmp_path):
    """Admin can remove buyer; non-admin is refused."""
    client = MagicMock()
    say = MagicMock()
    roster.add_admin("U_ADMIN")
    roster.add_requester("U_NONADMIN", "Casey")
    roster.add_buyer("U_TARGETBUYER")
    assert roster.is_buyer("U_TARGETBUYER")

    from src import ops

    # Non-admin attempt
    ops.handle_remove_buyer(client, say, channel="C_OPS", thread_ts="111.22", user_id="U_NONADMIN", text="@p-bot remove-buyer <@U_TARGETBUYER>")
    assert "restricted to bot administrators" in say.call_args[1]["text"]
    assert roster.is_buyer("U_TARGETBUYER")

    # Admin attempt
    say.reset_mock()
    ops.handle_remove_buyer(client, say, channel="C_OPS", thread_ts="111.22", user_id="U_ADMIN", text="@p-bot remove-buyer <@U_TARGETBUYER>")
    assert "removed from purchase buyers" in say.call_args[1]["text"]
    assert not roster.is_buyer("U_TARGETBUYER")


def test_dispatch_command_add_and_remove_buyer(monkeypatch):
    """dispatch_command routes add-buyer and remove-buyer to ops handlers."""
    client = MagicMock()
    say = MagicMock()
    roster.add_admin("U_ADMIN")

    # Test dispatch add-buyer
    app.dispatch_command(client, say, channel="C1", thread_ts="T1", user="U_ADMIN", event_ts="E1", text="@p-bot add-buyer <@U_NEW>")
    assert roster.is_buyer("U_NEW")

    # Test dispatch remove-buyer
    say.reset_mock()
    app.dispatch_command(client, say, channel="C1", thread_ts="T1", user="U_ADMIN", event_ts="E1", text="@p-bot remove-buyer <@U_NEW>")
    assert not roster.is_buyer("U_NEW")


# ==============================================================================
# TICKET 03: EVERY APPROVED REQUEST WAITS FOR A CLAIM
# ==============================================================================

def test_approved_request_from_buyer_broadcasts_and_sends_no_dm(monkeypatch):
    """An approved request from a buyer still broadcasts for claim and sends NO email-draft DM."""
    client = MagicMock()
    say = MagicMock()
    roster.add_requester("U_BUYER_REQ", "Isaac")
    roster.add_buyer("U_BUYER_REQ")
    roster.add_buyer("U_OTHER_BUYER")

    stage1 = {
        "resolved_name": "Isaac",
        "user_id": "U_BUYER_REQ",
        "vendor_choice": config.VENDOR_OTHER_OPTION,
        "vendor_custom": "Thorlabs",
        "route": "epif",
    }
    stage2 = {
        "item_description": "Laser Optics Mount",
        "purpose": "Optical alignment",
        "total_price": "$149.99",
        "vendor_contact_name": "Sales",
        "vendor_contact_email": "sales@thorlabs.com",
        "date_of_purchase": "09/15/26",
        "delivery_room": "ERB 212",
        "project_id": "PG000025831",
        "fund": "133",
        "category": "Research/Lab Supplies (3105)",
        "payment_method": "P-card",
    }
    parsed = interview.build_parsed_from_stages(stage1, stage2, stage3=None)

    with patch.object(lifecycle.log_writer, "save_epif", return_value="/lab/EPIFs/epif.pdf"):
        with patch.object(lifecycle.log_writer, "append_row", return_value=18):
            with patch.object(lifecycle.queue_worker, "submit_write_task") as mock_submit:
                lifecycle.finalize_purchase_request(
                    client=client,
                    say=say,
                    channel="C_PURCHASE",
                    thread_ts="100.00",
                    event_ts="100.00",
                    parsed=parsed,
                    requester="Isaac",
                    notify_target="U_BUYER_REQ",
                    pdf_bytes=b"fake-pdf",
                    file_name="epif.pdf",
                )
                success_cb = mock_submit.call_args[1]["success_callback"]
                success_cb((18, "/lab/EPIFs/epif.pdf"))

    say.assert_called_once()
    broadcast_text = say.call_args[1]["text"]
    assert "Logged to row 18" in broadcast_text
    assert "Laser Optics Mount" in broadcast_text
    assert "$149.99" in broadcast_text
    assert "Thorlabs" in broadcast_text
    assert "Research/Lab Supplies (3105)" in broadcast_text
    assert "Saved EPIF to `/lab/EPIFs/epif.pdf`" in broadcast_text
    assert "Needs a Grad Student Buyer to process in Workday / ShopUW." in broadcast_text
    assert "<@U_BUYER_REQ>" in broadcast_text
    assert "<@U_OTHER_BUYER>" in broadcast_text

    # Assert NO DM was sent at approval time (client.chat_postMessage never called for DM)
    dm_calls = [
        call for call in client.chat_postMessage.call_args_list
        if call[1].get("channel") == "U_BUYER_REQ"
    ]
    assert len(dm_calls) == 0, f"Expected no DM to be sent at approval time, but got: {dm_calls}"


def test_req_claim_click_from_non_buyer():
    """A non-buyer clicking req_claim gets ephemeral denial, no handle_claim call, no chat_update, no DM."""
    ack = MagicMock()
    respond = MagicMock()
    client = MagicMock()
    roster.add_requester("U_NONBUYER", "Alice")
    # Note: U_NONBUYER is not added to buyers

    button_body = {
        "user": {"id": "U_NONBUYER"},
        "channel": {"id": "C_PURCHASE"},
        "message": {"ts": "100.00", "thread_ts": "100.00"},
        "actions": [{"value": json.dumps({"request": {"item_description": "Filters"}, "history": []})}],
    }

    with patch.object(lifecycle, "handle_claim") as mock_claim:
        app.handle_req_claim_action(ack, button_body, respond, client)
        ack.assert_called_once()
        respond.assert_called_once()
        deny_text = respond.call_args[1]["text"]
        assert "Only purchase buyers can claim" in deny_text or "designated buyers" in deny_text
        mock_claim.assert_not_called()
        client.chat_update.assert_not_called()
        client.chat_postMessage.assert_not_called()


def test_req_claim_click_unregistered_user_runs_after_buyer_gate():
    """A buyer who has not set their name in the roster gets the roster registration prompt."""
    ack = MagicMock()
    respond = MagicMock()
    client = MagicMock()
    roster.add_buyer("U_UNREG_BUYER")
    # Note: U_UNREG_BUYER is in buyers, but NOT in requesters

    button_body = {
        "user": {"id": "U_UNREG_BUYER"},
        "channel": {"id": "C_PURCHASE"},
        "message": {"ts": "100.00", "thread_ts": "100.00"},
        "actions": [{"value": json.dumps({"request": {"item_description": "Filters"}, "history": []})}],
    }

    with patch.object(lifecycle, "handle_claim") as mock_claim:
        with patch.object(lifecycle.slack_io, "resolve_requester", return_value=None):
            app.handle_req_claim_action(ack, button_body, respond, client)
            ack.assert_called_once()
            respond.assert_called_once()
            assert "registered in the lab roster" in respond.call_args[1]["text"]
            mock_claim.assert_not_called()


def test_at_pbot_claim_mention_from_non_buyer():
    """An @p-bot claim mention from a non-buyer is denied and does not call handle_claim."""
    client = MagicMock()
    say = MagicMock()
    roster.add_requester("U_NONBUYER", "Alice")

    with patch.object(lifecycle, "handle_claim") as mock_claim:
        app.dispatch_command(
            client=client,
            say=say,
            channel="C_PURCHASE",
            thread_ts="100.00",
            user="U_NONBUYER",
            event_ts="100.01",
            text="@p-bot claim",
        )
        say.assert_called_once()
        deny_text = say.call_args[1]["text"]
        assert "Only purchase buyers can claim" in deny_text or "designated buyers" in deny_text
        mock_claim.assert_not_called()


def test_claim_as_different_user_than_requester():
    """Claiming as a different user than requester sends the email draft to the claimer, signed by claimer."""
    client = MagicMock()
    say = MagicMock()
    roster.add_requester("U_CLAIMER", "Dylan")
    roster.add_buyer("U_CLAIMER")

    req_data = {
        "item_description": "Spectrometer Grating",
        "total_price": 520.00,
        "vendor": "Thorlabs",
        "project_id": "PG000025831",
        "fund": "133",
        "requester": "Alice",
    }

    with patch.object(lifecycle.slack_io, "find_row_in_thread", return_value=22):
        with patch.object(lifecycle.log_writer, "get_row_info", return_value=req_data):
            lifecycle.handle_claim(
                client=client,
                say=say,
                channel="C_PURCHASE",
                thread_ts="100.00",
                user_id="U_CLAIMER",
                event_ts="100.02",
                req_data=req_data,
            )

    say.assert_called_once()
    assert "✋ <@U_CLAIMER> (Dylan) has claimed order for *Spectrometer Grating* (Row 22)!" in say.call_args[1]["text"]

    # Assert DM was sent to the claimer (U_CLAIMER)
    dm_calls = [
        call for call in client.chat_postMessage.call_args_list
        if call[1].get("channel") == "U_CLAIMER"
    ]
    assert len(dm_calls) == 1, f"Expected 1 DM to claimer U_CLAIMER, got {len(dm_calls)}"
    dm_text = dm_calls[0][1]["text"]
    assert "Dylan" in dm_text
    assert "All the best,\nDylan" in dm_text
    assert "All the best,\nAlice" not in dm_text
    assert "Spectrometer Grating" in dm_text


def test_claim_draft_fields_fallback_to_get_row_info():
    """When req_data is None, handle_claim reads fields from log_writer.get_row_info(row)."""
    client = MagicMock()
    say = MagicMock()
    roster.add_requester("U_CLAIMER2", "Finn")
    roster.add_buyer("U_CLAIMER2")

    row_info = {
        "row": 25,
        "item_description": "Cryogenic Valve",
        "total_price": 350.00,
        "vendor": "Swagelok",
        "project_id": "PG000025831",
        "fund": "133",
        "requester": "Charlie",
    }

    with patch.object(lifecycle.slack_io, "find_row_in_thread", return_value=25):
        with patch.object(lifecycle.log_writer, "get_row_info", return_value=row_info):
            lifecycle.handle_claim(
                client=client,
                say=say,
                channel="C_PURCHASE",
                thread_ts="200.00",
                user_id="U_CLAIMER2",
                event_ts="200.02",
                req_data=None,
            )

    dm_calls = [
        call for call in client.chat_postMessage.call_args_list
        if call[1].get("channel") == "U_CLAIMER2"
    ]
    assert len(dm_calls) == 1
    dm_text = dm_calls[0][1]["text"]
    assert "Finn" in dm_text
    assert "All the best,\nFinn" in dm_text
    assert "Cryogenic Valve" in dm_text
    assert "Swagelok" in dm_text


# --- Ticket 04: Buttons on the PDF-drop path ----------------------------------

def test_pdf_drop_in_thread_produces_posted_card_with_approve_button():
    """An EPIF PDF dropped in a channel thread produces a bot post carrying a req_approve button."""
    from datetime import date
    client = MagicMock()
    say = MagicMock()
    roster.add_requester("U_POSTER", "Isaac")

    fake_file = {
        "id": "F_EPIF_123",
        "name": "Prusa_EPIF.pdf",
        "url_private": "https://slack.com/files/epif.pdf",
    }
    event = {
        "type": "message",
        "subtype": "file_share",
        "channel": "C_PURCHASING",
        "channel_type": "channel",
        "user": "U_POSTER",
        "ts": "100.50",
        "thread_ts": "100.00",
        "files": [fake_file],
    }

    parsed_sample = {
        "item_description": "Prusa CORE One L+ INDX 4-Tool",
        "total_price": 2799.0,
        "vendor": "Prusa",
        "vendor_contact_email": "info@prusa3d.com",
        "date_of_purchase": date(2026, 9, 3),
        "project_id": "PG000025831",
        "fund": "150",
        "delivery_room": "ERB 212",
        "purpose": "3D printing parts",
        "category": "Research/Lab Supplies (3105)",
        "payment_method": "P-card",
    }

    with patch.object(lifecycle.slack_io, "download", return_value=b"%PDF-fake"):
        with patch.object(lifecycle.epif_parser, "parse_epif", return_value=parsed_sample):
            app.on_direct_message(event, client, say)

    client.chat_postMessage.assert_called_once()
    call_kw = client.chat_postMessage.call_args[1]
    assert call_kw["channel"] == "C_PURCHASING"
    assert call_kw["thread_ts"] == "100.00"
    assert "🛒 *New Purchase Request from Isaac:*" in call_kw["text"]
    assert "Use the buttons below to approve and track this request." in call_kw["text"]

    # Verify metadata and payload shape
    meta = call_kw["metadata"]
    assert meta["event_type"] == "purchase_request"
    payload = meta["event_payload"]
    assert payload["requester"] == "Isaac"
    assert payload["user_id"] == "U_POSTER"
    assert payload["parsed"]["item_description"] == "Prusa CORE One L+ INDX 4-Tool"
    assert payload["parsed"]["date_of_purchase"] == "2026-09-03"

    # Verify blocks have req_approve button
    blocks_posted = call_kw["blocks"]
    action_block = next(b for b in blocks_posted if b.get("type") == "actions")
    approve_btn = action_block["elements"][0]
    assert approve_btn["action_id"] == "req_approve"
    assert approve_btn["text"]["text"] == "Approve"


def test_pdf_drop_payload_built_where_pdf_parsed():
    """The PDF path's request payload is built where the PDF is parsed, and build_request_blocks is unchanged."""
    from datetime import date
    client = MagicMock()
    say = MagicMock()
    roster.add_requester("U_POSTER", "Dylan")

    fake_file = {
        "name": "EPIF.pdf",
        "url_private": "https://slack.com/files/epif.pdf",
    }
    parsed_sample = {
        "item_description": "Laser Diode",
        "total_price": 500.0,
        "vendor": "Thorlabs",
        "payment_method": "Req/PO",
        "category": "Research/Lab Supplies (3105)",
        "project_id": "PG000025831",
        "fund": "133",
        "delivery_room": "ERB 212",
        "purpose": "Optical setup",
        "date_of_purchase": date(2026, 9, 10),
    }

    with patch.object(lifecycle.slack_io, "download", return_value=b"%PDF-fake"):
        with patch.object(lifecycle.epif_parser, "parse_epif", return_value=parsed_sample):
            lifecycle.handle_epif_drop(
                client=client,
                say=say,
                channel="C_TEST",
                thread_ts="200.00",
                user_id="U_POSTER",
                file_obj=fake_file,
                event_ts="200.00",
            )

    client.chat_postMessage.assert_called_once()
    payload = client.chat_postMessage.call_args[1]["metadata"]["event_payload"]
    assert payload["requester"] == "Dylan"
    assert payload["user_id"] == "U_POSTER"
    assert payload["is_pending_name"] is False
    assert payload["thread_ts"] == "200.00"
    assert payload["parsed"]["item_description"] == "Laser Diode"
    assert payload["parsed"]["payment_method"] == "Req/PO"

    # Ensure build_request_blocks is called with standard signature and produces valid blocks
    direct_blocks = blocks.build_request_blocks("posted", payload)
    action_elem = next(b for b in direct_blocks if b.get("type") == "actions")["elements"][0]
    assert action_elem["action_id"] == "req_approve"


def test_pdf_request_approve_button_click_by_approver():
    """Clicking Approve as an approver on a PDF request writes the row, rewrites message with history & Claim button."""
    ack = MagicMock()
    respond = MagicMock()
    client = MagicMock()
    roster.add_requester("U_CHARLIE", "Charlie H.")
    roster.add_approver("U_CHARLIE")
    roster.add_requester("U_REQ", "Isaac")

    req_payload = {
        "parsed": {
            "item_description": "Oscilloscope",
            "total_price": 1200.00,
            "vendor": "Keysight",
            "payment_method": "P-card",
            "category": "Research/Lab Supplies (3105)",
            "project_id": "PG000025831",
            "fund": "133",
            "delivery_room": "ERB 212",
            "purpose": "Signal analysis",
            "date_of_purchase": "2026-09-01",
        },
        "requester": "Isaac",
        "user_id": "U_REQ",
        "is_pending_name": False,
        "thread_ts": "300.00",
    }

    body = {
        "user": {"id": "U_CHARLIE"},
        "channel": {"id": "C_PURCHASE"},
        "message": {"ts": "300.05"},
        "container": {"message_ts": "300.05", "thread_ts": "300.00"},
        "actions": [{
            "action_id": "req_approve",
            "value": json.dumps({"state": "posted", "requester": "Isaac", "thread_ts": "300.00", "request": req_payload, "history": []}),
        }],
    }

    with patch.object(lifecycle, "handle_epif_processing") as mock_epif:
        app.handle_req_approve_action(ack, body, respond, client)
        ack.assert_called_once()
        mock_epif.assert_called_once()
        assert mock_epif.call_args[1]["channel"] == "C_PURCHASE"
        assert mock_epif.call_args[1]["thread_ts"] == "300.00"
        assert mock_epif.call_args[1]["approver"] == "U_CHARLIE"

        # Chat update called to rewrite message to 'approved'
        client.chat_update.assert_called_once()
        update_kw = client.chat_update.call_args[1]
        assert update_kw["channel"] == "C_PURCHASE"
        assert update_kw["ts"] == "300.05"
        actions = next(b for b in update_kw["blocks"] if b.get("type") == "actions")
        assert actions["elements"][0]["action_id"] == "req_claim"

        # Context history line
        context = next(b for b in update_kw["blocks"] if b.get("type") == "context")
        assert "Approved by Charlie H. on" in context["elements"][0]["text"]


def test_pdf_request_approve_button_click_by_non_approver_denial():
    """Clicking Approve as a non-approver gets an ephemeral denial, message is unchanged, nothing written."""
    ack = MagicMock()
    respond = MagicMock()
    client = MagicMock()
    roster.add_requester("U_STUDENT", "Student")

    body = {
        "user": {"id": "U_STUDENT"},
        "channel": {"id": "C_PURCHASE"},
        "message": {"ts": "300.05"},
        "container": {"message_ts": "300.05", "thread_ts": "300.00"},
        "actions": [{
            "action_id": "req_approve",
            "value": json.dumps({"state": "posted", "requester": "Isaac", "thread_ts": "300.00", "request": {}, "history": []}),
        }],
    }

    with patch.object(lifecycle, "handle_epif_processing") as mock_epif:
        app.handle_req_approve_action(ack, body, respond, client)
        ack.assert_called_once()
        respond.assert_called_once()
        assert "Only authorized approvers" in respond.call_args[1]["text"]
        mock_epif.assert_not_called()
        client.chat_update.assert_not_called()


def test_pdf_request_at_pbot_approved_keyword_still_works():
    """@p-bot approved on a PDF request still works via dispatch_command."""
    client = MagicMock()
    say = MagicMock()
    roster.add_requester("U_CHARLIE", "Charlie H.")
    roster.add_approver("U_CHARLIE")

    with patch.object(lifecycle, "handle_epif_processing") as mock_epif:
        app.dispatch_command(
            client=client,
            say=say,
            channel="C_PURCHASE",
            thread_ts="400.00",
            user="U_CHARLIE",
            event_ts="400.05",
            text="@p-bot approved",
        )
        args, kwargs = mock_epif.call_args
        assert (kwargs.get("channel") or args[2]) == "C_PURCHASE"
        assert (kwargs.get("thread_ts") or args[3]) == "400.00"
        assert (kwargs.get("approver") or args[4]) == "U_CHARLIE"


def test_pdf_request_no_duplicate_lifecycle_logic():
    """No lifecycle logic is duplicated: req_approve calls handle_epif_processing."""
    ack = MagicMock()
    respond = MagicMock()
    client = MagicMock()
    roster.add_requester("U_CHARLIE", "Charlie H.")
    roster.add_approver("U_CHARLIE")

    body = {
        "user": {"id": "U_CHARLIE"},
        "channel": {"id": "C_PURCHASE"},
        "message": {"ts": "500.05"},
        "container": {"message_ts": "500.05", "thread_ts": "500.00"},
        "actions": [{
            "action_id": "req_approve",
            "value": json.dumps({"state": "posted", "requester": "Isaac", "thread_ts": "500.00", "request": {}, "history": []}),
        }],
    }

    with patch.object(lifecycle, "handle_epif_processing") as mock_epif:
        app.handle_req_approve_action(ack, body, respond, client)
        mock_epif.assert_called_once()


def test_pdf_request_walks_from_posted_to_delivered_with_excel_writes(monkeypatch):
    """Walk a PDF request from posted to delivered through buttons and assert matching Excel writes."""
    from datetime import date

    # Synchronously execute write tasks
    def sync_submit(action_fn, channel, thread_ts, user_id, task_type, description, success_callback, failure_callback, client=None):
        res = action_fn()
        success_callback(res)

    monkeypatch.setattr(lifecycle.queue_worker, "submit_write_task", sync_submit)

    ack = MagicMock()
    respond = MagicMock()
    client = MagicMock()
    say = MagicMock()

    # Dynamic in-thread replies tracking
    thread_messages = []

    def mock_chat_postMessage(channel, text, thread_ts=None, **kw):
        msg = {"channel": channel, "text": text, "ts": "100.99", "thread_ts": thread_ts, **kw}
        thread_messages.append(msg)
        return {"ok": True, "ts": "100.99"}

    client.chat_postMessage = mock_chat_postMessage
    client.conversations_replies.side_effect = lambda channel, ts, limit=100, **kw: {"ok": True, "messages": list(thread_messages)}

    # Roles setup
    roster.add_requester("U_CHARLIE", "Charlie H.")
    roster.add_approver("U_CHARLIE")
    roster.add_requester("U_BUYER", "Dylan")
    roster.add_buyer("U_BUYER")
    roster.add_requester("U_REQ", "Isaac")

    # Initial PDF drop
    fake_file = {"name": "EPIF.pdf", "url_private": "https://slack.com/files/epif.pdf"}
    thread_messages.append({
        "user": "U_REQ",
        "ts": "100.00",
        "thread_ts": "100.00",
        "files": [fake_file],
    })

    parsed_sample = {
        "item_description": "Precision Mirror Mount",
        "total_price": 250.0,
        "vendor": "Thorlabs",
        "vendor_contact_name": "Sales",
        "vendor_contact_email": "sales@thorlabs.com",
        "payment_method": "P-card",
        "category": "Research/Lab Supplies (3105)",
        "category_error": None,
        "project_id": "PG000025831",
        "fund": "133",
        "delivery_room": "ERB 212",
        "purpose": "Optics testing",
        "link": "https://thorlabs.com/mount",
        "date_of_purchase": date(2026, 9, 15),
        "name_of_system": "",
        "asset_id": "",
        "total_price_raw": "250.00",
        "pi_of_funding": "Charlie Hirst",
        "end_user": "Isaac",
    }

    excel_appends = []
    excel_updates = []

    def fake_append_row(values, workbook_path=None):
        excel_appends.append(values)
        return 42

    def fake_update_row(row, values, workbook_path=None):
        excel_updates.append((row, values))
        return row

    monkeypatch.setattr(lifecycle.log_writer, "append_row", fake_append_row)
    monkeypatch.setattr(lifecycle.log_writer, "update_row", fake_update_row)
    monkeypatch.setattr(lifecycle.log_writer, "save_epif", lambda bytes_, name, target_dir=None: "/lab/EPIFs/EPIF.pdf")
    monkeypatch.setattr(lifecycle.log_writer, "get_row_info", lambda row: {"row": row, "item_description": "Precision Mirror Mount"})

    with patch.object(lifecycle.slack_io, "download", return_value=b"%PDF-dummy"):
        with patch.object(lifecycle.epif_parser, "parse_epif", return_value=parsed_sample):
            lifecycle.handle_epif_drop(
                client=client,
                say=say,
                channel="C_PURCHASE",
                thread_ts="100.00",
                user_id="U_REQ",
                file_obj=fake_file,
                event_ts="100.00",
            )

    # Bot posted message with req_approve
    posted_call = thread_messages[-1]
    posted_actions = next(b for b in posted_call["blocks"] if b.get("type") == "actions")
    assert posted_actions["elements"][0]["action_id"] == "req_approve"
    approve_value = posted_actions["elements"][0]["value"]

    # 1. Approve (by Charlie) -> writes row to Excel (append)
    body_approve = {
        "user": {"id": "U_CHARLIE"},
        "channel": {"id": "C_PURCHASE"},
        "message": {"ts": "100.10"},
        "container": {"message_ts": "100.10", "thread_ts": "100.00"},
        "actions": [{"action_id": "req_approve", "value": approve_value}],
    }
    with patch.object(lifecycle.slack_io, "download", return_value=b"%PDF-dummy"):
        with patch.object(lifecycle.epif_parser, "parse_epif", return_value=parsed_sample):
            app.handle_req_approve_action(ack, body_approve, respond, client)

    # Assert append_row was called with parsed values and requester
    assert len(excel_appends) == 1
    appended = excel_appends[0]
    assert appended[config.COLUMN_REQUESTER] == "Isaac"
    assert appended["C"] == "Precision Mirror Mount"
    assert appended[config.COLUMN_TOTAL_PRICE] == 250.0

    update_approve = client.chat_update.call_args[1]
    actions_approve = next(b for b in update_approve["blocks"] if b.get("type") == "actions")
    assert actions_approve["elements"][0]["action_id"] == "req_claim"
    claim_value = actions_approve["elements"][0]["value"]

    # 2. Claim (by Dylan)
    ack.reset_mock()
    client.chat_update.reset_mock()
    body_claim = {
        "user": {"id": "U_BUYER"},
        "channel": {"id": "C_PURCHASE"},
        "message": {"ts": "100.10"},
        "container": {"message_ts": "100.10", "thread_ts": "100.00"},
        "actions": [{"action_id": "req_claim", "value": claim_value}],
    }
    app.handle_req_claim_action(ack, body_claim, respond, client)
    update_claim = client.chat_update.call_args[1]
    actions_claim = next(b for b in update_claim["blocks"] if b.get("type") == "actions")
    assert actions_claim["elements"][0]["action_id"] == "req_processed"
    processed_value = actions_claim["elements"][0]["value"]

    # 3. Processed (by Dylan) -> writes Date Processed to Col U
    ack.reset_mock()
    client.chat_update.reset_mock()
    body_sub = {
        "user": {"id": "U_BUYER"},
        "channel": {"id": "C_PURCHASE"},
        "message": {"ts": "100.10"},
        "container": {"message_ts": "100.10", "thread_ts": "100.00"},
        "actions": [{"action_id": "req_processed", "value": processed_value}],
    }
    app.handle_req_processed_action(ack, body_sub, respond, client)
    assert len(excel_updates) == 1
    assert excel_updates[0][0] == 42
    assert config.COLUMN_DATE_PROCESSED in excel_updates[0][1]

    update_sub = client.chat_update.call_args[1]
    actions_sub = next(b for b in update_sub["blocks"] if b.get("type") == "actions")
    assert actions_sub["elements"][0]["action_id"] == "req_confirmed"
    confirmed_value = actions_sub["elements"][0]["value"]

    # 4. Confirmed (by Dylan) -> writes Date Confirmed to Col V
    ack.reset_mock()
    client.chat_update.reset_mock()
    body_conf = {
        "user": {"id": "U_BUYER"},
        "channel": {"id": "C_PURCHASE"},
        "message": {"ts": "100.10"},
        "container": {"message_ts": "100.10", "thread_ts": "100.00"},
        "actions": [{"action_id": "req_confirmed", "value": confirmed_value}],
    }
    app.handle_req_confirmed_action(ack, body_conf, respond, client)
    assert len(excel_updates) == 2
    assert excel_updates[1][0] == 42
    assert config.COLUMN_DATE_CONFIRMED in excel_updates[1][1]

    update_conf = client.chat_update.call_args[1]
    actions_conf = next(b for b in update_conf["blocks"] if b.get("type") == "actions")
    assert actions_conf["elements"][0]["action_id"] == "req_delivered"
    delivered_value = actions_conf["elements"][0]["value"]

    # 5. Delivered (by Dylan) -> writes Date Delivered (Col W) + Received By (Col X)
    ack.reset_mock()
    client.chat_update.reset_mock()
    body_deliv = {
        "user": {"id": "U_BUYER"},
        "channel": {"id": "C_PURCHASE"},
        "message": {"ts": "100.10"},
        "container": {"message_ts": "100.10", "thread_ts": "100.00"},
        "actions": [{"action_id": "req_delivered", "value": delivered_value}],
    }
    app.handle_req_delivered_action(ack, body_deliv, respond, client)
    assert len(excel_updates) == 3
    assert excel_updates[2][0] == 42
    assert config.COLUMN_DATE_DELIVERY in excel_updates[2][1]
    assert excel_updates[2][1][config.COLUMN_RECEIVED_BY] == "Dylan"

    update_deliv = client.chat_update.call_args[1]
    assert not any(b.get("type") == "actions" for b in update_deliv["blocks"])






