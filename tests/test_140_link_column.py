"""Ticket 140: Link column in the BOM template, the reader and the builder (ADR 0020)."""
import io

import openpyxl

from src import bom, config


def _to_bytes(wb: openpyxl.Workbook) -> bytes:
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _make_bom_wb(headers=None) -> tuple[openpyxl.Workbook, openpyxl.worksheet.worksheet.Worksheet]:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "BOM"
    ws.append(["BILL OF MATERIALS"])
    ws.append(["Order Description", "Test order"])
    ws.append(["BOM Creator", "Tester"])
    ws.append(["Total Cost", "=H10"])
    ws.append(list(headers if headers is not None else getattr(config, "BOM_TEMPLATE_HEADERS", ())))
    return wb, ws


def test_normalize_link():
    assert bom.normalize_link("vendor.com/p/1") == "https://vendor.com/p/1"
    assert bom.normalize_link("http://x.org/a") == "http://x.org/a"
    assert bom.normalize_link("https://x.org/a") == "https://x.org/a"
    assert bom.normalize_link("HTTP://X.ORG/A") == "HTTP://X.ORG/A"
    assert bom.normalize_link("  https://vendor.com/p/1  ") == "https://vendor.com/p/1"
    assert bom.normalize_link("see quote") is None
    assert bom.normalize_link("nowebpage") is None
    assert bom.normalize_link("") is None
    assert bom.normalize_link("   ") is None


def test_reader_takes_link_with_or_without_scheme():
    wb, ws = _make_bom_wb(headers=[
        "Item", "Description", "Product #", "Link", "Vendor", "Unit Cost", "Quantity", "Total Cost", "Notes",
    ])
    ws.append(["Collar A", "Desc A", "P1", "vendor.com/p/1", "V", 10.0, 2, "=G6*F6", "note"])
    ws.append(["Collar B", "Desc B", "P2", "http://x.org/a", "V", 15.0, 1, "=G7*F7", None])
    ws.append([None, None, None, None, None, None, "Total", "=SUM(H6:H7)", None])

    items, problems = bom.read_bom_template(_to_bytes(wb))
    assert problems == []
    assert len(items) == 2
    assert items[0]["link"] == "https://vendor.com/p/1"
    assert items[0]["row"] == 6
    assert items[1]["link"] == "http://x.org/a"
    assert items[1]["row"] == 7


def test_reader_falls_back_to_item_hyperlink_and_reads_reasons():
    wb, ws = _make_bom_wb(headers=[
        "Item", "Description", "Product #", "Link", "Vendor", "Unit Cost", "Quantity", "Total Cost", "Notes",
    ])
    ws.append(["Collar A", "Desc", "P1", "", "V", 10.0, 1, "=G6*F6", None])
    ws.cell(row=6, column=1).hyperlink = "https://example.com/target"

    ws.append(["Collar B", "Desc", "P2", "no web page", "V", 10.0, 1, "=G7*F7", None])
    ws.append(["Collar C", "Desc", "P3", "Covered by another row's link", "V", 10.0, 1, "=G8*F8", None])
    ws.append(["Collar D", "Desc", "P4", "", "V", 10.0, 1, "=G9*F9", None])
    ws.append([None, None, None, None, None, None, "Total", "=SUM(H6:H9)", None])

    items, problems = bom.read_bom_template(_to_bytes(wb))
    assert problems == []
    assert len(items) == 4

    # Row 6: blank Link + hyperlinked Item -> target
    assert items[0]["link"] == "https://example.com/target"
    assert items[0]["no_link_reason"] == ""
    assert items[0]["row"] == 6

    # Row 7: Link cell 'no web page' -> link="", no_link_reason="No web page"
    assert items[1]["link"] == ""
    assert items[1]["no_link_reason"] == "No web page"
    assert items[1]["row"] == 7

    # Row 8: Link cell 'Covered by another row's link' -> link="", no_link_reason="Covered by another row's link"
    assert items[2]["link"] == ""
    assert items[2]["no_link_reason"] == "Covered by another row's link"
    assert items[2]["row"] == 8

    # Row 9: blank Link and no hyperlink -> both empty, no problem
    assert items[3]["link"] == ""
    assert items[3]["no_link_reason"] == ""
    assert items[3]["row"] == 9


