import pytest

from src import blocks


def test_request_summary_lines_all_fields():
    """
    Calls blocks.request_summary_lines on a request with every field set
    (link, buyer, expected delivery, three line items so bom.needs_bom is true,
    one bom attachment and two quote attachments).
    Asserts the exact list of lines.
    """
    request = {
        "parsed": {
            "item_description": "My Test Item",
            "total_price": "$1,234.56",
            "vendor": "Test Vendor",
            "payment_method": "Req/PO",
            "category": "Lab Consumable",
            "project_id": "PRJ-123",
            "fund": "FND-456",
            "delivery_room": "Room 101",
            "purpose": "Test purpose",
            "link": "https://example.com/test",
        },
        "requester": "Test Requester",
        "assignee_id": "U12345",
        "assignee": "Test Buyer",
        "expected_delivery": "2026-11-16",
        "items": [
            {"qty": 1, "description": "item 1", "price": 10},
            {"qty": 1, "description": "item 2", "price": 10},
            {"qty": 1, "description": "item 3", "price": 10},
        ],
        "attachments": [
            {"role": "bom", "name": "test_bom.xlsx"},
            {"role": "quote", "id": "q1", "name": "quote1.pdf"},
            {"role": "quote", "id": "q2", "name": "quote2.pdf"},
        ]
    }

    expected_lines = [
        "🛒 *New Purchase Request from Test Requester:*",
        "• *Item:* My Test Item",
        "• *Total:* $1,234.56",
        "• *Vendor:* Test Vendor (Req/PO)",
        "• *Category:* Lab Consumable",
        "• *Project ID / Fund:* PRJ-123 (Fund FND-456)",
        "• *Delivery Room:* Room 101",
        "• *Purpose:* Test purpose",
        "• *Link:* https://example.com/test",
        "• *Buyer:* <@U12345> (Test Buyer)",
        "• *Expected delivery:* Nov 16",
        "📋 3 line items (BOM attached in thread)",
        "📎 BOM attached: test_bom.xlsx",
        "📎 Quotes: 2"
    ]

    lines = blocks.request_summary_lines(
        request=request,
        state="approved",
        requester=request["requester"],
        items=request["items"],
        attachments=request["attachments"]
    )

    assert lines == expected_lines

@pytest.mark.parametrize("state", [
    "posted", "approved", "processed", "confirmed", "delivered", "declined", "cancelled", "waiting_for_details"
])
def test_build_request_blocks_uses_summary_lines(state):
    """
    For each state, the section text of blocks.build_request_blocks equals
    the joined lines from blocks.request_summary_lines.
    Also verifies unassigned requests in non-posted states include a warning,
    but posted does not.
    """
    request = {
        "parsed": {
            "item_description": "My Test Item",
            "total_price": "$1,234.56",
            "vendor": "Test Vendor",
            "payment_method": "Req/PO",
            "category": "Lab Consumable",
            "project_id": "PRJ-123",
            "fund": "FND-456",
            "delivery_room": "Room 101",
            "purpose": "Test purpose",
        },
        "requester": "Test Requester",
        # intentionally omitted assignee
    }

    b_list = blocks.build_request_blocks(state=state, request=request, history=["Hist 1", "Hist 2"])

    # section text is in the first block
    section_text = b_list[0]["text"]["text"]

    expected_lines = blocks.request_summary_lines(request=request, state=state)
    expected_text = "\n".join(expected_lines)

    assert section_text == expected_text

    # Unassigned check
    if state != "posted":
        assert "• *Buyer:* ⚠️ _Unassigned_" in expected_text
    else:
        assert "• *Buyer:* ⚠️ _Unassigned_" not in expected_text
