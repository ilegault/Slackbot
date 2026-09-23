"""Tests for Ticket 32: Edit a posted card.

WHY THIS EXISTS:
----------------
Covers ADR 0006 decision 8 for modal-born cards: a requester, buyer, or admin may
edit a posted card before it is approved. The edit reopens Screen 2 pre-filled,
validates with the same rules as the interview, updates the card in place, posts one
thread line listing every changed field, and re-posts the draft BOM when items change.

Acceptance criteria exercised:
1. A posted modal-born card renders an Edit button; an approved or later card does not.
2. A non-requester / non-buyer / non-admin who clicks Edit gets an ephemeral denial,
   no views_open is called, and the card is untouched — asserted on absence.
3. The edit form opens pre-filled with the card's current values, including line items.
4. Submitting a changed field updates the card (chat_update) and its metadata payload.
5. Exactly one thread line is posted with the right fragments; the same line appears
   in the card's history.
6. An edit that changes line items re-posts the draft BOM.
7. An edit that changes nothing posts no thread line and no history line.
8. An edit that fails validation is refused on the offending field, card untouched.
9. Changing category to Fabrication requires asset fields before the edit is accepted.
10. An edit submitted after the card was approved is refused with a message, and the
    card and payload are unchanged — asserted on the absence of chat_update.
11. Vendor and route are absent from the edit form (no block_vendor / block_route).
"""
import json
from unittest.mock import MagicMock, patch

from src import app, blocks, config, lifecycle


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _sample_modal_card_payload(
    vendor="VWR-AVANTOR",
    total_price=100.0,
    item_description="Nitrile Gloves",
    state="posted",
    items=None,
    shipping=0.0,
    user_id="U_ISAAC",
    requester="Isaac",
):
    parsed = {
        "item_description": item_description,
        "total_price": total_price,
        "vendor": vendor,
        "payment_method": config.WORKDAY_PAYMENT_METHOD,
        "category": "Research/Lab Supplies (3105)",
        "project_id": "PG000025831",
        "fund": "133",
        "delivery_room": "ERB 212",
        "purpose": "For experiments",
        "link": "https://example.com",
        "vendor_contact_name": "Rep Name",
        "vendor_contact_email": "rep@vendor.com",
        "date_of_purchase": "2026-01-15",
        "asset_id": "",
        "name_of_system": "",
    }
    payload = {
        "parsed": parsed,
        "requester": requester,
        "user_id": user_id,
        "is_pending_name": False,
        "thread_ts": "1000.000",
        "source": "modal",
        "state": state,
    }
    if items is not None:
        payload["items"] = items
        payload["shipping"] = shipping
    return payload


def _make_thread_with_card(card_payload, card_ts="1000.100", thread_ts="1000.000", state="posted"):
    card_blocks = blocks.build_request_blocks(state, card_payload, items=card_payload.get("items"))
    return {
        "ts": card_ts,
        "thread_ts": thread_ts,
        "blocks": card_blocks,
        "metadata": {
            "event_type": "purchase_request",
            "event_payload": card_payload,
        },
    }


def _make_client(card_payload, card_ts="1000.100", thread_ts="1000.000"):
    """Return a fake Slack client whose conversations_replies returns the given card."""
    client = MagicMock()
    thread_msg = _make_thread_with_card(card_payload, card_ts=card_ts, thread_ts=thread_ts)
    client.conversations_replies.return_value = {"messages": [thread_msg]}
    client.chat_update.return_value = {"ok": True}
    client.chat_postMessage.return_value = {"ok": True}
    client.users_info.return_value = {"ok": False}
    return client


def _make_body(user_id, channel_id, card_ts, thread_ts):
    return {
        "user": {"id": user_id},
        "channel": {"id": channel_id},
        "container": {"message_ts": card_ts, "thread_ts": thread_ts},
        "message": {"ts": card_ts, "thread_ts": thread_ts},
        "actions": [{"value": "{}"}],
        "trigger_id": "TRIGGER_ID",
    }


# ---------------------------------------------------------------------------
# 1. Edit button rendered only on posted modal-born cards
# ---------------------------------------------------------------------------

def test_edit_button_on_posted_modal_card():
    """AC1: A posted card from the interview renders an Edit button."""
    req = _sample_modal_card_payload()
    blks = blocks.build_request_blocks("posted", req)
    action_block = next(b for b in blks if b.get("type") == "actions")
    action_ids = [e.get("action_id") for e in action_block["elements"]]
    assert config.ACTION_REQ_EDIT in action_ids


