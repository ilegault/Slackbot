"""Tests for Ticket 28: Line items on /new-purchase.

WHY THIS EXISTS:
----------------
Covers the modal interview path for multi-item orders (ADR 0006 decisions 1-4):
1. Screen 2 renders an optional multiline Line items input with hint and 1500-char limit.
2. Empty items box completes interview exactly as before — no 'items' key in metadata, no upload.
3. Valid paste stores items and shipping in posted card metadata, and names line items on the card.
4. Button value never contains line items (metadata is the store).
5. Two or more items cause a draft spreadsheet to be uploaded to thread right after the card.
6. Paste whose totals disagree with Total Price is refused on block_line_items, no card posted.
7. Line-numbered parse error is shown on block_line_items, no card posted.
8. Maximum length is 1500 chars; a full box + Fabrication category completes Screen 3 and posts.
9. One-item paste posts card with items in metadata but NO draft spreadsheet.
"""
import io
import json
from unittest.mock import MagicMock

import openpyxl
import pytest

from src import app, blocks, config, roster


@pytest.fixture(autouse=True)
def isolate_roster(tmp_path, monkeypatch):
    """Ensure tests run against a clean isolated roster.json copy."""
    test_roster_file = str(tmp_path / "roster.json")
    monkeypatch.setattr(roster, "ROSTER_PATH", test_roster_file)
    roster.load_roster()
    return test_roster_file


def _sample_stage1_meta(
    vendor_choice="DigiKey",
    vendor_custom="",
    route="workday",
    resolved_name="Isaac",
    user_id="U_ISAAC",
    is_pending_name=False,
):
    return {
        "vendor_choice": vendor_choice,
        "vendor_custom": vendor_custom,
        "route": route,
        "resolved_name": resolved_name,
        "user_id": user_id,
        "is_pending_name": is_pending_name,
    }


def _make_stage2_view_submission(
    meta: dict,
    total_price: str = "100.00",
    item_description: str = "Electronic components",
    purpose: str = "Sensor instrumentation",
    link: str = "https://example.com/parts",
    category: str = "Research/Lab Supplies (3105)",
    project_id: str = "PG000025831",
    fund: str = "144",
    delivery_room: str = "ERB 212",
    vendor_contact_name: str = "Rep",
    vendor_contact_email: str = "rep@digikey.com",
    date_of_purchase: str = "2026-09-22",
    payment_method: str = "Workday",
    line_items: str = "",
):
    values = {
        "block_item_description": {
            "item_description": {"type": "plain_text_input", "value": item_description}
        },
        "block_purpose": {
            "purpose": {"type": "plain_text_input", "value": purpose}
        },
        "block_link": {
            "link": {"type": "plain_text_input", "value": link}
        },
        "block_total_price": {
            "total_price": {"type": "plain_text_input", "value": total_price}
        },
        "block_vendor_contact_name": {
            "vendor_contact_name": {"type": "plain_text_input", "value": vendor_contact_name}
        },
        "block_vendor_contact_email": {
            "vendor_contact_email": {"type": "plain_text_input", "value": vendor_contact_email}
        },
        "block_date_of_purchase": {
            "date_of_purchase": {"type": "datepicker", "selected_date": date_of_purchase}
        },
        "block_delivery_room": {
            "delivery_room": {"type": "static_select", "selected_option": {"value": delivery_room}}
        },
        "block_project_id": {
            "project_id": {"type": "static_select", "selected_option": {"value": project_id}}
        },
        "block_fund": {
            "fund": {"type": "static_select", "selected_option": {"value": fund}}
        },
        "block_category": {
            "category": {"type": "static_select", "selected_option": {"value": category}}
        },
    }
    if meta.get("route") == "epif":
        values["block_payment_method"] = {
            "payment_method": {"type": "static_select", "selected_option": {"value": payment_method}}
        }
    if line_items is not None:
        values["block_line_items"] = {
            "line_items": {"type": "plain_text_input", "value": line_items}
        }
    return {
        "private_metadata": json.dumps(meta),
        "state": {"values": values},
    }


# ---------------------------------------------------------------------------
# 1. Screen 2 renders optional multiline Line items input with hint
# ---------------------------------------------------------------------------

