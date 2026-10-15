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
import json
from unittest.mock import MagicMock

import pytest

from src import app, config, roster


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

# ---------------------------------------------------------------------------
# 5. Totals mismatch refused on items box, no card posted
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# 6. Line-numbered parse error shown on items box, no card posted
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# 7. Max length 1500 chars + Fabrication category completes Screen 3 and posts
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# 8. One-item paste posts card with items in metadata, but NO spreadsheet
# ---------------------------------------------------------------------------

