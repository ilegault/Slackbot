import os
import sys
from datetime import date

# Determine project root and src directory
_CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(_CURRENT_DIR) if os.path.basename(_CURRENT_DIR) == "tests" else _CURRENT_DIR
SRC_DIR = os.path.join(PROJECT_ROOT, "src")
for p in (PROJECT_ROOT, SRC_DIR):
    if p not in sys.path:
        sys.path.insert(0, p)

from src import config, interview


def test_route_vendor():
    # Workday punchout vendor
    assert interview.route_vendor("Fisher Scientific") == "workday"
    assert interview.route_vendor("Dell") == "workday"
    assert interview.route_vendor("Grainger") == "workday"

    # Non-workday / special options
    assert interview.route_vendor(config.VENDOR_OTHER_OPTION) == "epif"
    assert interview.route_vendor(config.VENDOR_SUGGEST_OPTION) == "epif"
    assert interview.route_vendor("Random Custom Store") == "epif"
    assert interview.route_vendor("") == "epif"


def test_build_parsed_from_modal_workday():
    modal_values = {
        "item_description": "Box of Nitrile Gloves (Medium)",
        "purpose": "General lab use https://fishersci.com/gloves",
        "total_price": "$145.50",
        "vendor_contact_name": "Sales Rep",
        "vendor_contact_email": "sales@fishersci.com",
        "date_of_purchase": "09/14/26",
        "name_of_system": "Cleanroom",
        "delivery_room": "ERB 212",
        "project_id": "PG000025831",
        "fund": "133",
        "asset_id": "",
        "category": "Research/Lab Supplies (3105)",
    }

    parsed = interview.build_parsed_from_modal(modal_values, vendor_choice="Fisher Scientific")

    expected_keys = {
        "raw_fields", "item_description", "purpose", "link", "total_price",
        "total_price_raw", "vendor", "vendor_contact_name", "vendor_contact_email",
        "date_of_purchase", "name_of_system", "delivery_room", "project_id",
        "fund", "asset_id", "pi_of_funding", "end_user", "category",
        "category_error", "payment_method",
    }
    assert set(parsed.keys()) == expected_keys
    assert parsed["item_description"] == "Box of Nitrile Gloves (Medium)"
    assert parsed["vendor"] == "Fisher Scientific"
    assert parsed["total_price"] == 145.50
    assert parsed["total_price_raw"] == "$145.50"
    assert parsed["link"] == "https://fishersci.com/gloves"
    assert parsed["date_of_purchase"] == date(2026, 9, 14)
    assert parsed["delivery_room"] == "ERB 212"
    assert parsed["project_id"] == "PG000025831"
    assert parsed["fund"] == "133"
    assert parsed["category"] == "Research/Lab Supplies (3105)"
    assert parsed["category_error"] is None
    assert parsed["payment_method"] == config.WORKDAY_PAYMENT_METHOD


def test_build_parsed_from_modal_epif():
    modal_values = {
        "item_description": "Custom Vacuum Flange",
        "purpose": "Chamber beamline upgrade",
        "link": "https://mcmaster.com/part123",
        "total_price": 520.0,
        "vendor_contact_name": "Support",
        "vendor_contact_email": "orders@mcmaster.com",
        "date_of_purchase": "2026-09-15",
        "name_of_system": "Target Chamber",
        "delivery_room": "ERB 839",
        "project_id": "PG000025831",
        "fund": "150",
        "asset_id": "TAG-999",
        "category": "Machining / Prof Services",
        "payment_method": "P-card",
        "other_vendor": "McMaster-Carr",
    }

    parsed = interview.build_parsed_from_modal(modal_values, vendor_choice=config.VENDOR_OTHER_OPTION)

    assert parsed["item_description"] == "Custom Vacuum Flange"
    assert parsed["vendor"] == "McMaster-Carr"
    assert parsed["total_price"] == 520.0
    assert parsed["link"] == "https://mcmaster.com/part123"
    assert parsed["payment_method"] == "P-card"
    assert parsed["delivery_room"] == "ERB 839"
    assert parsed["category"] == "Machining / Prof Services"
    assert parsed["category_error"] is None


def test_build_parsed_from_modal_suggest_vendor():
    modal_values = {
        "item_description": "Optical Breadboard",
        "purpose": "Laser table setup",
        "total_price": "890.00",
        "vendor_contact_email": "sales@thorlabs.com",
        "date_of_purchase": "09/16/2026",
        "delivery_room": "ERB 212",
        "project_id": "PG000025831",
        "fund": "133",
        "category": "Research/Lab Supplies (3105)",
        "payment_method": "Req/PO",
        "suggested_vendor": "Thorlabs",
    }

    parsed = interview.build_parsed_from_modal(modal_values, vendor_choice=config.VENDOR_SUGGEST_OPTION)
    assert parsed["vendor"] == "Thorlabs"
    assert parsed["payment_method"] == "Req/PO"


def test_match_faq():
    # Questions with matching topics
    assert interview.match_faq("what's a project id?") is not None
    assert "PG000025831" in interview.match_faq("what's a project id?")
    assert interview.match_faq("What is a fund number?") is not None
    assert interview.match_faq("Can you explain delivery room?") is not None
    assert interview.match_faq("What's the difference with p-card?") is not None
    assert interview.match_faq("What happens after I submit this?") is not None

    # Messages without question markers (should NOT match)
    assert interview.match_faq("I am using fund 133 for this order") is None
    assert interview.match_faq("@p-bot confirmed") is None
    assert interview.match_faq("submitted $150.00 for project id") is None
    assert interview.match_faq("") is None