def test_screen2_renders_optional_multiline_line_items_input():
    """AC: Screen 2 renders an optional multiline Line items input with a hint naming format and shipping line."""
    meta = _sample_stage1_meta()
    view = blocks.build_stage2_view(meta)
    blk_map = {b.get("block_id"): b for b in view.get("blocks", [])}

    assert "block_line_items" in blk_map, "block_line_items must be present in Stage 2 blocks"
    block = blk_map["block_line_items"]
    assert block.get("type") == "input"
    assert block.get("optional") is True

    elem = block.get("element", {})
    assert elem.get("type") == "plain_text_input"
    assert elem.get("multiline") is True
    assert elem.get("max_length") == config.MAX_LINE_ITEMS_LEN
    assert config.MAX_LINE_ITEMS_LEN == 1500

    label = block.get("label", {}).get("text", "")
    assert "Line items" in label

    hint = block.get("hint", {}).get("text", "")
    assert "qty | name | part #" in hint
    assert "shipping |" in hint


# ---------------------------------------------------------------------------
# 2. Empty items box completes interview as before (no metadata key, no upload)
# ---------------------------------------------------------------------------

def test_empty_items_box_completes_interview_without_items_key_or_upload(monkeypatch):
    """AC: An empty items box completes the interview exactly as before — no metadata key, no upload."""
    monkeypatch.setattr(config, "PURCHASING_CHANNEL", "C_PURCHASING")
    roster.add_requester("U_ISAAC", "Isaac")

    client = MagicMock()
    client.chat_postMessage.return_value = {"ok": True, "ts": "1000.1000"}

    ack = MagicMock()
    body = {"user": {"id": "U_ISAAC"}}
    meta = _sample_stage1_meta()
    view = _make_stage2_view_submission(meta, line_items="")

    app.handle_stage2_submit(ack, body, client, view)

    ack.assert_called_once_with()
    channel_calls = [c for c in client.chat_postMessage.call_args_list if c[1].get("channel") == "C_PURCHASING"]
    assert len(channel_calls) == 1
    call_kw = channel_calls[0][1]

    payload = call_kw["metadata"]["event_payload"]
    assert "items" not in payload, "Empty items box must not produce 'items' key in card metadata"
    assert "shipping" not in payload, "Empty items box must not produce 'shipping' key in card metadata"

    # Verify no draft spreadsheet was uploaded
    if hasattr(client, "files_upload_v2"):
        client.files_upload_v2.assert_not_called()
    client.files_upload.assert_not_called()


# ---------------------------------------------------------------------------
# 3 & 4. Valid paste stores items and shipping in metadata; 2+ items upload BOM
# ---------------------------------------------------------------------------

def test_valid_paste_stores_items_and_shipping_in_metadata_and_uploads_draft_bom(monkeypatch):
    """AC: A valid paste stores items and shipping in the posted card's metadata and names the line items on the card.

    AC: Two or more items post a draft spreadsheet into the thread right after the card.
    AC: Button value on posted card contains no line items.
    """
    monkeypatch.setattr(config, "PURCHASING_CHANNEL", "C_PURCHASING")
    roster.add_requester("U_ISAAC", "Isaac")

    client = MagicMock()
    client.chat_postMessage.return_value = {"ok": True, "ts": "2000.2000"}

    paste = (
        "2 | Resistors 10k | R-10K | 15.00 | https://example.com/r10k | Pack of 100\n"
        "1 | Capacitors 100uF | C-100U | 50.00 | https://example.com/c100u | Electrolytic\n"
        "shipping | 20.00"
    )
    # Total = (2 * 15.00) + (1 * 50.00) + 20.00 = 100.00

    ack = MagicMock()
    body = {"user": {"id": "U_ISAAC"}}
    meta = _sample_stage1_meta()
    view = _make_stage2_view_submission(meta, total_price="100.00", line_items=paste)

    app.handle_stage2_submit(ack, body, client, view)

    ack.assert_called_once_with()
    channel_calls = [c for c in client.chat_postMessage.call_args_list if c[1].get("channel") == "C_PURCHASING"]
    assert len(channel_calls) == 1
    call_kw = channel_calls[0][1]

    # Verify metadata
    payload = call_kw["metadata"]["event_payload"]
    assert "items" in payload
    assert len(payload["items"]) == 2
    assert payload["items"][0]["name"] == "Resistors 10k"
    assert payload["items"][0]["qty"] == 2
    assert payload["items"][0]["unit_price"] == 15.0
    assert payload["items"][1]["name"] == "Capacitors 100uF"
    assert payload["shipping"] == 20.0

    # Verify card summary names line items
    card_blocks = call_kw["blocks"]
    section = [b for b in card_blocks if b.get("type") == "section"][0]
    sec_text = section["text"]["text"]
    assert "📋 2 line items (BOM attached in thread)" in sec_text

    # Verify button value does NOT carry items
    actions = [b for b in card_blocks if b.get("type") == "actions"][0]
    for elem in actions["elements"]:
        val = elem.get("value")
        if val:
            parsed_val = json.loads(val)
            assert "items" not in parsed_val, "button value must never carry items"
            assert "items" not in parsed_val.get("request", {}), "button request payload must not carry items"

    # Verify draft BOM was uploaded to thread
    upload_mock = client.files_upload_v2 if hasattr(client, "files_upload_v2") else client.files_upload
    upload_mock.assert_called_once()
    upload_kw = upload_mock.call_args[1]
    assert upload_kw["thread_ts"] == "2000.2000"
    assert upload_kw["filename"].startswith("DRAFT_")
    assert upload_kw["filename"].endswith("_BOM.xlsx")

    # Verify openpyxl can read the uploaded bytes
    wb = openpyxl.load_workbook(io.BytesIO(upload_kw["content"]))
    ws = wb.active
    assert ws is not None
    # Row 1 header has DRAFT
    found_draft = any("DRAFT" in str(cell.value) for row in ws.iter_rows() for cell in row)
    assert found_draft, "Draft BOM workbook header must indicate DRAFT"


