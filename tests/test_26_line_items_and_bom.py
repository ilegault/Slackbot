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
7. bom_filename (ADR 0019 lab names).
8. Atomic save_bom with no leftover temp files.
9. BOMS_DIR presence in config and path_validator startup alert.
"""
import os
from unittest.mock import MagicMock

from src import config, heartbeat, log_writer, path_validator

# ---------------------------------------------------------------------------
# 1. Parsing line items
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# 2. Formatter and round-trip
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# 3. Total check & needs_bom
# ---------------------------------------------------------------------------

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

def test_build_bom_workbook_content_and_numbers():
    """Rewritten for ADR 0019: the lab template layout, live formulas, no shipping/project/fund."""
    import io

    import openpyxl

    from src import bom

    request = {
        "vendor": "Ruland",
        "requester": "Dylan",
        "item_description": "Shaft collars",
        "project_id": "PG000025831",
        "fund": "133",
        "date_of_purchase": "2026-09-22",
    }
    items = [
        {"qty": 2, "name": "Shaft Collar", "part_number": "SC-100", "unit_price": 12.50,
         "link": "https://ruland.com/sc100", "description": "Steel collar"},
        {"qty": 4, "name": "Clamp Collar", "part_number": "CC-200", "unit_price": 15.00,
         "link": "not-a-url", "description": "", "vendor": "Other Co", "notes": "rush"},
    ]

    wb_bytes = bom.build_bom_workbook(request, items)
    assert isinstance(wb_bytes, bytes)
    ws = openpyxl.load_workbook(io.BytesIO(wb_bytes)).active

    assert ws.title == "BOM"
    assert ws["A1"].value == "BILL OF MATERIALS"
    assert ws["A2"].value == "Order Description" and ws["B2"].value == "Shaft collars"
    assert ws["A3"].value == "BOM Creator" and ws["B3"].value == "Dylan"
    assert ws["A4"].value == "Total Cost" and ws["B4"].value == "=G8"
    assert [c.value for c in ws[5]][:8] == [
        "Item", "Description ", "Product #", "Vendor", "Unit Cost", "Quantity", "Total Cost", "Notes"]

    # Item rows carry the entered numbers; totals are live formulas, not concrete values.
    assert [ws.cell(6, c).value for c in (1, 3, 4, 5, 6)] == ["Shaft Collar", "SC-100", "Ruland", 12.50, 2]
    # An item's own vendor and notes win over the request's vendor.
    assert [ws.cell(7, c).value for c in (1, 3, 4, 5, 6, 8)] == [
        "Clamp Collar", "CC-200", "Other Co", 15.00, 4, "rush"]
    assert ws["G6"].value == "=F6*E6"
    assert ws["G7"].value == "=F7*E7"
    assert ws["F8"].value == "Total"
    assert ws["G8"].value == "=SUM(G6:G7)"

    # Hyperlink only for a real URL.
    assert ws["A6"].hyperlink is not None
    assert ws["A6"].hyperlink.target == "https://ruland.com/sc100"
    assert ws["A7"].hyperlink is None

    # Nothing about project, fund, date or shipping.
    text = [str(c.value) for row in ws.iter_rows() for c in row if c.value is not None]
    for banned in ("PG000025831", "2026-09-22", "Shipping", "DRAFT", "Purchasing Log"):
        assert not any(banned in t for t in text), banned
    # Only B3 (the BOM Creator) is filled in the header block's third row.
    assert all(c.value is None for c in ws[3][2:])


def test_build_bom_workbook_draft_header():
    """Rewritten for ADR 0019: a draft and an archived sheet are identical; only the file name differs."""
    import datetime
    import io

    import openpyxl

    from src import bom

    request = {"vendor": "DigiKey", "requester": "Isaac", "item_description": "ICs"}
    items = [{"qty": 1, "name": "IC", "part_number": "", "unit_price": 5.0, "link": "", "description": ""}]
    ws = openpyxl.load_workbook(io.BytesIO(bom.build_bom_workbook(request, items))).active

    assert ws["A1"].value == "BILL OF MATERIALS"
    assert ws["D6"].value == "DigiKey"
    assert ws["G7"].value == "=SUM(G6:G6)"
    assert ws["B4"].value == "=G7"
    assert ws.freeze_panes == "A6"
    assert not any("DRAFT" in str(c.value) for row in ws.iter_rows() for c in row if c.value)
    today = datetime.date.today().strftime("%m.%d.%Y")
    assert bom.bom_filename("ICs", draft=True) == f"DRAFT_HIRST_LAB_BOM_ICs_{today}.xlsx"
    assert bom.bom_filename("ICs", datetime.date(2026, 10, 14)) == "HIRST_LAB_BOM_ICs_10.14.2026.xlsx"

    # Unknown vendor fallback (ADR 0008 decision 1, kept by ADR 0019).
    ws2 = openpyxl.load_workbook(io.BytesIO(bom.build_bom_workbook({}, items))).active
    assert ws2["D6"].value == "Unknown Vendor"


def test_bom_filename():
    """Rewritten for ADR 0019: description words joined by '-', bad characters dropped, 60 max."""
    import datetime

    from src import bom

    d = datetime.date(2026, 10, 14)
    assert bom.bom_filename("Ruland couplings", d) == "HIRST_LAB_BOM_Ruland-couplings_10.14.2026.xlsx"
    assert bom.bom_filename("Ruland couplings", d, ext="csv").endswith("_10.14.2026.csv")

    # Punctuation a Windows name cannot hold is dropped; the rest stays.
    assert bom.bom_filename("Vendor, Inc. & Co.", d) == "HIRST_LAB_BOM_Vendor,-Inc.-&-Co._10.14.2026.xlsx"

    # A long description is cut to 60 characters.
    fn = bom.bom_filename("Very Long Description " * 10, d)
    part = fn[len("HIRST_LAB_BOM_"):-len("_10.14.2026.xlsx")]
    assert len(part) <= 60
    assert part.startswith("Very-Long-Description-Very-Long")

    # Nothing usable falls back to a placeholder rather than an empty name part.
    assert bom.bom_filename("", d) == "HIRST_LAB_BOM_Order_10.14.2026.xlsx"
    assert bom.bom_filename("???", d) == "HIRST_LAB_BOM_Order_10.14.2026.xlsx"


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
    assert blocks[0]["text"]["text"] == "🟠 Purchasing bot online — storage paths need attention"
    problems_block = blocks[2]
    assert f"• `BOMS_DIR` = `{missing_boms}` — does not exist" in problems_block["text"]["text"]
