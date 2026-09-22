"""Tests for Ticket 27: Add items to a dropped EPIF.

WHY THIS EXISTS:
----------------
Covers the line items capability on dropped EPIF cards (ADR 0006 decision 3):
1. Posted card renders 'Add items' on source=='epif' cards; approved/later cards do not.
2. Submitting valid paste stores items and shipping in message metadata.
3. Updated card button values contain NO line items (metadata is the store).
4. Summary line shows line items count only when items >= 2 ('📋 N line items (BOM attached in thread)').
5. Two or more items upload a draft spreadsheet to the thread; one item uploads nothing.
6. Draft file is not written to BOMS_DIR.
7. Totals mismatch is refused inside modal with both numbers, card untouched.
8. Bad line is refused inside modal with line-numbered error, card untouched.
9. Re-opening button once items exist pre-fills box and reads 'Edit items'.
10. Re-submitting different items replaces stored items, re-posts draft spreadsheet, posts edit line.
11. Reading card payload in multi-card thread returns clicked card, not newest card.
12. dropped EPIF sets source='epif'.
13. Permission check: non-requester/non-buyer/non-admin denied ephemerally, card untouched.
"""
import io
import json
import os
from unittest.mock import MagicMock

import openpyxl

from src import app, blocks, config, lifecycle, slack_io


def _sample_epif_card_payload(
    items=None,
    shipping=0.0,
    total_price=100.0,
    vendor="Ruland",
    ts="1000.1000",
    thread_ts="1000.1000",
    requester="Isaac",
    user_id="U_ISAAC",
    state="posted",
):
    parsed = {
        "item_description": "Couplings",
        "total_price": total_price,
        "vendor": vendor,
        "payment_method": "EPIF",
        "category": "Research/Lab Supplies (3105)",
        "project_id": "PG000025831",
        "fund": "133",
        "delivery_room": "ERB 212",
        "purpose": "Shaft alignment",
        "link": "https://example.com/ruland",
    }
    payload = {
        "parsed": parsed,
        "raw_text": "Uploaded EPIF: epif.pdf",
        "requester": requester,
        "user_id": user_id,
        "is_pending_name": False,
        "thread_ts": thread_ts,
        "source": "epif",
        "state": state,
    }
    if items is not None:
        payload["items"] = items
        payload["shipping"] = shipping
    return payload


def _make_thread_message(card_payload, ts="1000.1000", thread_ts="1000.1000", state="posted"):
    card_blocks = blocks.build_request_blocks(
        state,
        card_payload,
        items=card_payload.get("items"),
    )
    return {
        "ts": ts,
        "thread_ts": thread_ts,
        "text": f"🛒 Purchase Request ({state.capitalize()})",
        "blocks": card_blocks,
        "metadata": {
            "event_type": "purchase_request",
            "event_payload": card_payload,
        },
    }


# ---------------------------------------------------------------------------
# 1. Add items button rendered on posted EPIF card, not on approved/later
# ---------------------------------------------------------------------------

def test_posted_card_epif_renders_add_items_button_and_other_states_do_not():
    """AC: A posted card from a dropped EPIF renders an Add items button, and an approved or later card does not."""
    req = _sample_epif_card_payload()

    # posted + source=epif -> renders Add items
    posted_blks = blocks.build_request_blocks("posted", req)
    action_block = [b for b in posted_blks if b.get("type") == "actions"][0]
    action_ids = [e.get("action_id") for e in action_block["elements"]]
    assert config.ACTION_REQ_ITEMS in action_ids

    items_btn = [e for e in action_block["elements"] if e.get("action_id") == config.ACTION_REQ_ITEMS][0]
    assert items_btn["text"]["text"] == "Add items"

    # approved, processed, confirmed, delivered -> do NOT render Add items
    for st in ("approved", "processed", "confirmed", "delivered"):
        blks = blocks.build_request_blocks(st, req)
        action_blocks = [b for b in blks if b.get("type") == "actions"]
        if action_blocks:
            elem_ids = [e.get("action_id") for e in action_blocks[0]["elements"]]
            assert config.ACTION_REQ_ITEMS not in elem_ids

    # posted + source=modal -> does NOT render Add items (modal path handled in ticket 28)
    modal_req = _sample_epif_card_payload()
    modal_req["source"] = "modal"
    modal_blks = blocks.build_request_blocks("posted", modal_req)
    modal_action = [b for b in modal_blks if b.get("type") == "actions"][0]
    modal_action_ids = [e.get("action_id") for e in modal_action["elements"]]
    assert config.ACTION_REQ_ITEMS not in modal_action_ids