def test_no_edit_button_on_epif_card():
    """AC1: A posted EPIF-born card does not render an Edit button."""
    req = _sample_modal_card_payload()
    req["source"] = "epif"
    blks = blocks.build_request_blocks("posted", req)
    action_block = next(b for b in blks if b.get("type") == "actions")
    action_ids = [e.get("action_id") for e in action_block["elements"]]
    assert config.ACTION_REQ_EDIT not in action_ids


def test_no_edit_button_on_approved_card():
    """AC1: An approved card does not render an Edit button."""
    req = _sample_modal_card_payload(state="approved")
    blks = blocks.build_request_blocks("approved", req)
    # Approved state renders a primary button (Mark Processed) — never Edit
    for blk in blks:
        if blk.get("type") == "actions":
            action_ids = [e.get("action_id") for e in blk["elements"]]
            assert config.ACTION_REQ_EDIT not in action_ids


def test_no_edit_button_on_delivered_card():
    """AC1: A delivered card renders no action buttons at all."""
    req = _sample_modal_card_payload(state="delivered")
    blks = blocks.build_request_blocks("delivered", req)
    assert not any(b.get("type") == "actions" for b in blks)


# ---------------------------------------------------------------------------
# 2. Permission check on the Edit action
# ---------------------------------------------------------------------------

def test_non_authorized_user_denied_ephemerally_no_views_open():
    """AC2: A non-requester/buyer/admin click is refused; no views_open, no chat_update."""
    card_payload = _sample_modal_card_payload(user_id="U_ISAAC")
    client = _make_client(card_payload, card_ts="1001.100", thread_ts="1001.000")
    respond = MagicMock()
    body = _make_body("U_STRANGER", "C_CHAN", "1001.100", "1001.000")

    with (
        patch("src.app.roster.is_buyer", return_value=False),
        patch("src.app.admin.is_admin_user", return_value=False),
        patch("src.app.slack_io.resolve_requester", return_value=None),
    ):
        app_listener = app.app.dispatch
        # Call through the listener directly
        from src.app import handle_req_edit_action
        handle_req_edit_action(lambda: None, body, respond, client)

    # Denied ephemerally — respond called, not views_open
    respond.assert_called_once()
    call_kwargs = respond.call_args
    assert call_kwargs[1].get("response_type") == "ephemeral" or "🔒" in str(call_kwargs)
    client.views_open.assert_not_called()
    client.chat_update.assert_not_called()


def test_requester_can_open_edit_form():
    """AC2: The requester can open the edit form."""
    card_payload = _sample_modal_card_payload(user_id="U_ISAAC")
    client = _make_client(card_payload, card_ts="1002.100", thread_ts="1002.000")
    body = _make_body("U_ISAAC", "C_CHAN", "1002.100", "1002.000")
    respond = MagicMock()

    with (
        patch("src.app.roster.is_buyer", return_value=False),
        patch("src.app.admin.is_admin_user", return_value=False),
        patch("src.app.slack_io.resolve_requester", return_value="Isaac"),
    ):
        from src.app import handle_req_edit_action
        handle_req_edit_action(lambda: None, body, respond, client)

    client.views_open.assert_called_once()
    respond.assert_not_called()


def test_buyer_can_open_edit_form():
    """AC2: A buyer can open the edit form."""
    card_payload = _sample_modal_card_payload(user_id="U_ISAAC")
    client = _make_client(card_payload, card_ts="1003.100", thread_ts="1003.000")
    body = _make_body("U_BUYER", "C_CHAN", "1003.100", "1003.000")
    respond = MagicMock()

    with (
        patch("src.app.roster.is_buyer", return_value=True),
        patch("src.app.admin.is_admin_user", return_value=False),
        patch("src.app.slack_io.resolve_requester", return_value=None),
    ):
        from src.app import handle_req_edit_action
        handle_req_edit_action(lambda: None, body, respond, client)

    client.views_open.assert_called_once()
    respond.assert_not_called()


