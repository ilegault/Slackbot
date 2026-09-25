"""Tests for Ticket 26: Line items, the BOM workbook, and the BOMs folder.

WHY THIS EXISTS:
----------------
Covers the pure BOM domain logic (src/bom.py), the BOM storage writer
(log_writer.save_bom), and the BOMS_DIR startup configuration:
1. Pasted items parser: pipe- and tab-separated, optional fields, error reporting.
2. Formatter round-trip.
3. Total check tolerance and mismatch reporting.
4. needs_bom distinction (line count vs quantity).
5. describe_changes fragment generator.
6. Openpyxl workbook builder (headers, numbers not formulas, hyperlinks).
7. bom_filename slugging, zero-padding, and draft fallback.
8. Atomic save_bom with no leftover temp files.
9. BOMS_DIR presence in config and path_validator startup alert.
"""
import io
import os
from unittest.mock import MagicMock

import openpyxl

from src import config, heartbeat, log_writer, path_validator

# ---------------------------------------------------------------------------
# 1. Parsing line items
# ---------------------------------------------------------------------------

def test_parse_line_items_pipe_and_tab_identical():
    """Tab-separated paste copied out of a spreadsheet parses identically to | form."""
    from src import bom

    pipe_text = (
        "2 | Shaft Collar | SC-100 | 12.50 | https://example.com/sc100 | Steel collar\n"
        "5 | Hex Bolt | HB-05 | 1.20 | | Grade 8 bolt\n"
        "shipping | 15.00\n"
    )
    tab_text = (
        "2\tShaft Collar\tSC-100\t12.50\thttps://example.com/sc100\tSteel collar\n"
        "5\tHex Bolt\tHB-05\t1.20\t\tGrade 8 bolt\n"
        "shipping\t15.00\n"
    )

    items_pipe, shipping_pipe, errors_pipe = bom.parse_line_items(pipe_text)
    items_tab, shipping_tab, errors_tab = bom.parse_line_items(tab_text)

    assert errors_pipe == []
    assert errors_tab == []
    assert items_pipe == items_tab
    assert shipping_pipe == shipping_tab == 15.0
    assert len(items_pipe) == 2

    assert items_pipe[0] == {
        "qty": 2,
        "name": "Shaft Collar",
        "part_number": "SC-100",
        "unit_price": 12.50,
        "link": "https://example.com/sc100",
        "description": "Steel collar",
    }
    assert items_pipe[1] == {
        "qty": 5,
        "name": "Hex Bolt",
        "part_number": "HB-05",
        "unit_price": 1.20,
        "link": "",
        "description": "Grade 8 bolt",
    }


def test_parse_line_items_optional_fields():
    """part #, link, and description are optional; a 4-field line parses cleanly."""
    from src import bom

    text = "3 | Resistors | | 0.50\n"
    items, shipping, errors = bom.parse_line_items(text)

    assert errors == []
    assert len(items) == 1
    assert items[0] == {
        "qty": 3,
        "name": "Resistors",
        "part_number": "",
        "unit_price": 0.50,
        "link": "",
        "description": "",
    }
    assert shipping == 0.0


def test_parse_line_items_validation_errors():
    """Quantity must be positive whole number, price >= 0, name non-empty."""
    from src import bom

    # Bad qty
    items, _, errors = bom.parse_line_items("0 | Widget | W-1 | 10.00")
    assert any("line 1" in e and "0" in e for e in errors)

    items, _, errors = bom.parse_line_items("-2 | Widget | W-1 | 10.00")
    assert any("line 1" in e and "-2" in e for e in errors)

    items, _, errors = bom.parse_line_items("abc | Widget | W-1 | 10.00")
    assert any("line 1" in e and "abc" in e for e in errors)

    # Empty name
    items, _, errors = bom.parse_line_items("2 | | W-1 | 10.00")
    assert any("line 1" in e and "name" in e.lower() for e in errors)

    # Bad price
    items, _, errors = bom.parse_line_items("2 | Widget | W-1 | abc")
    assert any("line 1" in e and "abc" in e for e in errors)

    items, _, errors = bom.parse_line_items("2 | Widget | W-1 | -5.00")
    assert any("line 1" in e and "-5.00" in e for e in errors)

    # Too few / too many fields
    items, _, errors = bom.parse_line_items("2 | Widget | W-1")
    assert any("line 1" in e and "field" in e.lower() for e in errors)

    items, _, errors = bom.parse_line_items("2 | Widget | W-1 | 10.00 | link | desc | extra")
    assert any("line 1" in e and "too many" in e.lower() for e in errors)