# ---------------------------------------------------------------------------
# 2 & 3. Submitting valid paste stores items in metadata, NOT in button value
# ---------------------------------------------------------------------------

def test_submitting_valid_paste_stores_items_and_shipping_in_metadata_and_not_in_button_value(monkeypatch):
    """AC: Submitting a valid paste stores the items and shipping in that card message's metadata.

    AC: The button value on the updated card contains no line items — asserted on value's contents.
    """
    card_payload = _sample_epif_card_payload(total_price=100.0)
    msg = _make_thread_message(card_payload)

    client = MagicMock()
    client.conversations_replies.return_value = {"ok": True, "messages": [msg]}

    ack = MagicMock()
    body = {"user": {"id": "U_ISAAC"}}
    view = {
        "private_metadata": json.dumps({
            "channel": "C123",
            "thread_ts": "1000.1000",
            "card_ts": "1000.1000",
        }),
        "state": {
            "values": {
                "block_line_items": {
                    "action_line_items": {
                        "value": (
                            "2 | Couplings | C-1 | 40.00 | | Two couplings\n"
                            "1 | Set Screws | SS-2 | 10.00 | | Screws\n"
                            "shipping | 10.00\n"
                        )
                    }
                }
            }
        },
    }

    app.handle_items_modal_submit(ack, body, client, view)

    ack.assert_called_once_with()
    client.chat_update.assert_called_once()
    update_kwargs = client.chat_update.call_args[1]

    # Verify metadata contains items and shipping
    assert "metadata" in update_kwargs
    meta = update_kwargs["metadata"]
    assert meta["event_type"] == "purchase_request"
    stored_payload = meta["event_payload"]
    assert len(stored_payload["items"]) == 2
    assert stored_payload["items"][0]["name"] == "Couplings"
    assert stored_payload["items"][0]["qty"] == 2
    assert stored_payload["items"][0]["unit_price"] == 40.0
    assert stored_payload["shipping"] == 10.0

    # Verify button value contains NO line items (asserted on value contents)
    updated_blocks = update_kwargs["blocks"]
    action_block = [b for b in updated_blocks if b.get("type") == "actions"][0]
    for elem in action_block["elements"]:
        if elem.get("type") == "button":
            val_str = elem.get("value")
            assert val_str, "Button must have a value"
            val_dict = json.loads(val_str)
            assert "items" not in val_dict
            assert "shipping" not in val_dict
            req_in_val = val_dict.get("request", {})
            assert "items" not in req_in_val
            assert "shipping" not in req_in_val


# ---------------------------------------------------------------------------
# 4. Summary names line items count for 2+, says nothing for 1 item
# ---------------------------------------------------------------------------