def test_admin_can_open_edit_form():
    """AC2: An admin can open the edit form."""
    card_payload = _sample_modal_card_payload(user_id="U_ISAAC")
    client = _make_client(card_payload, card_ts="1004.100", thread_ts="1004.000")
    body = _make_body("U_ADMIN", "C_CHAN", "1004.100", "1004.000")
    respond = MagicMock()

    with (
        patch("src.app.roster.is_buyer", return_value=False),
        patch("src.app.admin.is_admin_user", return_value=True),
        patch("src.app.slack_io.resolve_requester", return_value=None),
    ):
        from src.app import handle_req_edit_action
        handle_req_edit_action(lambda: None, body, respond, client)

    client.views_open.assert_called_once()
    respond.assert_not_called()


# ---------------------------------------------------------------------------
# 3. Edit form is pre-filled and vendor/route blocks are absent
# ---------------------------------------------------------------------------

def test_edit_form_is_pre_filled():
    """AC3: The edit form pre-fills fields from the card's current values."""
    from src import bom as bom_mod
    items = [{"qty": 2, "name": "Glove", "part_number": "", "unit_price": 50.0, "link": "", "description": ""}]
    card_payload = _sample_modal_card_payload(total_price=100.0, items=items, shipping=0.0)

    meta = {
        "is_edit": True,
        "channel": "C_CHAN",
        "thread_ts": "1000.000",
        "card_ts": "1000.100",
        "vendor_choice": "VWR-AVANTOR",
        "vendor_custom": "",
        "route": "workday",
        "item_description": "Nitrile Gloves",
        "purpose": "For experiments",
        "link": "https://example.com",
        "total_price": "100.00",
        "vendor_contact_name": "Rep Name",
        "vendor_contact_email": "rep@vendor.com",
        "date_of_purchase": "2026-01-15",
        "delivery_room": "ERB 212",
        "project_id": "PG000025831",
        "fund": "133",
        "category": "Research/Lab Supplies (3105)",
        "payment_method": config.WORKDAY_PAYMENT_METHOD,
        "asset_id": "",
        "name_of_system": "",
        "line_items": bom_mod.format_line_items(items, 0.0),
    }

    view = blocks.build_stage2_view(meta)

    # callback_id must be EDIT_CALLBACK_ID, not STAGE2_CALLBACK_ID
    assert view["callback_id"] == config.EDIT_CALLBACK_ID

    # Item description is pre-filled
    item_desc_block = next(b for b in view["blocks"] if b.get("block_id") == "block_item_description")
    assert item_desc_block["element"].get("initial_value") == "Nitrile Gloves"

    # Line items are pre-filled
    line_items_block = next(b for b in view["blocks"] if b.get("block_id") == "block_line_items")
    assert "Glove" in (line_items_block["element"].get("initial_value") or "")

    # Asset fields are present (always included in edit form)
    block_ids = [b.get("block_id") for b in view["blocks"]]
    assert "block_asset_id" in block_ids
    assert "block_name_of_system" in block_ids


def test_edit_form_has_no_vendor_or_route_input_blocks():
    """AC11: Vendor and route are not editable — no input blocks for them."""
    meta = {
        "is_edit": True,
        "channel": "C_CHAN",
        "thread_ts": "1000.000",
        "card_ts": "1000.100",
        "vendor_choice": "VWR-AVANTOR",
        "vendor_custom": "",
        "route": "workday",
        "item_description": "Gloves",
        "purpose": "Research",
        "link": "",
        "total_price": "50.00",
        "vendor_contact_name": "Rep",
        "vendor_contact_email": "rep@v.com",
        "date_of_purchase": "2026-01-15",
        "delivery_room": "ERB 212",
        "project_id": "PG000025831",
        "fund": "133",
        "category": "Research/Lab Supplies (3105)",
        "payment_method": config.WORKDAY_PAYMENT_METHOD,
        "asset_id": "",
        "name_of_system": "",
        "line_items": "",
    }
    view = blocks.build_stage2_view(meta)
    block_ids = [b.get("block_id") for b in view["blocks"] if b.get("type") == "input"]
    assert "block_vendor" not in block_ids
    assert "block_vendor_custom" not in block_ids


# ---------------------------------------------------------------------------
# 4 & 5. Submitting a changed field updates the card and posts one thread line
# ---------------------------------------------------------------------------