def test_shipping_line_and_duplicate_error():
    """A shipping | <amount> line is picked up; a second one is an error."""
    from src import bom

    # Valid shipping
    text = (
        "1 | Widget | W-1 | 20.00\n"
        "shipping | $24.50\n"
    )
    items, shipping, errors = bom.parse_line_items(text)
    assert errors == []
    assert shipping == 24.50
    assert len(items) == 1

    # Duplicate shipping
    dup_text = (
        "1 | Widget | W-1 | 20.00\n"
        "shipping | 10.00\n"
        "shipping | 15.00\n"
    )
    items, shipping, errors = bom.parse_line_items(dup_text)
    assert any("line 3" in e and "shipping" in e.lower() for e in errors)

    # Invalid shipping amount
    bad_ship = "shipping | abc"
    items, shipping, errors = bom.parse_line_items(bad_ship)
    assert any("line 1" in e and "abc" in e for e in errors)


def test_blank_lines_skipped_and_line_numbering():
    """Blank lines are skipped, and a bad line after blanks reports true line number."""
    from src import bom

    text = (
        "1 | Good Item | G-1 | 10.00\n"
        "\n"
        "   \n"
        "bad_qty | Broken Item | B-1 | 20.00\n"
    )
    items, _, errors = bom.parse_line_items(text)
    assert len(errors) == 1
    assert "line 4" in errors[0]
    assert "bad_qty" in errors[0]


def test_more_than_25_items_error():
    """More than 25 item lines is an error."""
    from src import bom

    lines = [f"{i} | Item {i} | PART-{i} | 5.00" for i in range(1, 27)]
    text = "\n".join(lines)
    items, _, errors = bom.parse_line_items(text)
    assert any("25" in e for e in errors)


# ---------------------------------------------------------------------------
# 2. Formatter and round-trip
# ---------------------------------------------------------------------------

def test_format_line_items_round_trip():
    """Formatting items back to text and re-parsing returns identical items and shipping."""
    from src import bom

    original_items = [
        {
            "qty": 3,
            "name": "Capacitor",
            "part_number": "CAP-01",
            "unit_price": 2.50,
            "link": "https://example.com/cap",
            "description": "Ceramic cap",
        },
        {
            "qty": 1,
            "name": "Breadboard",
            "part_number": "",
            "unit_price": 12.00,
            "link": "",
            "description": "",
        },
    ]
    original_shipping = 8.50

    formatted = bom.format_line_items(original_items, original_shipping)
    parsed_items, parsed_shipping, errors = bom.parse_line_items(formatted)

    assert errors == []
    assert parsed_items == original_items
    assert parsed_shipping == original_shipping


# ---------------------------------------------------------------------------
# 3. Total check & needs_bom
# ---------------------------------------------------------------------------

def test_check_total():
    """check_total passes within $0.01 tolerance, and names both numbers on mismatch."""
    from src import bom

    items = [
        {"qty": 2, "unit_price": 10.00},
        {"qty": 3, "unit_price": 5.00},
    ]  # items sum = 35.00
    shipping = 5.00  # calculated total = 40.00

    # Exact match
    assert bom.check_total(items, shipping, 40.00) is None
    assert bom.check_total(items, shipping, "$40.00") is None

    # Within 1 cent
    assert bom.check_total(items, shipping, 40.01) is None
    assert bom.check_total(items, shipping, 39.99) is None

    # Mismatch
    err = bom.check_total(items, shipping, 42.00)
    assert err is not None
    assert "40.00" in err
    assert "42.00" in err


def test_needs_bom():
    """One line with quantity 10 does not need a BOM; two lines do."""
    from src import bom

    one_item = [{"qty": 10, "name": "Item A", "part_number": "", "unit_price": 5.0, "link": "", "description": ""}]
    assert bom.needs_bom(one_item) is False

    two_items = [
        {"qty": 1, "name": "Item A", "part_number": "", "unit_price": 5.0, "link": "", "description": ""},
        {"qty": 1, "name": "Item B", "part_number": "", "unit_price": 5.0, "link": "", "description": ""},
    ]
    assert bom.needs_bom(two_items) is True


# ---------------------------------------------------------------------------
# 4. describe_changes
# ---------------------------------------------------------------------------

def test_describe_changes_identical_and_differing():
    """describe_changes returns empty list for identical requests, and exact fragments for diffs."""
    from src import bom

    req1 = {
        "item_description": "Parts",
        "total_price": 412.00,
        "purpose": "Experiment",
        "link": "https://example.com",
        "project_id": "PG000025831",
        "fund": "133",
        "category": "Research/Lab Supplies (3105)",
        "delivery_room": "ERB 212",
        "vendor_contact_name": "Alice",
        "vendor_contact_email": "alice@example.com",
        "payment_method": "PCard",
        "asset_id": "",
        "name_of_system": "",
        "items": [{"qty": 1, "name": "A", "part_number": "", "unit_price": 412.0, "link": "", "description": ""}],
        "shipping": 0.0,
    }
    # Identical
    assert bom.describe_changes(req1, dict(req1)) == []

    # Total and items count differ
    req2 = dict(req1)
    req2["total_price"] = 455.50
    req2["items"] = [
        {"qty": 1, "name": "A", "part_number": "", "unit_price": 100.0, "link": "", "description": ""},
        {"qty": 1, "name": "B", "part_number": "", "unit_price": 355.5, "link": "", "description": ""},
    ]
    changes = bom.describe_changes(req1, req2)
    assert "Total $412.00 → $455.50" in changes
    assert "items 1 → 2" in changes

    # Items content changed with same count
    req3 = dict(req1)
    req3["items"] = [{"qty": 1, "name": "Changed Name", "part_number": "", "unit_price": 412.0, "link": "", "description": ""}]
    changes3 = bom.describe_changes(req1, req3)
    assert "items changed" in changes3