def test_updated_card_summary_line_items_count():
    """AC: The updated card summary names the number of line items when there are two or more,

    and says nothing extra for one item.
    """
    card_payload = _sample_epif_card_payload()

    items_5 = [
        {"qty": 1, "name": f"Item {i}", "part_number": f"P{i}", "unit_price": 20.0, "link": "", "description": ""}
        for i in range(5)
    ]
    blks_5 = blocks.build_request_blocks("posted", card_payload, items=items_5)
    summary_text_5 = blks_5[0]["text"]["text"]
    assert "📋 5 line items (BOM attached in thread)" in summary_text_5

    items_2 = [
        {"qty": 1, "name": "Item 1", "part_number": "P1", "unit_price": 50.0, "link": "", "description": ""},
        {"qty": 1, "name": "Item 2", "part_number": "P2", "unit_price": 50.0, "link": "", "description": ""},
    ]
    blks_2 = blocks.build_request_blocks("posted", card_payload, items=items_2)
    summary_text_2 = blks_2[0]["text"]["text"]
    assert "📋 2 line items (BOM attached in thread)" in summary_text_2

    items_1 = [
        {"qty": 10, "name": "Item 1", "part_number": "P1", "unit_price": 10.0, "link": "", "description": ""},
    ]
    blks_1 = blocks.build_request_blocks("posted", card_payload, items=items_1)
    summary_text_1 = blks_1[0]["text"]["text"]
    assert "line items" not in summary_text_1
    assert "BOM" not in summary_text_1


# ---------------------------------------------------------------------------
# 5 & 6. Two or more items upload draft spreadsheet; one item does not. Not saved to BOMS_DIR.
# ---------------------------------------------------------------------------

def test_two_or_more_items_upload_draft_spreadsheet_and_one_item_uploads_nothing(tmp_path, monkeypatch):
    """AC: Two or more items cause a draft spreadsheet to be uploaded into the thread; one item uploads nothing.

    AC: The draft file is not written to BOMS_DIR.
    """
    monkeypatch.setattr(config, "BOMS_DIR", str(tmp_path))

    # Case A: 2 items -> draft spreadsheet uploaded
    card_payload_2 = _sample_epif_card_payload(total_price=100.0)
    msg_2 = _make_thread_message(card_payload_2)

    client_2 = MagicMock()
    client_2.conversations_replies.return_value = {"ok": True, "messages": [msg_2]}

    ack = MagicMock()
    body = {"user": {"id": "U_ISAAC"}}
    view_2 = {
        "private_metadata": json.dumps({"channel": "C1", "thread_ts": "1000.1000", "card_ts": "1000.1000"}),
        "state": {
            "values": {
                "block_line_items": {
                    "action_line_items": {
                        "value": "1 | Part A | PA | 60.00\n1 | Part B | PB | 40.00"
                    }
                }
            }
        },
    }

    app.handle_items_modal_submit(ack, body, client_2, view_2)

    client_2.files_upload_v2.assert_called_once()
    upload_kwargs = client_2.files_upload_v2.call_args[1]
    assert upload_kwargs["channel"] == "C1"
    assert upload_kwargs["thread_ts"] == "1000.1000"
    assert upload_kwargs["filename"] == "DRAFT_Ruland_BOM.xlsx"
    xlsx_bytes = upload_kwargs["content"]
    assert isinstance(xlsx_bytes, bytes)

    # Verify it opens with openpyxl
    wb = openpyxl.load_workbook(io.BytesIO(xlsx_bytes))
    assert "BOM" in wb.sheetnames

    # Assert BOMS_DIR is empty (not written to disk)
    assert os.listdir(str(tmp_path)) == []

    # Case B: 1 item -> no draft upload
    card_payload_1 = _sample_epif_card_payload(total_price=100.0)
    msg_1 = _make_thread_message(card_payload_1)

    client_1 = MagicMock()
    client_1.conversations_replies.return_value = {"ok": True, "messages": [msg_1]}

    view_1 = {
        "private_metadata": json.dumps({"channel": "C1", "thread_ts": "1000.1000", "card_ts": "1000.1000"}),
        "state": {
            "values": {
                "block_line_items": {
                    "action_line_items": {
                        "value": "10 | Part A | PA | 10.00"
                    }
                }
            }
        },
    }

    ack_1 = MagicMock()
    app.handle_items_modal_submit(ack_1, body, client_1, view_1)

    client_1.files_upload_v2.assert_not_called()
    assert os.listdir(str(tmp_path)) == []


# ---------------------------------------------------------------------------
# 7. Totals mismatch refused inside modal, naming both numbers, card untouched
# ---------------------------------------------------------------------------