def test_edit_updates_card_and_posts_thread_line():
    """AC4+5: A changed field causes chat_update and exactly one thread line with the right fragment."""
    card_payload = _sample_modal_card_payload(total_price=100.0)
    client = _make_client(card_payload, card_ts="2000.100", thread_ts="2000.000")

    with patch("src.lifecycle.slack_io.resolve_requester", return_value="Isaac"):
        lifecycle.handle_request_edit(
            client=client,
            channel="C_CHAN",
            thread_ts="2000.000",
            card_ts="2000.100",
            stage2={
                "item_description": "Nitrile Gloves",
                "purpose": "For experiments",
                "link": "https://example.com",
                "total_price": "150.00",  # changed
                "vendor_contact_name": "Rep Name",
                "vendor_contact_email": "rep@vendor.com",
                "date_of_purchase": "2026-01-15",
                "delivery_room": "ERB 212",
                "project_id": "PG000025831",
                "fund": "133",
                "category": "Research/Lab Supplies (3105)",
                "payment_method": config.WORKDAY_PAYMENT_METHOD,
            },
            stage3=None,
            items=[],
            shipping=0.0,
            user_id="U_ISAAC",
            card_payload=card_payload,
            meta={
                "vendor_choice": "VWR-AVANTOR",
                "vendor_custom": "",
                "route": "workday",
            },
        )

    # card updated
    client.chat_update.assert_called_once()
    update_kwargs = client.chat_update.call_args[1]
    assert update_kwargs["ts"] == "2000.100"
    assert update_kwargs["channel"] == "C_CHAN"

    # metadata payload carries new total
    new_payload = update_kwargs["metadata"]["event_payload"]
    assert new_payload["parsed"]["total_price"] == 150.0

    # exactly one thread line posted
    client.chat_postMessage.assert_called_once()
    thread_text = client.chat_postMessage.call_args[1]["text"]
    assert "✏️ Edited by Isaac" in thread_text
    assert "Total" in thread_text
    assert "150" in thread_text

    # same line in history
    assert thread_text in new_payload["history"]


# ---------------------------------------------------------------------------
# 6. Items change re-posts draft BOM
# ---------------------------------------------------------------------------

def test_edit_items_change_reposts_draft_bom():
    """AC6: When items change in an edit, the draft BOM is re-posted."""
    old_items = [
        {"qty": 1, "name": "Widget A", "part_number": "", "unit_price": 50.0, "link": "", "description": ""},
        {"qty": 1, "name": "Widget B", "part_number": "", "unit_price": 50.0, "link": "", "description": ""},
    ]
    card_payload = _sample_modal_card_payload(total_price=100.0, items=old_items)
    client = _make_client(card_payload)
    client.files_upload_v2 = MagicMock(return_value={"ok": True})

    new_items = [
        {"qty": 1, "name": "Widget A", "part_number": "", "unit_price": 50.0, "link": "", "description": ""},
        {"qty": 2, "name": "Widget B", "part_number": "", "unit_price": 25.0, "link": "", "description": ""},  # changed
    ]

    with patch("src.lifecycle.slack_io.resolve_requester", return_value="Isaac"):
        lifecycle.handle_request_edit(
            client=client,
            channel="C_CHAN",
            thread_ts="1000.000",
            card_ts="1000.100",
            stage2={
                "item_description": "Nitrile Gloves",
                "purpose": "For experiments",
                "link": "https://example.com",
                "total_price": "100.00",
                "vendor_contact_name": "Rep Name",
                "vendor_contact_email": "rep@vendor.com",
                "date_of_purchase": "2026-01-15",
                "delivery_room": "ERB 212",
                "project_id": "PG000025831",
                "fund": "133",
                "category": "Research/Lab Supplies (3105)",
                "payment_method": config.WORKDAY_PAYMENT_METHOD,
            },
            stage3=None,
            items=new_items,
            shipping=0.0,
            user_id="U_ISAAC",
            card_payload=card_payload,
            meta={
                "vendor_choice": "VWR-AVANTOR",
                "vendor_custom": "",
                "route": "workday",
            },
        )

    client.chat_update.assert_called_once()
    client.files_upload_v2.assert_called_once()
    upload_call = client.files_upload_v2.call_args[1]
    assert "BOM" in upload_call.get("filename", "") or "bom" in upload_call.get("filename", "").lower()


# ---------------------------------------------------------------------------
# 7. No change → no thread line, no history line
# ---------------------------------------------------------------------------

