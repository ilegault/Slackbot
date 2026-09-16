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





def test_needs_asset_details():
    assert interview.needs_asset_details("Fabrication Component (4670) > $200") is True
    assert interview.needs_asset_details("Standalone Equipment >$5k (4602)") is False
    assert interview.needs_asset_details("Research/Lab Supplies (3105)") is False
    assert interview.needs_asset_details(None) is False
    assert interview.needs_asset_details("") is False


def test_validate_stage1():
    # Valid Workday vendor without custom text
    assert interview.validate_stage1("Fisher Scientific", "") == {}
    assert interview.validate_stage1("Dell", "") == {}

    # Other option with blank or whitespace text -> error
    err_other_blank = interview.validate_stage1(config.VENDOR_OTHER_OPTION, "")
    assert "block_vendor_custom" in err_other_blank

    err_other_ws = interview.validate_stage1(config.VENDOR_OTHER_OPTION, "   ")
    assert "block_vendor_custom" in err_other_ws

    # Other option with valid text -> clean
    assert interview.validate_stage1(config.VENDOR_OTHER_OPTION, "McMaster-Carr") == {}

    # Suggest option with blank or whitespace text -> error
    err_suggest_blank = interview.validate_stage1(config.VENDOR_SUGGEST_OPTION, "")
    assert "block_vendor_custom" in err_suggest_blank

    err_suggest_ws = interview.validate_stage1(config.VENDOR_SUGGEST_OPTION, " \t\n ")
    assert "block_vendor_custom" in err_suggest_ws

    # Suggest option with valid text -> clean
    assert interview.validate_stage1(config.VENDOR_SUGGEST_OPTION, "Thorlabs") == {}


def test_build_parsed_from_stages_workday_non_fabrication():
    stage1 = {
        "resolved_name": "Isaac",
        "user_id": "U123",
        "vendor_choice": "Fisher Scientific",
        "vendor_custom": "",
        "route": "workday",
    }
    stage2 = {
        "item_description": "Box of Nitrile Gloves (Medium)",
        "purpose": "General lab use https://fishersci.com/gloves",
        "total_price": "$145.50",
        "vendor_contact_name": "Sales Rep",
        "vendor_contact_email": "sales@fishersci.com",
        "date_of_purchase": "09/14/26",
        "delivery_room": "ERB 212",
        "project_id": "PG000025831",
        "fund": "133",
        "category": "Research/Lab Supplies (3105)",
    }

    parsed = interview.build_parsed_from_stages(stage1, stage2, stage3=None)

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
    assert parsed["asset_id"] == ""
    assert parsed["name_of_system"] == ""
    assert parsed["pi_of_funding"] == ""
    assert parsed["end_user"] == ""


def test_build_parsed_from_stages_epif_fabrication():
    stage1 = {
        "resolved_name": "Dylan",
        "user_id": "U456",
        "vendor_choice": config.VENDOR_OTHER_OPTION,
        "vendor_custom": "Custom Machining Co",
        "route": "epif",
    }
    stage2 = {
        "item_description": "Beamline Flange Port",
        "purpose": "Fabrication chamber port",
        "total_price": 520.0,
        "vendor_contact_name": "John Machinist",
        "vendor_contact_email": "john@machining.com",
        "date_of_purchase": "2026-09-15",
        "delivery_room": "ERB 839",
        "project_id": "PG000025831",
        "fund": "150",
        "category": "Fabrication Component (4670) > $200",
        "payment_method": "P-card",
    }
    stage3 = {
        "asset_id": "TAG-88899",
        "name_of_system": "Target Chamber Alpha",
    }

    parsed = interview.build_parsed_from_stages(stage1, stage2, stage3=stage3)

    assert parsed["item_description"] == "Beamline Flange Port"
    assert parsed["vendor"] == "Custom Machining Co"
    assert parsed["total_price"] == 520.0
    assert parsed["payment_method"] == "P-card"
    assert parsed["asset_id"] == "TAG-88899"
    assert parsed["name_of_system"] == "Target Chamber Alpha"
    assert parsed["delivery_room"] == "ERB 839"
    assert parsed["category"] == "Fabrication Component (4670) > $200"
    assert parsed["category_error"] is None


def test_match_faq():
    # Questions with matching topics
    assert interview.match_faq("what's a project id?") is not None
    assert "PG000025831" in interview.match_faq("what's a project id?")
    assert interview.match_faq("What is a fund number?") is not None
    assert interview.match_faq("Can you explain delivery room?") is not None
    assert interview.match_faq("What's the difference with p-card?") is not None
    assert interview.match_faq("What happens after I submit this?") is not None
    assert interview.match_faq("What is Workday punchout?") is not None

    # Messages without question markers (should NOT match)
    assert interview.match_faq("I am using fund 133 for this order") is None
    assert interview.match_faq("@p-bot confirmed") is None
    assert interview.match_faq("processed $150.00 for project id") is None
    assert interview.match_faq("") is None