def test_totals_mismatch_refused_inside_modal_naming_both_numbers_card_untouched():
    """AC: A paste whose totals disagree with the EPIF amount is refused inside the modal,

    naming both numbers, with no metadata change, no upload and no card update — asserted on the absence.
    """
    card_payload = _sample_epif_card_payload(total_price=412.00)
    msg = _make_thread_message(card_payload)

    client = MagicMock()
    client.conversations_replies.return_value = {"ok": True, "messages": [msg]}

    ack = MagicMock()
    body = {"user": {"id": "U_ISAAC"}}
    # Paste totals $455.50 vs EPIF $412.00
    view = {
        "private_metadata": json.dumps({"channel": "C1", "thread_ts": "1000.1000", "card_ts": "1000.1000"}),
        "state": {
            "values": {
                "block_line_items": {
                    "action_line_items": {
                        "value": "5 | Part | P1 | 91.10"
                    }
                }
            }
        },
    }

    app.handle_items_modal_submit(ack, body, client, view)

    # Refused inside modal with both numbers
    ack.assert_called_once()
    call_kwargs = ack.call_args[1]
    assert call_kwargs.get("response_action") == "errors"
    err_text = call_kwargs["errors"]["block_line_items"]
    assert "$455.50" in err_text
    assert "$412.00" in err_text

    # Asserted on absence: no metadata change, no upload, no card update, no thread post
    client.chat_update.assert_not_called()
    client.files_upload_v2.assert_not_called()
    client.chat_postMessage.assert_not_called()


# ---------------------------------------------------------------------------
# 8. Bad line refused inside modal with line number, card untouched
# ---------------------------------------------------------------------------

def test_bad_line_refused_inside_modal_with_line_number_card_untouched():
    """AC: A paste with a bad line is refused inside the modal with the line-numbered error,

    and the card is untouched.
    """
    card_payload = _sample_epif_card_payload(total_price=100.0)
    msg = _make_thread_message(card_payload)

    client = MagicMock()
    client.conversations_replies.return_value = {"ok": True, "messages": [msg]}

    ack = MagicMock()
    body = {"user": {"id": "U_ISAAC"}}
    # Line 2 has invalid unit price
    view = {
        "private_metadata": json.dumps({"channel": "C1", "thread_ts": "1000.1000", "card_ts": "1000.1000"}),
        "state": {
            "values": {
                "block_line_items": {
                    "action_line_items": {
                        "value": (
                            "1 | Item 1 | P1 | 50.00\n"
                            "1 | Item 2 | P2 | invalid_price\n"
                        )
                    }
                }
            }
        },
    }

    app.handle_items_modal_submit(ack, body, client, view)

    ack.assert_called_once()
    call_kwargs = ack.call_args[1]
    assert call_kwargs.get("response_action") == "errors"
    err_text = call_kwargs["errors"]["block_line_items"]
    assert "line 2" in err_text

    # Card untouched
    client.chat_update.assert_not_called()
    client.files_upload_v2.assert_not_called()
    client.chat_postMessage.assert_not_called()


# ---------------------------------------------------------------------------
# 9. Re-opening button once items exist pre-fills box and reads Edit items
# ---------------------------------------------------------------------------

