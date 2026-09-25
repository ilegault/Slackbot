import io
import re

import openpyxl

from src import bom


def test_bom_layout():
    request = {"vendor": "TestVendor"}
    items = [
        {
            "qty": 2,
            "name": "Item 1",
            "part_number": "P1",
            "unit_price": 10.0,
            "link": "https://example.com/1",
            "description": "Desc 1",
        },
        {
            "qty": 1,
            "name": "Item 2",
            "part_number": "P2",
            "unit_price": 20.0,
            "link": "",
            "description": "Desc 2",
        },
        {
            "qty": 5,
            "name": "Item 3",
            "part_number": "P3",
            "unit_price": 5.0,
            "link": "see quote",
            "description": "Desc 3",
        },
    ]

    wb_bytes = bom.build_bom_workbook(request, items)
    assert isinstance(wb_bytes, bytes)

    wb = openpyxl.load_workbook(io.BytesIO(wb_bytes))
    ws = wb.active

    # Check A1
    assert ws["A1"].value == "BILL OF MATERIALS"

    # Check merge A1:B1
    merged_ranges = [str(m) for m in ws.merged_cells.ranges]
    assert "A1:B1" in merged_ranges

    # Check A2
    assert ws["A2"].value == "Total Cost"

    # Check row 4 headers
    headers = ["Item", "Description", "Product #", "Vendor", "Unit Cost", "Quantity", "Total Cost", "Notes"]
    for col_idx, expected_header in enumerate(headers, start=1):
        assert ws.cell(row=4, column=col_idx).value == expected_header

    # Check rows 5-7
    # Item 1
    assert ws["A5"].value == "Item 1"
    assert ws["B5"].value == "Desc 1"
    assert ws["C5"].value == "P1"
    assert ws["D5"].value == "TestVendor"
    assert ws["E5"].value == 10.0
    assert ws["F5"].value == 2
    assert ws["H5"].value is None

    # Item 2
    assert ws["A6"].value == "Item 2"
    assert ws["B6"].value == "Desc 2"
    assert ws["C6"].value == "P2"
    assert ws["D6"].value == "TestVendor"
    assert ws["E6"].value == 20.0
    assert ws["F6"].value == 1
    assert ws["H6"].value is None

    # Item 3
    assert ws["A7"].value == "Item 3"
    assert ws["B7"].value == "Desc 3"
    assert ws["C7"].value == "P3"
    assert ws["D7"].value == "TestVendor"
    assert ws["E7"].value == 5.0
    assert ws["F7"].value == 5
    assert ws["H7"].value is None

    # Check row 8 (Total)
    assert ws["F8"].value == "Total"

    # Check freeze panes
    assert ws.freeze_panes == "A5"

    # Check hyperlinks in column A
    # Row 5 (https://)
    assert ws["A5"].hyperlink is not None
    assert ws["A5"].hyperlink.target == "https://example.com/1"

    # Row 6 (empty)
    assert ws["A6"].hyperlink is None

    # Row 7 (non URL)
    assert ws["A7"].hyperlink is None


def _evaluate_formula(formula, ws):
    """
    Evaluates only `=E{r}*F{r}`, `=SUM(G{a}:G{b})`, and `=G{n}`.
    Raises on anything else.
    """
    if not isinstance(formula, str) or not formula.startswith("="):
        raise ValueError(f"Not a formula: {formula}")

    # Check for =E{r}*F{r}
    m1 = re.match(r"^=E(\d+)\*F(\d+)$", formula)
    if m1:
        r1, r2 = m1.groups()
        if r1 != r2:
            raise ValueError(f"Mismatched rows in multiplication formula: {formula}")
        e_val = ws[f"E{r1}"].value or 0
        f_val = ws[f"F{r1}"].value or 0
        return e_val * f_val

    # Check for =SUM(G{a}:G{b})
    m2 = re.match(r"^=SUM\(G(\d+):G(\d+)\)$", formula)
    if m2:
        a, b = [int(x) for x in m2.groups()]
        total = 0
        for i in range(a, b + 1):
            cell_formula = ws[f"G{i}"].value
            total += _evaluate_formula(cell_formula, ws)
        return total

    # Check for =G{n}
    m3 = re.match(r"^=G(\d+)$", formula)
    if m3:
        n = m3.group(1)
        return _evaluate_formula(ws[f"G{n}"].value, ws)

    raise ValueError(f"Unsupported formula: {formula}")

def test_bom_formulas():
    request = {"vendor": "TestVendor"}
    items = [
        {"qty": 2, "name": "Item 1", "part_number": "P1", "unit_price": 10.0, "link": "https://example.com/1", "description": "Desc 1"},
        {"qty": 1, "name": "Item 2", "part_number": "P2", "unit_price": 20.0, "link": "", "description": "Desc 2"},
        {"qty": 5, "name": "Item 3", "part_number": "P3", "unit_price": 5.0, "link": "see quote", "description": "Desc 3"},
    ]
    wb_bytes = bom.build_bom_workbook(request, items)
    wb = openpyxl.load_workbook(io.BytesIO(wb_bytes))
    ws = wb.active

    # Every G cell in rows 5-7 evaluates to qty * unit_price
    assert _evaluate_formula(ws["G5"].value, ws) == 20.0
    assert _evaluate_formula(ws["G6"].value, ws) == 20.0
    assert _evaluate_formula(ws["G7"].value, ws) == 25.0

    # G8 and B2 evaluate to sum of qty * unit_price
    sum_val = 20.0 + 20.0 + 25.0
    assert _evaluate_formula(ws["G8"].value, ws) == sum_val
    assert _evaluate_formula(ws["B2"].value, ws) == sum_val

def test_bom_removed_content():
    request = {
        "vendor": "TestVendor",
        "requester": "Bob",
        "project_id": "PRJ123",
        "fund": "FUND456",
        "date_of_purchase": "2023-01-01"
    }
    items = [{"qty": 1, "name": f"Item {i}", "part_number": f"P{i}", "unit_price": 10.0, "link": "", "description": ""} for i in range(5)]
    wb_bytes = bom.build_bom_workbook(request, items)
    wb = openpyxl.load_workbook(io.BytesIO(wb_bytes))
    ws = wb.active

    # Walk every cell with a value
    max_row_with_value = 0
    row_3_empty = True
    for row_idx, row in enumerate(ws.iter_rows(), start=1):
        for cell in row:
            if cell.value is not None:
                max_row_with_value = max(max_row_with_value, row_idx)
                if row_idx == 3:
                    row_3_empty = False
                val_str = str(cell.value)
                assert "Bob" not in val_str
                assert "PRJ123" not in val_str
                assert "FUND456" not in val_str
                assert "2023-01-01" not in val_str
                assert "Shipping" not in val_str
                assert "DRAFT" not in val_str
                assert "Purchasing Log" not in val_str

    assert row_3_empty
    # Data is in rows 5-9 (5 items), so Total row is 10
    assert max_row_with_value == 10