# ---------------------------------------------------------------------------
# 5. Totals mismatch refused on items box, no card posted
# ---------------------------------------------------------------------------

def test_totals_mismatch_refused_on_items_box_no_card_posted():
    """AC: A paste whose totals disagree with the Total Price field is refused on the items box, and no card is posted."""
    client = MagicMock()
    ack = MagicMock()
    body = {"user": {"id": "U_ISAAC"}}
    meta = _sample_stage1_meta()

    # Total is 100.00, but items sum to 60.00 (1*40 + 20)
    paste = (
        "1 | Widget | W-1 | 40.00\n"
        "shipping | 20.00"
    )
    view = _make_stage2_view_submission(meta, total_price="100.00", line_items=paste)

    app.handle_stage2_submit(ack, body, client, view)

    ack.assert_called_once()
    call_kw = ack.call_args[1]
    assert call_kw.get("response_action") == "errors"
    errors = call_kw.get("errors", {})
    assert "block_line_items" in errors
    assert "Line items total ($60.00) does not match request total ($100.00)" in errors["block_line_items"]

    # Assert NO card posted
    client.chat_postMessage.assert_not_called()
    client.files_upload.assert_not_called()
    if hasattr(client, "files_upload_v2"):
        client.files_upload_v2.assert_not_called()


# ---------------------------------------------------------------------------
# 6. Line-numbered parse error shown on items box, no card posted
# ---------------------------------------------------------------------------

def test_line_numbered_parse_error_refused_on_items_box_no_card_posted():
    """AC: A line-numbered parse error is shown on the items box, and no card is posted."""
    client = MagicMock()
    ack = MagicMock()
    body = {"user": {"id": "U_ISAAC"}}
    meta = _sample_stage1_meta()

    # Line 2 has bad unit price "xyz"
    paste = (
        "1 | Widget A | W-A | 25.00\n"
        "2 | Widget B | W-B | xyz\n"
        "shipping | 5.00"
    )
    view = _make_stage2_view_submission(meta, total_price="55.00", line_items=paste)

    app.handle_stage2_submit(ack, body, client, view)

    ack.assert_called_once()
    call_kw = ack.call_args[1]
    assert call_kw.get("response_action") == "errors"
    errors = call_kw.get("errors", {})
    assert "block_line_items" in errors
    assert 'line 2: unit price "xyz" is not a number' in errors["block_line_items"]

    client.chat_postMessage.assert_not_called()
    client.files_upload.assert_not_called()
    if hasattr(client, "files_upload_v2"):
        client.files_upload_v2.assert_not_called()


# ---------------------------------------------------------------------------
# 7. Max length 1500 chars + Fabrication category completes Screen 3 and posts
# ---------------------------------------------------------------------------