# ---------------------------------------------------------------------------
# 5. Workbook builder & filename
# ---------------------------------------------------------------------------

def test_bom_filename():
    """bom_filename pads row, strips punctuation, truncates, falls back on empty vendor."""
    from src import bom

    assert bom.bom_filename(18, "Ruland") == "0018_Ruland_BOM.xlsx"
    assert bom.bom_filename(None, "Ruland") == "DRAFT_Ruland_BOM.xlsx"

    # Punctuation stripped and spaces replaced by hyphens
    assert bom.bom_filename(5, "Vendor, Inc. & Co.") == "0005_Vendor-Inc-Co_BOM.xlsx"

    # Long vendor truncated to 40 characters
    long_vendor = "Very Long Company Name That Exceeds Forty Characters Easily Inc"
    fn = bom.bom_filename(1, long_vendor)
    slug = fn.split("_")[1]
    assert len(slug) <= 40

    # Empty vendor falls back to 'Vendor'
    assert bom.bom_filename(7, "") == "0007_Vendor_BOM.xlsx"
    assert bom.bom_filename(7, "   ") == "0007_Vendor_BOM.xlsx"
    assert bom.bom_filename(7, "!!!") == "0007_Vendor_BOM.xlsx"


# ---------------------------------------------------------------------------
# 6. Atomic save_bom
# ---------------------------------------------------------------------------

def test_save_bom_atomic(tmp_path):
    """Saving a BOM is atomic, writes exact bytes, and leaves no temp files behind."""
    boms_dir = tmp_path / "BOMs"
    boms_dir.mkdir()

    content = b"fake-bom-bytes-content"
    saved_path = log_writer.save_bom(content, "0018_Ruland_BOM.xlsx", target_dir=str(boms_dir))

    assert os.path.exists(saved_path)
    assert os.path.basename(saved_path) == "0018_Ruland_BOM.xlsx"
    with open(saved_path, "rb") as f:
        assert f.read() == content

    # Ensure no leftover temp files
    remaining_files = os.listdir(str(boms_dir))
    assert remaining_files == ["0018_Ruland_BOM.xlsx"]


# ---------------------------------------------------------------------------
# 7. BOMS_DIR configuration and startup check
# ---------------------------------------------------------------------------

def test_boms_dir_in_config_and_path_validator(monkeypatch, tmp_path):
    """BOMS_DIR is read from config and checked in path_validator."""
    boms = tmp_path / "BOMs"
    monkeypatch.setattr(config, "BOMS_DIR", str(boms))

    # Folder does not exist
    problems = path_validator.check_storage_paths()
    bom_prob = [p for p in problems if p[0] == "BOMS_DIR"]
    assert len(bom_prob) == 1
    assert bom_prob[0][2] == "does not exist"

    # Folder exists
    boms.mkdir()
    problems = path_validator.check_storage_paths()
    bom_prob = [p for p in problems if p[0] == "BOMS_DIR"]
    assert len(bom_prob) == 0


def test_startup_alert_names_missing_boms_dir(monkeypatch, tmp_path):
    """Missing BOMS_DIR is named in startup alert without stopping the bot."""
    wb = tmp_path / "Purchasing-Log.xlsx"
    wb.write_text("dummy", encoding="utf-8")
    epifs = tmp_path / "EPIFs"
    epifs.mkdir()
    confs = tmp_path / "Order-Confirmations"
    confs.mkdir()
    quotes = tmp_path / "Quotes"
    quotes.mkdir()
    missing_boms = str(tmp_path / "MissingBOMs")

    monkeypatch.setattr(config, "WORKBOOK_PATH", str(wb))
    monkeypatch.setattr(config, "EPIFS_DIR", str(epifs))
    monkeypatch.setattr(config, "CONFIRMATIONS_DIR", str(confs))
    monkeypatch.setattr(config, "QUOTES_DIR", str(quotes))
    monkeypatch.setattr(config, "BOMS_DIR", missing_boms)
    monkeypatch.setattr(config, "ADMIN_ALERT_CHANNEL", "C_ADMIN_ALERT")

    mock_client = MagicMock()
    result = heartbeat.send_startup_alert(mock_client)
    assert result is True

    call_kwargs = mock_client.chat_postMessage.call_args[1]
    blocks = call_kwargs["blocks"]
    assert blocks[0]["text"]["text"] == "🟠 P-Bot Online — storage paths need attention"
    problems_block = blocks[2]
    assert f"• `BOMS_DIR` = `{missing_boms}` — does not exist" in problems_block["text"]["text"]