def test_reopening_button_once_items_exist_prefills_box_and_reads_edit_items():
    """AC: Re-opening the button once items exist pre-fills the box with the current items

    and reads Edit items.
    """
    items = [
        {"qty": 2, "name": "Coupling", "part_number": "C-1", "unit_price": 40.0, "link": "https://example.com/c1", "description": "Desc"},
        {"qty": 1, "name": "Collar", "part_number": "C-2", "unit_price": 20.0, "link": "", "description": ""},
    ]
    card_payload = _sample_epif_card_payload(items=items, shipping=0.0, total_price=100.0)

    # 1. Card button reads "Edit items"
    blks = blocks.build_request_blocks("posted", card_payload, items=items)
    action_block = [b for b in blks if b.get("type") == "actions"][0]
    items_btn = [e for e in action_block["elements"] if e.get("action_id") == config.ACTION_REQ_ITEMS][0]
    assert items_btn["text"]["text"] == "Edit items"

    # 2. Clicking button opens modal pre-filled with items
    msg = _make_thread_message(card_payload)
    client = MagicMock()
    client.conversations_replies.return_value = {"ok": True, "messages": [msg]}

    ack = MagicMock()
    respond = MagicMock()
    body = {
        "user": {"id": "U_ISAAC"},
        "channel": {"id": "C1"},
        "trigger_id": "trig_123",
        "container": {"message_ts": "1000.1000", "thread_ts": "1000.1000"},
    }

    app.handle_req_items_action(ack, body, respond, client)

    ack.assert_called_once()
    client.views_open.assert_called_once()
    open_kwargs = client.views_open.call_args[1]
    modal_view = open_kwargs["view"]
    assert open_kwargs["trigger_id"] == "trig_123"

    input_elem = modal_view["blocks"][0]["element"]
    initial_val = input_elem.get("initial_value", "")
    assert "2 | Coupling | C-1 | 40.00" in initial_val
    assert "1 | Collar | C-2 | 20.00" in initial_val


# ---------------------------------------------------------------------------
# 10. Re-submitting different items replaces stored items and re-posts draft BOM
# ---------------------------------------------------------------------------

def test_resubmitting_different_items_replaces_stored_items_and_reposts_draft_spreadsheet():
    """AC: Re-submitting different items replaces the stored items and re-posts the draft spreadsheet."""
    initial_items = [
        {"qty": 2, "name": "Coupling", "part_number": "C-1", "unit_price": 50.0, "link": "", "description": ""},
    ]
    card_payload = _sample_epif_card_payload(items=initial_items, shipping=0.0, total_price=100.0)
    msg = _make_thread_message(card_payload)

    client = MagicMock()
    client.conversations_replies.return_value = {"ok": True, "messages": [msg]}

    ack = MagicMock()
    body = {"user": {"id": "U_ISAAC"}}
    # Re-submit with 3 different items adding up to $100.00
    new_paste = (
        "1 | Part A | PA | 30.00\n"
        "1 | Part B | PB | 30.00\n"
        "1 | Part C | PC | 40.00\n"
    )
    view = {
        "private_metadata": json.dumps({"channel": "C1", "thread_ts": "1000.1000", "card_ts": "1000.1000"}),
        "state": {
            "values": {
                "block_line_items": {
                    "action_line_items": {
                        "value": new_paste,
                    }
                }
            }
        },
    }

    app.handle_items_modal_submit(ack, body, client, view)

    ack.assert_called_once_with()

    # Replaces stored items in metadata
    client.chat_update.assert_called_once()
    stored_items = client.chat_update.call_args[1]["metadata"]["event_payload"]["items"]
    assert len(stored_items) == 3
    assert [it["name"] for it in stored_items] == ["Part A", "Part B", "Part C"]

    # Re-posts draft spreadsheet
    client.files_upload_v2.assert_called_once()
    assert client.files_upload_v2.call_args[1]["filename"] == "DRAFT_Ruland_BOM.xlsx"

    # Posts edit notice to thread
    client.chat_postMessage.assert_called_once()
    post_text = client.chat_postMessage.call_args[1]["text"]
    assert "✏️ Edited by" in post_text
    assert "items 1 → 3" in post_text


# ---------------------------------------------------------------------------
# 11. Reading card payload in multi-card thread returns clicked card, not newest
# ---------------------------------------------------------------------------

