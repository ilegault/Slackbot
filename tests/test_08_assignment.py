"""Tests for Ticket 08: Assignment replaces claim — the approver names the buyer.

Enforces ADR 0004 decisions:
- Mentions parsed purely via text_rules.parse_mentions
- Keyword matching against mention-stripped text
- Approver naming buyer before or after keyword assigns buyer
- Assignee DM contains email draft signed by assignee
- Approvals with 0, 2+, group, or non-buyer mentions write rows but leave card unassigned
- Gating on assignee/admin for req_processed
- Reassignment on already-approved thread avoids duplicate Excel row
- Clean removal of req_claim and claim keywords
"""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

import src.app as app
from src import blocks, lifecycle, roster, text_rules


@pytest.fixture(autouse=True)
def clean_roster(tmp_path, monkeypatch):
    """Ensure tests run against a clean isolated roster."""
    roster_file = tmp_path / "roster.json"
    roster_file.write_text(json.dumps({
        "requesters": {},
        "admins": ["U_ADMIN"],
        "approvers": ["U_CHARLIE"],
        "buyers": ["U_DYLAN", "U_SMEET"],
        "vendors": {},
    }), encoding="utf-8")
    monkeypatch.setattr(roster, "ROSTER_PATH", str(roster_file))
    roster.load_roster()
    roster.add_requester("U_ADMIN", "Admin User")
    roster.add_requester("U_CHARLIE", "Charlie Hirst")
    roster.add_requester("U_DYLAN", "Dylan")
    roster.add_requester("U_SMEET", "Smeet")
    roster.add_requester("U_STUDENT", "Student")
    roster.add_requester("U_ISAAC", "Isaac")


def make_valid_parsed(**overrides):
    base = {
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
        "date_of_purchase": "09/16/26",
        "name_of_system": "",
        "asset_id": "",
    }
    base.update(overrides)
    return base


# 1. parse_mentions signature, purity, and formats
def test_parse_mentions_pure_and_handles_formats():
    """parse_mentions extracts users, groups, and strips them purely."""
    bot_id = "U_BOT"
    text = f"<@{bot_id}> please review <@U123> and <@U456|alice> plus <!subteam^S789|team> and <@W999>"
    stripped, users, groups = text_rules.parse_mentions(text, bot_user_id=bot_id)

    assert stripped == "please review and plus and"
    assert users == ["U123", "U456", "W999"]
    assert groups == ["S789"]

    # Assert purity: same call returns same output without side-effects
    stripped2, users2, groups2 = text_rules.parse_mentions(text, bot_user_id=bot_id)
    assert stripped2 == stripped
    assert users2 == users
    assert groups2 == groups


# 2. dispatch_command matches keywords against stripped text
def test_dispatch_command_keyword_matching_after_stripping():
    """Keyword matching operates on mention-stripped text; user IDs with keyword names don't trigger."""
    client = MagicMock()
    say = MagicMock()

    with patch.object(app.ops, "handle_logs") as mock_logs:
        # @Purchasing logs reaches ops logs handler
        app.dispatch_command(
            client=client,
            say=say,
            channel="C1",
            thread_ts="100.0",
            user="U_ADMIN",
            event_ts="100.1",
            text="<@U_BOT> logs",
            bot_user_id="U_BOT",
        )
        mock_logs.assert_called_once()

    with patch.object(app.ops, "handle_logs") as mock_logs:
        # A message whose only content is a mention with a keyword-shaped ID does NOT reach it
        app.dispatch_command(
            client=client,
            say=say,
            channel="C1",
            thread_ts="100.0",
            user="U_ADMIN",
            event_ts="100.2",
            text="<@U_BOT> <@U0LOGS99>",
            bot_user_id="U_BOT",
        )
        mock_logs.assert_not_called()


