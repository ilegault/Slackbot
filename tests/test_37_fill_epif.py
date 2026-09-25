import datetime

from src import config, epif_filler, epif_parser


def test_fill_epif_round_trip():
    with open("tests/fixtures/EPIF_TEMPLATE_HIRST.pdf", "rb") as f:
        template = f.read()

    parsed = {
        "item_description": "Laser component",
        "purpose": "For the laser",
        "total_price": 2799.0,
        "total_price_raw": "$2,799",
        "vendor": "Test Vendor",
        "vendor_contact_name": "John Doe",
        "vendor_contact_email": "john@test.com",
        "date_of_purchase": datetime.date(2026, 9, 22),
        "name_of_system": "Laser System",
        "delivery_room": "ERB 212",
        "project_id": "PG000025831",
        "fund": "133",
        "asset_id": "ASSET-123",
        "category": "Fabrication Component (4670) > $200",
        "payment_method": "P-card",
    }

    filled_bytes = epif_filler.fill_epif(template, parsed)
    round_tripped = epif_parser.parse_epif(filled_bytes)

    assert round_tripped["item_description"] == parsed["item_description"]
    assert round_tripped["purpose"] == parsed["purpose"]
    assert round_tripped["total_price"] == parsed["total_price"]
    assert round_tripped["vendor"] == parsed["vendor"]
    assert round_tripped["vendor_contact_name"] == parsed["vendor_contact_name"]
    assert round_tripped["vendor_contact_email"] == parsed["vendor_contact_email"]
    assert round_tripped["date_of_purchase"] == parsed["date_of_purchase"]
    assert round_tripped["name_of_system"] == parsed["name_of_system"]
    assert round_tripped["delivery_room"] == parsed["delivery_room"]
    assert round_tripped["project_id"] == parsed["project_id"]
    assert round_tripped["fund"] == parsed["fund"]
    assert round_tripped["asset_id"] == parsed["asset_id"]
    assert round_tripped["category"] == parsed["category"]
    assert round_tripped["payment_method"] == parsed["payment_method"]
    assert round_tripped["pi_of_funding"] == config.EPIF_PI_AND_END_USER
    assert round_tripped["end_user"] == config.EPIF_PI_AND_END_USER


def test_fill_epif_bom_round_trip():
    with open("tests/fixtures/EPIF_TEMPLATE_HIRST.pdf", "rb") as f:
        template = f.read()

    parsed = {
        "items": [
            {"name": "Item 1", "price": 10},
            {"name": "Item 2", "price": 20},
            {"name": "Item 3", "price": 30},
        ],
        "total_price": 60.0,
        "vendor": "Winford",
        "category": "Other",
        "payment_method": "Req/PO",
    }

    filled_bytes = epif_filler.fill_epif(template, parsed)
    round_tripped = epif_parser.parse_epif(filled_bytes)

    assert round_tripped["item_description"] == "See attached BOM — 3 items"
    assert round_tripped["total_price"] == 60.0
    assert round_tripped["vendor"] == "Winford"
    assert round_tripped["category"] == "Other"
    assert round_tripped["payment_method"] == "Req/PO"
    assert round_tripped["pi_of_funding"] == config.EPIF_PI_AND_END_USER
    assert round_tripped["end_user"] == config.EPIF_PI_AND_END_USER