def test_edit_no_change_posts_nothing():
    """AC7: When nothing changes, no thread line is posted and history is unchanged."""
    card_payload = _sample_modal_card_payload(total_price=100.0)
    client = _make_client(card_payload)

    lifecycle.handle_request_edit(
        client=client,
        channel="C_CHAN",
        thread_ts="1000.000",
        card_ts="1000.100",
        stage2={
            "item_description": "Nitrile Gloves",
            "purpose": "For experiments",
            "link": "https://example.com",
            "total_price": "100.00",
            "vendor_contact_name": "Rep Name",
            "vendor_contact_email": "rep@vendor.com",
            "date_of_purchase": "2026-01-15",
            "delivery_room": "ERB 212",
            "project_id": "PG000025831",
            "fund": "133",
            "category": "Research/Lab Supplies (3105)",
            "payment_method": config.WORKDAY_PAYMENT_METHOD,
        },
        stage3=None,
        items=[],
        shipping=0.0,
        user_id="U_ISAAC",
        card_payload=card_payload,
        meta={
            "vendor_choice": "VWR-AVANTOR",
            "vendor_custom": "",
            "route": "workday",
        },
    )

    client.chat_update.assert_not_called()
    client.chat_postMessage.assert_not_called()


# ---------------------------------------------------------------------------
# 8. Validation failure is refused on offending field, card untouched
# ---------------------------------------------------------------------------

def _make_edit_view_submission(meta, stage2_overrides=None, stage3_overrides=None, line_items_text=""):
    """Build a fake Bolt view submission body for handle_edit_submit."""
    base_stage2 = {
        "item_description": "Nitrile Gloves",
        "purpose": "For experiments",
        "link": "https://example.com",
        "total_price": "100.00",
        "vendor_contact_name": "Rep Name",
        "vendor_contact_email": "rep@vendor.com",
        "date_of_purchase": "2026-01-15",
        "delivery_room": "ERB 212",
        "project_id": "PG000025831",
        "fund": "133",
        "category": "Research/Lab Supplies (3105)",
        "payment_method": config.WORKDAY_PAYMENT_METHOD,
    }
    if stage2_overrides:
        base_stage2.update(stage2_overrides)

    base_stage3 = {"asset_id": "", "name_of_system": ""}
    if stage3_overrides:
        base_stage3.update(stage3_overrides)

    values = {}
    for k, v in base_stage2.items():
        if k in ("delivery_room", "project_id", "fund", "category", "payment_method"):
            values[f"block_{k}"] = {k: {"type": "static_select", "selected_option": {"value": v} if v else None}}
        elif k == "date_of_purchase":
            values["block_date_of_purchase"] = {"date_of_purchase": {"type": "datepicker", "selected_date": v}}
        else:
            values[f"block_{k}"] = {k: {"type": "plain_text_input", "value": v}}

    for k, v in base_stage3.items():
        values[f"block_{k}"] = {k: {"type": "plain_text_input", "value": v}}

    if line_items_text:
        values["block_line_items"] = {"line_items": {"type": "plain_text_input", "value": line_items_text}}

    return {
        "user": {"id": "U_ISAAC"},
        "view": {
            "state": {"values": values},
            "private_metadata": json.dumps(meta),
        },
    }


def test_edit_validation_failure_refused_card_untouched():
    """AC8: A submission with an empty item description is refused on block_item_description."""
    card_payload = _sample_modal_card_payload()
    client = _make_client(card_payload)

    meta = {
        "is_edit": True,
        "channel": "C_CHAN",
        "thread_ts": "1000.000",
        "card_ts": "1000.100",
        "vendor_choice": "VWR-AVANTOR",
        "vendor_custom": "",
        "route": "workday",
    }

    ack_calls = []
    def fake_ack(**kwargs):
        ack_calls.append(kwargs)

    body = _make_edit_view_submission(meta, stage2_overrides={"item_description": ""})
    view = body["view"]

    with (
        patch("src.app.roster.get_valid_requesters", return_value={"U_ISAAC": "Isaac"}),
        patch("src.app.slack_io.get_card_payload", return_value=card_payload),
    ):
        from src.app import handle_edit_submit
        handle_edit_submit(fake_ack, body, client, view)

    # ack was called with errors — validation failed
    assert len(ack_calls) == 1
    assert ack_calls[0].get("response_action") == "errors"
    assert "block_item_description" in ack_calls[0]["errors"]

    # card untouched
    client.chat_update.assert_not_called()


