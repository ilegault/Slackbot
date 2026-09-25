import datetime
import os

import pytest

from src import config
from src.epif_filler import fill_epif
from src.epif_parser import parse_epif

FIXTURE_PATH = os.path.join(
    os.path.dirname(__file__), "fixtures", "EPIF_TEMPLATE_HIRST.pdf"
)

@pytest.fixture
def template_bytes():
    with open(FIXTURE_PATH, "rb") as f:
        return f.read()

def test_fill_epif_round_trip(template_bytes):
    """
    Test round-trip across all categories and both payment methods.
    """
    base_parsed = {
        "item_description": "Some lab supplies",
        "purpose": "To do research at the university",
        "total_price": 2799.50,
        "vendor": "Airgas",
        "vendor_contact_name": "John Doe",
        "vendor_contact_email": "john@airgas.com",
        "date_of_purchase": datetime.date(2026, 9, 23),
        "name_of_system": "Spectrometer",
        "delivery_room": "ERB 212",
        "project_id": "PG000025831",
        "fund": "133",
        "asset_id": "ASSET-999",
    }

    # Test for each category and payment method combination
    payment_methods = ["P-card", "Req/PO"]
    categories = list(config.CHECKBOX_TO_CATEGORY.values())

    for category in categories:
        for payment_method in payment_methods:
            parsed_in = base_parsed.copy()
            parsed_in["category"] = category
            parsed_in["payment_method"] = payment_method

            filled_bytes = fill_epif(template_bytes, parsed_in)
            parsed_out = parse_epif(filled_bytes)

            assert parsed_out["item_description"] == parsed_in["item_description"]
            assert parsed_out["purpose"] == parsed_in["purpose"]
            assert parsed_out["total_price"] == parsed_in["total_price"]
            assert parsed_out["vendor"] == parsed_in["vendor"]
            assert parsed_out["vendor_contact_name"] == parsed_in["vendor_contact_name"]
            assert parsed_out["vendor_contact_email"] == parsed_in["vendor_contact_email"]
            assert parsed_out["date_of_purchase"] == parsed_in["date_of_purchase"]
            assert parsed_out["delivery_room"] == parsed_in["delivery_room"]
            assert parsed_out["project_id"] == parsed_in["project_id"]
            assert parsed_out["fund"] == parsed_in["fund"]
            assert parsed_out["asset_id"] == parsed_in["asset_id"]
            assert parsed_out["name_of_system"] == parsed_in["name_of_system"]
            assert parsed_out["category"] == parsed_in["category"]
            assert parsed_out["payment_method"] == parsed_in["payment_method"]

            assert parsed_out["pi_of_funding"] == config.EPIF_PI_AND_END_USER
            assert parsed_out["end_user"] == config.EPIF_PI_AND_END_USER

            # Check ignored fields
            assert parsed_out["raw_fields"].get("Signature1") == ""
            assert parsed_out["raw_fields"].get("Telephone # for ?'s") == "608-263-2760"

def test_fill_epif_bom(template_bytes):
    """
    Test BOM case where we have >= 2 items.
    """
    parsed_in = {
        "total_price": 500.0,
        "items": [
            {"description": "Item 1", "quantity": 1, "unit_price": 250.0},
            {"description": "Item 2", "quantity": 1, "unit_price": 250.0},
        ],
        "category": "Software",
        "payment_method": "Req/PO",
        "item_description": "Should be overwritten by BOM text",
    }

    filled_bytes = fill_epif(template_bytes, parsed_in)
    parsed_out = parse_epif(filled_bytes)

    assert parsed_out["item_description"] == "See attached BOM — 2 items"
    assert parsed_out["total_price"] == 500.0
