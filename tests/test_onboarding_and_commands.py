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
    view_workday = app.build_stage2_view(meta_workday)
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
    view_epif = app.build_stage2_view(meta_epif)
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
    view = app.build_stage2_view(meta)
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

    view_stage3 = app.build_stage3_view(worst_case_meta)
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
    with patch.object(app, "handle_template_command") as mock_tmpl:
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
    with patch.object(app, "handle_template_command"):
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

    state_expected_action = {
        "posted": "req_approve",
        "approved": "req_claim",
        "claimed": "req_submitted",
        "submitted": "req_confirmed",
        "confirmed": "req_delivered",
    }

    for state, expected_action in state_expected_action.items():
        blocks = app.build_request_blocks(state, sample_req)
        action_blocks = [b for b in blocks if b.get("type") == "actions"]
        assert len(action_blocks) == 1
        elements = action_blocks[0].get("elements", [])
        assert len(elements) == 1
        assert elements[0].get("action_id") == expected_action

    # delivered state -> 0 buttons
    blocks_deliv = app.build_request_blocks("delivered", sample_req)
    action_blocks_deliv = [b for b in blocks_deliv if b.get("type") == "actions"]
    assert len(action_blocks_deliv) == 0


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
    with patch.object(app, "handle_epif_processing") as mock_epif:
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

    # 1. Button click req_claim
    button_body = {
        "user": {"id": "UGRADBUYER"},
        "channel": {"id": "C_TEST"},
        "message": {"ts": "5555.66"},
        "container": {"message_ts": "5555.66", "thread_ts": "5555.66"},
        "actions": [{"value": json.dumps({"request": {"item_description": "Bolts"}, "history": []})}],
    }
    with patch.object(app, "handle_claim") as mock_claim:
        app.handle_req_claim_action(ack, button_body, respond, client)
        ack.assert_called_once()
        mock_claim.assert_called_once()
        btn_channel = mock_claim.call_args[1]["channel"]
        btn_thread = mock_claim.call_args[1]["thread_ts"]

    # 2. Keyword mention @p-bot claim
    with patch.object(app, "handle_claim") as mock_claim_kw:
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