# 3 & 4. Approver naming buyer before or after keyword
def test_approval_naming_buyer_before_and_after_keyword():
    """Naming buyer before bot mention or after keyword produces identical assignment."""
    client = MagicMock()
    say = MagicMock()

    # Pattern A: @Dylan @Purchasing approved
    with patch.object(lifecycle, "handle_epif_processing") as mock_epif_a:
        app.dispatch_command(
            client=client,
            say=say,
            channel="C1",
            thread_ts="100.0",
            user="U_CHARLIE",
            event_ts="100.1",
            text="<@U_DYLAN> <@U_BOT> approved",
            bot_user_id="U_BOT",
        )
        mock_epif_a.assert_called_once()
        assert mock_epif_a.call_args[1]["assignee_id"] == "U_DYLAN"
        assert mock_epif_a.call_args[1]["assignee_name"] == "Dylan"

    # Pattern B: @Purchasing approved @Dylan
    with patch.object(lifecycle, "handle_epif_processing") as mock_epif_b:
        app.dispatch_command(
            client=client,
            say=say,
            channel="C1",
            thread_ts="100.0",
            user="U_CHARLIE",
            event_ts="100.2",
            text="<@U_BOT> approved <@U_DYLAN>",
            bot_user_id="U_BOT",
        )
        mock_epif_b.assert_called_once()
        assert mock_epif_b.call_args[1]["assignee_id"] == "U_DYLAN"
        assert mock_epif_b.call_args[1]["assignee_name"] == "Dylan"


# 5. Assignee DM contains email draft signed by assignee
def test_assignee_dm_contains_draft_signed_by_assignee(monkeypatch):
    """The assignment DM contains the draft signed with assignee's name and goes to assignee."""
    client = MagicMock()
    say = MagicMock()

    parsed = make_valid_parsed()

    def sync_submit(action_fn, *args, success_callback=None, **kwargs):
        res = action_fn()
        if success_callback:
            success_callback(res)

    monkeypatch.setattr(lifecycle.queue_worker, "submit_write_task", sync_submit)
    monkeypatch.setattr(lifecycle.log_writer, "append_row", lambda *a, **k: 12)
    monkeypatch.setattr(lifecycle.log_writer, "save_epif", lambda *a, **k: "/path/EPIFs/order.pdf")
    monkeypatch.setattr(lifecycle.log_writer, "get_row_info", lambda row: {"row": row, "item_description": "Precision Mirror Mount"})

    lifecycle.finalize_purchase_request(
        client=client,
        say=say,
        channel="C1",
        thread_ts="100.0",
        event_ts="100.1",
        parsed=parsed,
        requester="Isaac",
        notify_target="U_CHARLIE",
        pdf_bytes=b"pdf",
        file_name="order.pdf",
        assignee_id="U_DYLAN",
        assignee_name="Dylan",
        approver="U_CHARLIE",
    )

    dm_calls = [
        call for call in client.chat_postMessage.call_args_list
        if call[1].get("channel") == "U_DYLAN"
    ]
    assert len(dm_calls) == 1
    dm_text = dm_calls[0][1]["text"]
    assert "Hirst Lab purchase request" in dm_text
    assert "Dylan" in dm_text  # Signed by assignee