def test_reading_card_payload_multi_card_thread_returns_clicked_card_not_newest():
    """AC: Reading a card's items in a thread holding two cards returns the items

    of the card that was clicked, not the newest card.
    """
    items_card1 = [{"qty": 1, "name": "Item Card 1", "part_number": "C1", "unit_price": 50.0, "link": "", "description": ""}]
    items_card2 = [{"qty": 2, "name": "Item Card 2", "part_number": "C2", "unit_price": 25.0, "link": "", "description": ""}]

    payload1 = _sample_epif_card_payload(items=items_card1, ts="100.1", thread_ts="100.1")
    payload2 = _sample_epif_card_payload(items=items_card2, ts="100.2", thread_ts="100.1")

    msg1 = _make_thread_message(payload1, ts="100.1", thread_ts="100.1")
    msg2 = _make_thread_message(payload2, ts="100.2", thread_ts="100.1")

    # In thread replies, both messages are present
    client = MagicMock()
    client.conversations_replies.return_value = {"ok": True, "messages": [msg1, msg2]}

    # Click card 1
    retrieved_1 = slack_io.get_card_payload(client, "C_TEST", "100.1", "100.1")
    assert retrieved_1 is not None
    assert retrieved_1["items"] == items_card1

    # Click card 2
    retrieved_2 = slack_io.get_card_payload(client, "C_TEST", "100.1", "100.2")
    assert retrieved_2 is not None
    assert retrieved_2["items"] == items_card2


# ---------------------------------------------------------------------------
# 12. Dropped EPIF sets source='epif'
# ---------------------------------------------------------------------------

def test_dropped_epif_sets_source_epif(monkeypatch):
    """Verify handle_epif_drop marks card metadata with source='epif'."""
    client = MagicMock()
    file_obj = {"name": "test.pdf", "url_private_download": "https://example.com/test.pdf"}

    monkeypatch.setattr(lifecycle.slack_io, "download", lambda f: b"%PDF-1.4 dummy")
    dummy_parsed = {
        "item_description": "Widgets",
        "total_price": 50.0,
        "vendor": "Acme",
        "payment_method": "EPIF",
        "category": "Research/Lab Supplies (3105)",
        "project_id": "PG000025831",
        "fund": "133",
        "delivery_room": "ERB 212",
        "purpose": "Testing",
        "date_of_purchase": None,
    }
    monkeypatch.setattr(lifecycle.epif_parser, "parse_epif", lambda content: dummy_parsed)
    monkeypatch.setattr(lifecycle.slack_io, "resolve_requester", lambda c, uid: "Isaac")

    say = MagicMock()
    lifecycle.handle_epif_drop(client, say, "C_PURCHASING", "1000.1000", "U_ISAAC", file_obj, "1000.1000")

    client.chat_postMessage.assert_called_once()
    posted_meta = client.chat_postMessage.call_args[1]["metadata"]
    assert posted_meta["event_payload"]["source"] == "epif"


# ---------------------------------------------------------------------------
# 13. Permission denial on Add items leaves card intact
# ---------------------------------------------------------------------------

def test_permission_denial_on_add_items_leaves_card_intact(monkeypatch):
    """Unauthorized user clicking Add items is denied ephemerally without opening modal."""
    card_payload = _sample_epif_card_payload(user_id="U_OWNER", requester="Owner")
    msg = _make_thread_message(card_payload)

    client = MagicMock()
    client.conversations_replies.return_value = {"ok": True, "messages": [msg]}

    ack = MagicMock()
    respond = MagicMock()
    body = {
        "user": {"id": "U_STRANGER"},
        "channel": {"id": "C1"},
        "trigger_id": "trig_stranger",
        "container": {"message_ts": "1000.1000", "thread_ts": "1000.1000"},
    }

    # U_STRANGER is not owner, not buyer, not admin
    app.handle_req_items_action(ack, body, respond, client)

    ack.assert_called_once()
    respond.assert_called_once()
    resp_kwargs = respond.call_args[1]
    assert resp_kwargs.get("response_type") == "ephemeral"
    assert resp_kwargs.get("replace_original") is False
    assert "Only the requester, a buyer, or an admin" in resp_kwargs["text"]

    client.views_open.assert_not_called()
    client.chat_update.assert_not_called()