def test_reader_flags_bad_link_and_old_template():
    wb, ws = _make_bom_wb(headers=[
        "Item", "Description", "Product #", "Link", "Vendor", "Unit Cost", "Quantity", "Total Cost", "Notes",
    ])
    ws.append(["Collar A", "Desc", "P1", "see quote", "V", 10.0, 1, "=G6*F6", None])
    ws.append([None, None, None, None, None, None, "Total", "=SUM(H6:H6)", None])

    items, problems = bom.read_bom_template(_to_bytes(wb))
    assert problems == ["Row 6: Link 'see quote' isn't a web address."]
    assert items == []

    # Old template headers (8 columns)
    old_headers = getattr(config, "BOM_OLD_TEMPLATE_HEADERS", (
        "Item", "Description", "Product #", "Vendor", "Unit Cost", "Quantity", "Total Cost", "Notes",
    ))
    wb_old, ws_old = _make_bom_wb(headers=old_headers)
    wb_old.worksheets[0].cell(row=5, column=2, value="Description ")  # test with trailing space
    wb_old.worksheets[0].append(["Collar", "Desc", "P1", "V", 10.0, 1, "=F6*E6", None])
    items_old, problems_old = bom.read_bom_template(_to_bytes(wb_old))
    assert items_old == []
    assert problems_old == [
        "This is the old BOM template, which has no Link column — get the new one with the “Send me the BOM template” button."
    ]

    # Non-template headers
    wb_other = openpyxl.Workbook()
    wb_other.active.append(["Some", "Random", "Headers"])
    wb_other.active.append(["a", "b", "c"])
    items_other, problems_other = bom.read_bom_template(_to_bytes(wb_other))
    assert items_other == []
    assert problems_other == [
        "This isn't the lab BOM template — get it with the “Send me the BOM template” button. Vendor carts and quotes go in the Quotes field."
    ]


def test_build_then_read_keeps_links_and_reasons():
    items_in = [
        {
            "name": "Part 1",
            "description": "Desc 1",
            "part_number": "P1",
            "vendor": "V",
            "unit_price": 10.0,
            "qty": 2,
            "link": "https://example.com/p1",
            "no_link_reason": "",
            "notes": "note 1",
        },
        {
            "name": "Part 2",
            "description": "Desc 2",
            "part_number": "P2",
            "vendor": "V",
            "unit_price": 20.0,
            "qty": 1,
            "link": "",
            "no_link_reason": "No web page",
            "notes": "",
        },
        {
            "name": "Part 3",
            "description": "Desc 3",
            "part_number": "P3",
            "vendor": "V",
            "unit_price": 5.0,
            "qty": 3,
            "link": "",
            "no_link_reason": "Covered by another row's link",
            "notes": "",
        },
    ]

    req = {"item_description": "Parts test", "requester": "Alice"}
    built_bytes = bom.build_bom_workbook(req, items_in)

    wb = openpyxl.load_workbook(io.BytesIO(built_bytes))
    ws = wb.worksheets[0]

    # Header row equals config.BOM_TEMPLATE_HEADERS
    headers = [str(ws.cell(row=5, column=c).value or "").strip() for c in range(1, 10)]
    assert headers == list(config.BOM_TEMPLATE_HEADERS)

    # Linked row: Link cell and Item cell have .hyperlink.target equal to URL
    item_cell = ws.cell(row=6, column=1)
    link_cell = ws.cell(row=6, column=4)
    assert item_cell.hyperlink is not None and item_cell.hyperlink.target == "https://example.com/p1"
    assert link_cell.hyperlink is not None and link_cell.hyperlink.target == "https://example.com/p1"

    # Other rows: Link cell holds reason text
    assert ws.cell(row=7, column=4).value == "No web page"
    assert ws.cell(row=8, column=4).value == "Covered by another row's link"

    # Reading the bytes back gives the same items per row and problems == []
    read_items, problems = bom.read_bom_template(built_bytes)
    assert problems == []
    assert len(read_items) == 3

    for orig, read in zip(items_in, read_items):
        assert read["name"] == orig["name"]
        assert read["qty"] == orig["qty"]
        assert read["link"] == orig["link"]
        assert read["no_link_reason"] == orig["no_link_reason"]