# 6. Approval with no mention leaves unassigned and sends no DM
def test_approval_with_no_mention_unassigned_and_no_dm(monkeypatch):
    """Approval without mention writes row, posts unassigned card, prompts for buyer, sends NO DM."""
    client = MagicMock()
    say = MagicMock()

    parsed = make_valid_parsed()

    def sync_submit(action_fn, *args, success_callback=None, **kwargs):
        res = action_fn()
        if success_callback:
            success_callback(res)

    monkeypatch.setattr(lifecycle.queue_worker, "submit_write_task", sync_submit)
    monkeypatch.setattr(lifecycle.log_writer, "append_row", lambda *a, **k: 15)
    monkeypatch.setattr(lifecycle.log_writer, "save_epif", lambda *a, **k: "/path/EPIFs/order.pdf")

    lifecycle.finalize_purchase_request(
        client=client,
        say=say,
        channel="C1",
        thread_ts="100.0",
        event_ts="100.1",
        parsed=parsed,
        requester="Isaac",
        notify_target="U_CHARLIE",
        pdf_bytes=b"pdf",
        file_name="order.pdf",
        assignee_id=None,
        assignee_name=None,
        approver="U_CHARLIE",
    )

    say.assert_called_once()
    broadcast_text = say.call_args[1]["text"]
    assert "Please assign a buyer" in broadcast_text

    # Assert NO DMs were sent
    dm_calls = [
        call for call in client.chat_postMessage.call_args_list
        if not call[1].get("thread_ts")
    ]
    assert len(dm_calls) == 0


# 7. Approval naming a non-buyer refused without refusing approval
def test_approval_naming_non_buyer_refused_no_dm():
    """Approver naming a non-buyer writes rows, leaves unassigned, refuses with add-buyer hint, no DM."""
    client = MagicMock()
    say = MagicMock()

    with patch.object(lifecycle, "handle_epif_processing") as mock_epif:
        app.dispatch_command(
            client=client,
            say=say,
            channel="C1",
            thread_ts="100.0",
            user="U_CHARLIE",
            event_ts="100.1",
            text="<@U_BOT> approved <@U_STUDENT>",
            bot_user_id="U_BOT",
        )
        mock_epif.assert_called_once()
        assert mock_epif.call_args[1]["assignee_id"] is None
        refusal = mock_epif.call_args[1]["refusal_msg"]
        assert "<@U_STUDENT> isn't on the buyers list" in refusal
        assert "@Purchasing add-buyer <@U_STUDENT>" in refusal


# 8. Approval naming two users refused
def test_approval_naming_two_users_refused():
    """Approver naming multiple users writes rows, leaves unassigned, asks which one, no DM."""
    client = MagicMock()
    say = MagicMock()

    with patch.object(lifecycle, "handle_epif_processing") as mock_epif:
        app.dispatch_command(
            client=client,
            say=say,
            channel="C1",
            thread_ts="100.0",
            user="U_CHARLIE",
            event_ts="100.1",
            text="<@U_BOT> approved <@U_DYLAN> <@U_SMEET>",
            bot_user_id="U_BOT",
        )
        mock_epif.assert_called_once()
        assert mock_epif.call_args[1]["assignee_id"] is None
        refusal = mock_epif.call_args[1]["refusal_msg"]
        assert "Multiple buyers mentioned" in refusal
        assert "<@U_DYLAN>" in refusal
        assert "<@U_SMEET>" in refusal


# 9. Approval naming user group refused
def test_approval_naming_user_group_refused():
    """Approver naming a user group writes rows, leaves unassigned, refuses group assignment."""
    client = MagicMock()
    say = MagicMock()

    with patch.object(lifecycle, "handle_epif_processing") as mock_epif:
        app.dispatch_command(
            client=client,
            say=say,
            channel="C1",
            thread_ts="100.0",
            user="U_CHARLIE",
            event_ts="100.1",
            text="<@U_BOT> approved <!subteam^S123|buyers>",
            bot_user_id="U_BOT",
        )
        mock_epif.assert_called_once()
        assert mock_epif.call_args[1]["assignee_id"] is None
        refusal = mock_epif.call_args[1]["refusal_msg"]
        assert "Cannot assign to a user group" in refusal