def test_items_box_1500_char_with_fabrication_completes_screen3_and_posts(monkeypatch):
    """AC: The items box carries its own maximum length, and a request with a full box plus a Fabrication category still completes Screen 3 and posts."""
    monkeypatch.setattr(config, "PURCHASING_CHANNEL", "C_PURCHASING")
    roster.add_requester("U_ISAAC", "Isaac")

    client = MagicMock()
    client.chat_postMessage.return_value = {"ok": True, "ts": "3000.3000"}

    # Build a valid line items paste close to 1500 chars
    # Each item line: "1 | Part Name XX | PART-XX | 10.00 | https://example.com/part-long-url-path-number-XX | Research description for XX"
    lines = []
    total_val = 0.0
    for i in range(12):
        qty = 1
        price = 10.00
        total_val += qty * price
        line = f"{qty} | Part Name {i:02d} | PART-{i:02d} | {price:.2f} | https://example.com/parts/{i:02d} | Description {i:02d}"
        lines.append(line)
    lines.append(f"shipping | {5.00:.2f}")
    total_val += 5.00

    base_paste = "\n".join(lines)
    diff = config.MAX_LINE_ITEMS_LEN - len(base_paste)
    if diff > 0:
        lines[11] += " " + ("X" * (diff - 1))
    paste = "\n".join(lines)
    assert len(paste) == 1500

    # Category is Fabrication which requires Screen 3
    fab_category = list(config.ASSET_REQUIRED_CATEGORIES)[0]
    meta = _sample_stage1_meta()
    view2 = _make_stage2_view_submission(
        meta,
        total_price=f"{total_val:.2f}",
        category=fab_category,
        line_items=paste,
    )

    ack2 = MagicMock()
    body = {"user": {"id": "U_ISAAC"}}

    # Submit Screen 2 -> advances to Screen 3
    app.handle_stage2_submit(ack2, body, client, view2)

    ack2.assert_called_once()
    ack2_kw = ack2.call_args[1]
    assert ack2_kw.get("response_action") == "update"
    stage3_view = ack2_kw.get("view", {})
    assert stage3_view.get("callback_id") == config.STAGE3_CALLBACK_ID

    # Verify private_metadata is under Slack's 3000-char limit!
    raw_meta3 = stage3_view.get("private_metadata", "")
    assert len(raw_meta3) < 3000, f"Carried metadata length {len(raw_meta3)} exceeds 3000 char Slack limit!"

    # Submit Screen 3
    ack3 = MagicMock()
    view3 = {
        "private_metadata": raw_meta3,
        "state": {
            "values": {
                "block_asset_id": {"asset_id": {"value": "AST-98765"}},
                "block_name_of_system": {"name_of_system": {"value": "High Vacuum Chamber"}},
            }
        },
    }

    app.handle_stage3_submit(ack3, body, client, view3)

    ack3.assert_called_once_with()
    channel_calls = [c for c in client.chat_postMessage.call_args_list if c[1].get("channel") == "C_PURCHASING"]
    assert len(channel_calls) == 1
    call_kw = channel_calls[0][1]
    payload = call_kw["metadata"]["event_payload"]
    assert len(payload["items"]) == 12
    assert payload["shipping"] == 5.0
    assert payload["parsed"]["asset_id"] == "AST-98765"
    assert payload["parsed"]["name_of_system"] == "High Vacuum Chamber"

    # Draft BOM upload called
    upload_mock = client.files_upload_v2 if hasattr(client, "files_upload_v2") else client.files_upload
    upload_mock.assert_called_once()


# ---------------------------------------------------------------------------
# 8. One-item paste posts card with items in metadata, but NO spreadsheet
# ---------------------------------------------------------------------------

def test_one_item_paste_posts_card_with_no_spreadsheet(monkeypatch):
    """AC: A one-item paste posts the card with no spreadsheet."""
    monkeypatch.setattr(config, "PURCHASING_CHANNEL", "C_PURCHASING")
    roster.add_requester("U_ISAAC", "Isaac")

    client = MagicMock()
    client.chat_postMessage.return_value = {"ok": True, "ts": "4000.4000"}

    paste = "10 | Flange Bolts | F-BOLT | 5.00\nshipping | 0.00"
    # Total = 50.00

    ack = MagicMock()
    body = {"user": {"id": "U_ISAAC"}}
    meta = _sample_stage1_meta()
    view = _make_stage2_view_submission(meta, total_price="50.00", line_items=paste)

    app.handle_stage2_submit(ack, body, client, view)

    ack.assert_called_once_with()
    channel_calls = [c for c in client.chat_postMessage.call_args_list if c[1].get("channel") == "C_PURCHASING"]
    assert len(channel_calls) == 1
    call_kw = channel_calls[0][1]

    payload = call_kw["metadata"]["event_payload"]
    assert "items" in payload
    assert len(payload["items"]) == 1

    # Single item must NOT display the multi-item summary line
    card_blocks = call_kw["blocks"]
    section = [b for b in card_blocks if b.get("type") == "section"][0]
    assert "BOM attached in thread" not in section["text"]["text"]

    # NO spreadsheet uploaded
    client.files_upload.assert_not_called()
    if hasattr(client, "files_upload_v2"):
        client.files_upload_v2.assert_not_called()
