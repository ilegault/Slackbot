from src import blocks


def test_request_summary_lines_all_fields():
    request = {
        "user_id": "U123",
        "requester": "Bob",
        "parsed": {
            "item_description": "Widgets",
            "total_price": 500.00,
            "vendor": "Acme Corp",
            "payment_method": "EPIF",
            "category": "Lab Consumable",
            "project_id": "P123",
            "fund": "F456",
            "delivery_room": "Room 101",
            "purpose": "Science",
            "link": "https://example.com/widgets",
        },
        "assignee_id": "U456",
        "assignee": "Alice",
        "expected_delivery": "2026-10-15",
        "suggest_note": "A note",
    }
    items = [
        {"description": "Item 1", "quantity": 1},
        {"description": "Item 2", "quantity": 2},
        {"description": "Item 3", "quantity": 3},
    ]
    attachments = [
        {"role": "bom", "name": "BOM.xlsx"},
        {"role": "quote", "name": "Quote1.pdf"},
        {"role": "quote", "name": "Quote2.pdf"},
    ]

    lines = blocks.request_summary_lines(request, "approved", items=items, attachments=attachments)

    expected = [
        "🛒 *New Purchase Request from Bob:*",
        "• *Item:* Widgets",
        "• *Total:* $500.00",
        "• *Vendor:* Acme Corp (EPIF)",
        "• *Category:* Lab Consumable",
        "• *Project ID / Fund:* P123 (Fund F456)",
        "• *Delivery Room:* Room 101",
        "• *Purpose:* Science",
        "• *Link:* https://example.com/widgets",
        "• *Buyer:* <@U456> (Alice)",
        "• *Expected delivery:* Oct 15",
        "📋 3 line items (BOM attached in thread)",
        "📎 BOM attached: BOM.xlsx",
        "📎 Quotes: 2",
        "A note"
    ]
    assert lines == expected

def test_request_summary_lines_states():
    request = {
        "user_id": "U123",
        "requester": "Bob",
        "parsed": {
            "item_description": "Widgets",
            "total_price": 500.00,
            "vendor": "Acme Corp",
        }
    }

    states = ["posted", "approved", "processed", "confirmed", "delivered", "declined", "cancelled", "waiting_for_details"]

    for state in states:
        expected_text = "\n".join(blocks.request_summary_lines(request, state))

        # In build_request_blocks, the first block is a section containing the text.
        built = blocks.build_request_blocks(state, request)
        actual_text = built[0]["text"]["text"]

        assert actual_text == expected_text

        if state == "posted":
            assert "• *Buyer:* ⚠️ _Unassigned_" not in expected_text
        else:
            assert "• *Buyer:* ⚠️ _Unassigned_" in expected_text