# 10. Buyer self-assigns to unassigned request succeeds and receives draft
def test_buyer_self_assigns_unassigned_request():
    """A buyer can self-assign an unassigned request via handle_assign and receives email draft."""
    client = MagicMock()
    say = MagicMock()

    card_req = {
        "row": 20,
        "item_description": "Lens",
        "vendor": "Thorlabs",
        "vendor_contact_email": "sales@thorlabs.com",
        "total_price": 50.0,
    }
    history = ["Posted on 09/16"]

    with patch.object(lifecycle.slack_io, "find_card_in_thread", return_value=(card_req, "100.1", history, "approved")):
        ok = lifecycle.handle_assign(
            client=client,
            say=say,
            channel="C1",
            thread_ts="100.0",
            user_id="U_DYLAN",
            event_ts="100.2",
            target_user_id=None,  # Self-assign
        )
        assert ok is True
        client.chat_update.assert_called_once()
        update_blocks = client.chat_update.call_args[1]["blocks"]
        # Summary block contains buyer
        section = update_blocks[0]["text"]["text"]
        assert "• *Buyer:* <@U_DYLAN> (Dylan)" in section

        # DM sent to Dylan
        dm_calls = [
            call for call in client.chat_postMessage.call_args_list
            if call[1].get("channel") == "U_DYLAN"
        ]
        assert len(dm_calls) == 1
        assert "Hirst Lab purchase request" in dm_calls[0][1]["text"]
        assert "Dylan" in dm_calls[0][1]["text"]


# 11. Non-assignee buyer attempting to reassign already assigned request is refused
def test_buyer_reassign_already_assigned_request_denied():
    """A buyer who is not the assignee cannot reassign an assigned order."""
    client = MagicMock()
    say = MagicMock()

    card_req = {
        "row": 20,
        "assignee_id": "U_DYLAN",
        "assignee": "Dylan",
    }
    history = ["Assigned to Dylan"]

    with patch.object(lifecycle.slack_io, "find_card_in_thread", return_value=(card_req, "100.1", history, "approved")):
        ok = lifecycle.handle_assign(
            client=client,
            say=say,
            channel="C1",
            thread_ts="100.0",
            user_id="U_SMEET",  # Smeet is a buyer, but Dylan is current assignee
            event_ts="100.2",
            target_user_id="U_SMEET",
        )
        assert ok is False
        client.chat_update.assert_not_called()
        say.assert_called_once()
        assert "Only the assignee, an approver, or an admin can reassign it" in say.call_args[1]["text"]


# 12. Approver reassigning assigned request succeeds and leaves both in history
def test_approver_reassigning_assigned_request():
    """Approver can reassign an assigned request; history preserves both assignments."""
    client = MagicMock()
    say = MagicMock()

    card_req = {
        "row": 20,
        "assignee_id": "U_DYLAN",
        "assignee": "Dylan",
        "item_description": "Lens",
        "vendor": "Thorlabs",
    }
    history = ["Assigned to Dylan on 09/16/26 10:00"]

    with patch.object(lifecycle.slack_io, "find_card_in_thread", return_value=(card_req, "100.1", history, "approved")):
        ok = lifecycle.handle_assign(
            client=client,
            say=say,
            channel="C1",
            thread_ts="100.0",
            user_id="U_CHARLIE",  # Approver
            event_ts="100.2",
            target_user_id="U_SMEET",
        )
        assert ok is True
        client.chat_update.assert_called_once()
        update_blocks = client.chat_update.call_args[1]["blocks"]
        # Summary block contains Smeet
        section = update_blocks[0]["text"]["text"]
        assert "• *Buyer:* <@U_SMEET> (Smeet)" in section

        # History contains both
        actions = next(b for b in update_blocks if b.get("type") == "actions")
        new_val = json.loads(actions["elements"][0]["value"])
        new_history = new_val["history"]
        assert len(new_history) == 2
        assert "Assigned to Dylan" in new_history[0]
        assert "Reassigned to Smeet by Charlie Hirst" in new_history[1]

        # DM sent to Smeet
        dm_calls = [
            call for call in client.chat_postMessage.call_args_list
            if call[1].get("channel") == "U_SMEET"
        ]
        assert len(dm_calls) == 1