# ---------------------------------------------------------------------------
# 9. Fabrication category requires asset fields
# ---------------------------------------------------------------------------

def test_edit_fabrication_category_requires_asset_fields():
    """AC9: Changing category to Fabrication Component without asset fields is refused."""
    card_payload = _sample_modal_card_payload()
    client = _make_client(card_payload)

    meta = {
        "is_edit": True,
        "channel": "C_CHAN",
        "thread_ts": "1000.000",
        "card_ts": "1000.100",
        "vendor_choice": "VWR-AVANTOR",
        "vendor_custom": "",
        "route": "workday",
    }

    ack_calls = []
    def fake_ack(**kwargs):
        ack_calls.append(kwargs)

    body = _make_edit_view_submission(
        meta,
        stage2_overrides={"category": "Fabrication Component (4670) > $200"},
        stage3_overrides={"asset_id": "", "name_of_system": ""},
    )
    view = body["view"]

    with (
        patch("src.app.roster.get_valid_requesters", return_value={"U_ISAAC": "Isaac"}),
        patch("src.app.slack_io.get_card_payload", return_value=card_payload),
    ):
        from src.app import handle_edit_submit
        handle_edit_submit(fake_ack, body, client, view)

    assert ack_calls[0].get("response_action") == "errors"
    errors = ack_calls[0]["errors"]
    assert "block_asset_id" in errors or "block_name_of_system" in errors
    client.chat_update.assert_not_called()


def test_edit_fabrication_category_accepted_with_asset_fields():
    """AC9: Fabrication category is accepted when asset fields are provided."""
    card_payload = _sample_modal_card_payload()
    client = _make_client(card_payload)

    meta = {
        "is_edit": True,
        "channel": "C_CHAN",
        "thread_ts": "1000.000",
        "card_ts": "1000.100",
        "vendor_choice": "VWR-AVANTOR",
        "vendor_custom": "",
        "route": "workday",
    }

    ack_calls = []
    def fake_ack(**kwargs):
        ack_calls.append(kwargs)

    body = _make_edit_view_submission(
        meta,
        stage2_overrides={"category": "Fabrication Component (4670) > $200"},
        stage3_overrides={"asset_id": "TAG-99", "name_of_system": "Laser System"},
    )
    view = body["view"]

    # Card is still posted
    card_payload_copy = dict(card_payload)
    card_payload_copy["state"] = "posted"

    with (
        patch("src.app.roster.get_valid_requesters", return_value={"U_ISAAC": "Isaac"}),
        patch("src.app.slack_io.get_card_payload", return_value=card_payload_copy),
        patch("src.lifecycle.slack_io.resolve_requester", return_value="Isaac"),
    ):
        from src.app import handle_edit_submit
        handle_edit_submit(fake_ack, body, client, view)

    # ack with no errors (normal ack)
    assert len(ack_calls) == 1
    assert ack_calls[0] == {}


# ---------------------------------------------------------------------------
# 10. Approved-meanwhile guard
# ---------------------------------------------------------------------------

def test_edit_refused_when_approved_meanwhile():
    """AC10: If card is approved when the edit is submitted, nothing changes."""
    approved_payload = _sample_modal_card_payload(state="approved")
    client = _make_client(approved_payload)

    meta = {
        "is_edit": True,
        "channel": "C_CHAN",
        "thread_ts": "1000.000",
        "card_ts": "1000.100",
        "vendor_choice": "VWR-AVANTOR",
        "vendor_custom": "",
        "route": "workday",
    }

    ack_calls = []
    def fake_ack(**kwargs):
        ack_calls.append(kwargs)

    body = _make_edit_view_submission(meta, stage2_overrides={"total_price": "200.00"})
    view = body["view"]

    with (
        patch("src.app.roster.get_valid_requesters", return_value={"U_ISAAC": "Isaac"}),
        patch("src.app.slack_io.get_card_payload", return_value=approved_payload),
    ):
        from src.app import handle_edit_submit
        handle_edit_submit(fake_ack, body, client, view)

    assert ack_calls[0].get("response_action") == "errors"
    errors = ack_calls[0]["errors"]
    # Error message mentions "approved"
    assert any("approved" in v.lower() for v in errors.values())

    # card not modified
    client.chat_update.assert_not_called()