# 13. Current assignee reassigns to another buyer succeeds
def test_current_assignee_reassigns_to_another_buyer():
    """Current assignee can reassign to another buyer."""
    client = MagicMock()
    say = MagicMock()

    card_req = {
        "row": 20,
        "assignee_id": "U_DYLAN",
        "assignee": "Dylan",
        "item_description": "Lens",
    }
    history = ["Assigned to Dylan on 09/16"]

    with patch.object(lifecycle.slack_io, "find_card_in_thread", return_value=(card_req, "100.1", history, "approved")):
        ok = lifecycle.handle_assign(
            client=client,
            say=say,
            channel="C1",
            thread_ts="100.0",
            user_id="U_DYLAN",  # Current assignee
            event_ts="100.2",
            target_user_id="U_SMEET",
        )
        assert ok is True
        client.chat_update.assert_called_once()


# 14. Already approved thread: approval keyword reassigns without second Excel write
def test_already_approved_thread_approval_keyword_reassigns_no_excel_write():
    """@Purchasing approved @Smeet on an already-approved thread reassigns without appending Excel row."""
    client = MagicMock()
    say = MagicMock()

    card_req = {
        "row": 25,
        "assignee_id": "U_DYLAN",
        "assignee": "Dylan",
    }
    with patch.object(lifecycle.slack_io, "find_card_in_thread", return_value=(card_req, "100.1", [], "approved")):
        with patch.object(lifecycle, "handle_assign") as mock_assign:
            with patch.object(lifecycle, "handle_epif_processing") as mock_epif:
                app.dispatch_command(
                    client=client,
                    say=say,
                    channel="C1",
                    thread_ts="100.0",
                    user="U_CHARLIE",
                    event_ts="100.2",
                    text="<@U_BOT> approved <@U_SMEET>",
                    bot_user_id="U_BOT",
                )
                mock_assign.assert_called_once()
                assert mock_assign.call_args[1]["target_user_id"] == "U_SMEET"
                mock_epif.assert_not_called()


# 15 & 16. req_processed permissions
def test_req_processed_unauthorized_user_denied():
    """req_processed from user who is neither assignee nor admin is denied."""
    ack = MagicMock()
    respond = MagicMock()
    client = MagicMock()

    body = {
        "user": {"id": "U_STUDENT"},
        "channel": {"id": "C1"},
        "message": {"ts": "100.1"},
        "actions": [{
            "action_id": "req_processed",
            "value": json.dumps({"state": "approved", "request": {"row": 20, "assignee_id": "U_DYLAN"}, "history": []}),
        }],
    }
    with patch.object(lifecycle, "handle_processed") as mock_processed:
        app.handle_req_processed_action(ack, body, respond, client)
        mock_processed.assert_not_called()
        client.chat_update.assert_not_called()
        respond.assert_called_once()
        assert "Only the assigned buyer" in respond.call_args[1]["text"]


def test_req_processed_unassigned_request_denied():
    """req_processed on an unassigned request is denied asking to assign first."""
    ack = MagicMock()
    respond = MagicMock()
    client = MagicMock()

    body = {
        "user": {"id": "U_DYLAN"},
        "channel": {"id": "C1"},
        "message": {"ts": "100.1"},
        "actions": [{
            "action_id": "req_processed",
            "value": json.dumps({"state": "approved", "request": {"row": 20, "assignee_id": None}, "history": []}),
        }],
    }
    with patch.object(lifecycle, "handle_processed") as mock_processed:
        app.handle_req_processed_action(ack, body, respond, client)
        mock_processed.assert_not_called()
        client.chat_update.assert_not_called()
        respond.assert_called_once()
        assert "must be assigned to a buyer before it can be marked processed" in respond.call_args[1]["text"]


# 17. build_request_blocks approved state & no req_claim in src/
def test_build_request_blocks_approved_state_and_no_req_claim_in_src():
    """Approved state offers Mark Processed and Cancel; req_claim appears nowhere in src/."""
    card_blocks = blocks.build_request_blocks("approved", {"item_description": "Mirror", "total_price": 10.0})
    actions = next(b for b in card_blocks if b.get("type") == "actions")
    action_ids = [el["action_id"] for el in actions["elements"]]
    assert action_ids == ["req_processed", "req_cancel"]

    src_dir = Path("src")
    for py_file in src_dir.rglob("*.py"):
        content = py_file.read_text(encoding="utf-8")
        assert "req_claim" not in content, f"Found req_claim in {py_file}"
        assert "CLAIM_KEYWORDS" not in content, f"Found CLAIM_KEYWORDS in {py_file}"


# 18. Card renders assignee line in both forms
def test_card_renders_assignee_in_both_forms():
    """Card summary block renders assigned buyer or unassigned badge."""
    assigned_blocks = blocks.build_request_blocks("approved", {
        "assignee_id": "U_DYLAN",
        "assignee": "Dylan",
        "item_description": "Mirror",
    })
    assigned_text = assigned_blocks[0]["text"]["text"]
    assert "• *Buyer:* <@U_DYLAN> (Dylan)" in assigned_text

    unassigned_blocks = blocks.build_request_blocks("approved", {
        "assignee_id": None,
        "item_description": "Mirror",
    })
    unassigned_text = unassigned_blocks[0]["text"]["text"]
    assert "• *Buyer:* ⚠️ _Unassigned_" in unassigned_text


# 19. Claim keyword ignored
def test_claim_keyword_ignored():
    """@Purchasing claim assigns nothing, writes nothing, and updates no card."""
    client = MagicMock()
    say = MagicMock()

    with patch.object(lifecycle, "handle_epif_processing") as mock_epif:
        with patch.object(lifecycle, "handle_assign") as mock_assign:
            app.dispatch_command(
                client=client,
                say=say,
                channel="C1",
                thread_ts="100.0",
                user="U_DYLAN",
                event_ts="100.1",
                text="<@U_BOT> claim",
                bot_user_id="U_BOT",
            )
            mock_epif.assert_not_called()
            mock_assign.assert_not_called()
            client.chat_update.assert_not_called()


# 20. Approval thread message contains filename only
def test_approval_thread_message_contains_filename_only(monkeypatch):
    """Saved EPIF message prints file name only, no directory or drive letter."""
    client = MagicMock()
    say = MagicMock()

    parsed = make_valid_parsed()

    def sync_submit(action_fn, *args, success_callback=None, **kwargs):
        res = action_fn()
        if success_callback:
            success_callback(res)

    monkeypatch.setattr(lifecycle.queue_worker, "submit_write_task", sync_submit)
    monkeypatch.setattr(lifecycle.log_writer, "append_row", lambda *a, **k: 15)
    monkeypatch.setattr(lifecycle.log_writer, "save_epif", lambda *a, **k: r"C:\Users\IGLeg\Purchasing\EPIFs\Thorlabs_EPIF.pdf")
    monkeypatch.setattr(lifecycle.log_writer, "get_row_info", lambda row: {"row": row, "item_description": "Precision Mirror Mount"})

    lifecycle.finalize_purchase_request(
        client=client,
        say=say,
        channel="C1",
        thread_ts="100.0",
        event_ts="100.1",
        parsed=parsed,
        requester="Isaac",
        notify_target="U_CHARLIE",
        pdf_bytes=b"pdf",
        file_name="Thorlabs_EPIF.pdf",
        approver="U_CHARLIE",
    )

    say.assert_called_once()
    msg = say.call_args[1]["text"]
    saved_epif_line = next(line for line in msg.splitlines() if "Saved EPIF to" in line)
    assert "Saved EPIF to `Thorlabs_EPIF.pdf`" in saved_epif_line
    assert "C:" not in saved_epif_line
    assert "\\" not in saved_epif_line
    assert "/" not in saved_epif_line
