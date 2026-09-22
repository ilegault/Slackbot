"""Tests for Ticket 11: Mirror the roster into the workbook's Roles & Lists sheet.

Acceptance criteria:
- log_writer.sync_roster_lists exists with the signature and is the only new code that opens the workbook
- The string openpyxl appears nowhere in src/
- A test builds a fixture workbook, adds a requester not in the sheet, and asserts the name lands in the first free D row
  and that Requesters' ref and autoFilter ref both grew by one row
- A test adds a name already in the sheet in different case ("isaac") and asserts the sheet XML is byte-identical afterwards
- A test asserts a name present in the sheet but absent from roster.json is still there after a sync — assert on specific name
- A test adds a buyer and asserts the name lands in column A, that column B of that row is still empty, and that GradStudents' ref grew
- A test asserts remove_buyer removes the ID from roster.json and leaves the sheet byte-identical
- A test fills the sheet to row 49, adds one more name, and asserts: nothing written at or below row 50,
  the name is in the returned skipped list, and one message went to ADMIN_ALERT_CHANNEL
- A test with the workbook locked (~$Purchasing-Log.xlsx present) asserts roster.add_buyer still returns and the ID is in roster.json
- A test with config.WORKBOOK_PATH pointing at a nonexistent file asserts roster.add_requester succeeds and no exception escapes
- A round-trip test asserts that after a sync every other part of the zip is byte-identical to the input —
  specifically xl/worksheets/sheet1.xml, xl/styles.xml, xl/metadata.xml and the xl/webextensions/ parts —
  and that the part order in the archive is unchanged
- A test asserts the sheet still parses and that x14:conditionalFormatting is still present in sheet1.xml after a sync
- /roster-set-name accepts Hansel and Zehui, and config.VALID_REQUESTERS appears nowhere in src/
"""
import json
import os
import re
import sys
import zipfile
from unittest.mock import MagicMock

import pytest

_CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(_CURRENT_DIR) if os.path.basename(_CURRENT_DIR) == "tests" else _CURRENT_DIR
SRC_DIR = os.path.join(PROJECT_ROOT, "src")
for p in (PROJECT_ROOT, SRC_DIR):
    if p not in sys.path:
        sys.path.insert(0, p)

from src import app, config, log_writer, roster

STARTING_REQUESTERS = [
    "Isaac", "Smeet", "Dylan", "Alex", "Casey", "Prof. Hirst",
    "Erich", "Finn", "Eddie", "Katarina", "Keyvan", "Hansel", "Zehui"
]

STARTING_BUYERS = [
    ("U_ISAAC", "Isaac"),
    ("U_SMEET", "Smeet"),
    ("U_DYLAN", "Dylan"),
]


def create_fixture_workbook(dest_path: str, req_count: int = 13, grad_count: int = 3, fill_to_row: int = 0) -> str:
    """Build a realistic Purchasing-Log.xlsx fixture with Roles & Lists sheet and tables."""
    sheet1_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:x14="http://schemas.microsoft.com/office/spreadsheetml/2009/9/main">\n'
        '<sheetData>\n'
        '  <row r="11"><c r="B11" t="inlineStr"><is><t>Requester Name</t></is></c></row>\n'
        '  <row r="12"><c r="B12" s="46" t="inlineStr"><is><t>Isaac</t></is></c></row>\n'
        '</sheetData>\n'
        '<x14:conditionalFormatting><x14:cfRule type="expression"/></x14:conditionalFormatting>\n'
        '</worksheet>'
    )

    sheet2_rows = [
        '<row r="4">'
        '<c r="A4" t="inlineStr"><is><t>Grad Student</t></is></c>'
        '<c r="B4" t="inlineStr"><is><t>Color</t></is></c>'
        '<c r="D4" t="inlineStr"><is><t>Requester Name</t></is></c>'
        '</row>'
    ]

    for r in range(5, 50):
        # Determine cell values
        if fill_to_row and r <= fill_to_row:
            a_val = f'<c r="A{r}" s="3" t="inlineStr"><is><t xml:space="preserve">Grad{r}</t></is></c>'
            b_val = f'<c r="B{r}"/>'
            d_val = f'<c r="D{r}" s="3" t="inlineStr"><is><t xml:space="preserve">Req{r}</t></is></c>'
        else:
            req_idx = r - 5
            grad_idx = r - 5
            if req_idx < req_count and req_idx < len(STARTING_REQUESTERS):
                name = STARTING_REQUESTERS[req_idx]
                d_val = f'<c r="D{r}" s="3" t="inlineStr"><is><t xml:space="preserve">{name}</t></is></c>'
            else:
                d_val = f'<c r="D{r}" s="3"/>'

            if grad_idx < grad_count and grad_idx < len(STARTING_BUYERS):
                bname = STARTING_BUYERS[grad_idx][1]
                a_val = f'<c r="A{r}" s="3" t="inlineStr"><is><t xml:space="preserve">{bname}</t></is></c>'
                b_val = f'<c r="B{r}" t="inlineStr"><is><t xml:space="preserve">Yellow</t></is></c>'
            else:
                a_val = f'<c r="A{r}" s="3"/>'
                b_val = f'<c r="B{r}"/>'

        sheet2_rows.append(f'<row r="{r}">{a_val}{b_val}{d_val}</row>')

    sheet2_rows.append('<row r="50"><c r="A50" t="inlineStr"><is><t>Notes: Do not overwrite</t></is></c></row>')

    sheet2_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">\n'
        '<sheetData>\n'
        + "\n".join(sheet2_rows) +
        '\n</sheetData>\n'
        '</worksheet>'
    )

    t4_end = 4 + (fill_to_row - 4 if fill_to_row else req_count)
    table4_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        f'<table xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" id="4" name="Requesters" displayName="Requesters" ref="D4:D{t4_end}" totalsRowShown="0">\n'
        f'<autoFilter ref="D4:D{t4_end}"/>\n'
        '<tableColumns count="1"><tableColumn id="1" name="Requester Name"/></tableColumns>\n'
        '<tableStyleInfo name="TableStyleLight1" showFirstColumn="0" showLastColumn="0" showRowStripes="1" showColumnStripes="0"/>\n'
        '</table>'
    )

    t3_end = 4 + (fill_to_row - 4 if fill_to_row else grad_count)
    table3_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        f'<table xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" id="3" name="GradStudents" displayName="GradStudents" ref="A4:B{t3_end}" totalsRowShown="0">\n'
        f'<autoFilter ref="A4:B{t3_end}"/>\n'
        '<tableColumns count="2"><tableColumn id="1" name="Grad Student"/><tableColumn id="2" name="Color"/></tableColumns>\n'
        '<tableStyleInfo name="TableStyleLight1" showFirstColumn="0" showLastColumn="0" showRowStripes="1" showColumnStripes="0"/>\n'
        '</table>'
    )

    styles_xml = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"/>'
    metadata_xml = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><metadata xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"/>'
    webext_xml = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><webextension xmlns="http://schemas.microsoft.com/office/webextensions/webextension/2010/11"/>'

    with zipfile.ZipFile(dest_path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("xl/worksheets/sheet1.xml", sheet1_xml)
        z.writestr("xl/worksheets/sheet2.xml", sheet2_xml)
        z.writestr("xl/tables/table3.xml", table3_xml)
        z.writestr("xl/tables/table4.xml", table4_xml)
        z.writestr("xl/styles.xml", styles_xml)
        z.writestr("xl/metadata.xml", metadata_xml)
        z.writestr("xl/webextensions/webextension1.xml", webext_xml)

    return dest_path


@pytest.fixture
def clean_roster(tmp_path, monkeypatch):
    """Provide a fresh roster.json in tmp_path with 13 starting requesters and 3 buyers."""
    r_file = tmp_path / "roster.json"
    monkeypatch.setattr(roster, "ROSTER_PATH", str(r_file))

    data = {
        "requesters": {f"U{i}": name for i, name in enumerate(STARTING_REQUESTERS, start=100)},
        "admins": ["U100"],
        "approvers": ["U07L2RFEPJ9"],
        "buyers": ["U100", "U101", "U102"],  # Isaac, Smeet, Dylan
        "vendors": ["Fisher Scientific", "Grainger"],
    }
    roster.save_roster(data)
    return r_file


# ------------------------------------------------------------------------------
# 1. Signature and writer exclusivity
# ------------------------------------------------------------------------------

def test_sync_roster_lists_exists_and_signature():
    import inspect
    assert hasattr(log_writer, "sync_roster_lists")
    sig = inspect.signature(log_writer.sync_roster_lists)
    assert "workbook_path" in sig.parameters


def test_openpyxl_appears_nowhere_in_src():
    """Verify openpyxl is not used for workbook writes.

    ADR 0006 authorizes openpyxl in src/bom.py for building brand-new BOM spreadsheets
    from scratch. All other modules under src/ (particularly log_writer) must never
    use openpyxl because it destroys x14 conditional formatting in Purchasing-Log.xlsx.
    """
    for root, _, files in os.walk(SRC_DIR):
        for fname in files:
            if fname.endswith(".py") and fname != "bom.py":
                fpath = os.path.join(root, fname)
                with open(fpath, "r", encoding="utf-8") as f:
                    content = f.read()
                    assert "openpyxl" not in content, f"Found 'openpyxl' in {fpath}"


# ------------------------------------------------------------------------------
# 2. Append requester: free row and table ref growth
# ------------------------------------------------------------------------------

def test_sync_appends_new_requester_and_grows_table_ref(tmp_path, clean_roster, monkeypatch):
    wb_path = str(tmp_path / "Purchasing-Log.xlsx")
    create_fixture_workbook(wb_path, req_count=13, grad_count=3)
    monkeypatch.setattr(config, "WORKBOOK_PATH", wb_path)

    # Add a new requester not in sheet (starts at D18)
    roster.add_requester("U_NEW_PERSON", "NewPerson")

    res = log_writer.sync_roster_lists(workbook_path=wb_path)
    assert "NewPerson" in res["requesters_added"]

    with zipfile.ZipFile(wb_path) as z:
        sheet2_xml = z.read("xl/worksheets/sheet2.xml").decode("utf-8")
        table4_xml = z.read("xl/tables/table4.xml").decode("utf-8")

    # Name landed in first free D row (D18)
    assert log_writer.get_cell_value(sheet2_xml, "D18") == "NewPerson"

    # Requesters ref and autoFilter ref both grew to D4:D18
    assert 'ref="D4:D18"' in table4_xml
    assert '<autoFilter ref="D4:D18"/>' in table4_xml


# ------------------------------------------------------------------------------
# 3. Case-insensitive comparison leaves sheet byte-identical
# ------------------------------------------------------------------------------

def test_sync_existing_name_different_case_leaves_sheet_byte_identical(tmp_path, clean_roster, monkeypatch):
    wb_path = str(tmp_path / "Purchasing-Log.xlsx")
    create_fixture_workbook(wb_path, req_count=13, grad_count=3)
    monkeypatch.setattr(config, "WORKBOOK_PATH", wb_path)

    with zipfile.ZipFile(wb_path) as z:
        before_sheet2 = z.read("xl/worksheets/sheet2.xml")

    # Add "isaac" (sheet has "Isaac")
    roster.add_requester("U_LOWER", "isaac")

    res = log_writer.sync_roster_lists(workbook_path=wb_path)
    assert "isaac" not in res["requesters_added"]

    with zipfile.ZipFile(wb_path) as z:
        after_sheet2 = z.read("xl/worksheets/sheet2.xml")

    assert after_sheet2 == before_sheet2


# ------------------------------------------------------------------------------
# 4. Name present in sheet but absent from roster.json is preserved
# ------------------------------------------------------------------------------

def test_sync_preserves_unrostered_name_in_sheet(tmp_path, monkeypatch):
    r_file = tmp_path / "roster.json"
    monkeypatch.setattr(roster, "ROSTER_PATH", str(r_file))
    # Roster only has Isaac
    roster.save_roster({"requesters": {"U1": "Isaac"}, "buyers": []})

    wb_path = str(tmp_path / "Purchasing-Log.xlsx")
    create_fixture_workbook(wb_path, req_count=13, grad_count=3)
    monkeypatch.setattr(config, "WORKBOOK_PATH", wb_path)

    # Sheet has Zehui at D17, which is not in this roster
    res = log_writer.sync_roster_lists(workbook_path=wb_path)
    assert not res["requesters_added"]

    with zipfile.ZipFile(wb_path) as z:
        sheet2_xml = z.read("xl/worksheets/sheet2.xml").decode("utf-8")

    assert log_writer.get_cell_value(sheet2_xml, "D17") == "Zehui"


# ------------------------------------------------------------------------------
# 5. Add buyer: lands in column A, column B empty, GradStudents ref grew
# ------------------------------------------------------------------------------

def test_sync_appends_buyer_and_grows_table3(tmp_path, clean_roster, monkeypatch):
    wb_path = str(tmp_path / "Purchasing-Log.xlsx")
    create_fixture_workbook(wb_path, req_count=13, grad_count=3)
    monkeypatch.setattr(config, "WORKBOOK_PATH", wb_path)

    # Finn (U107) is already in requesters; add as buyer
    roster.add_buyer("U107")

    res = log_writer.sync_roster_lists(workbook_path=wb_path)
    assert "Finn" in res["grads_added"]

    with zipfile.ZipFile(wb_path) as z:
        sheet2_xml = z.read("xl/worksheets/sheet2.xml").decode("utf-8")
        table3_xml = z.read("xl/tables/table3.xml").decode("utf-8")

    # Landed in column A row 8
    assert log_writer.get_cell_value(sheet2_xml, "A8") == "Finn"
    # Column B row 8 is empty
    assert log_writer.get_cell_value(sheet2_xml, "B8") is None

    # GradStudents ref grew to A4:B8
    assert 'ref="A4:B8"' in table3_xml
    assert '<autoFilter ref="A4:B8"/>' in table3_xml


# ------------------------------------------------------------------------------
# 6. remove_buyer leaves sheet byte-identical
# ------------------------------------------------------------------------------

def test_remove_buyer_leaves_sheet_byte_identical(tmp_path, clean_roster, monkeypatch):
    wb_path = str(tmp_path / "Purchasing-Log.xlsx")
    create_fixture_workbook(wb_path, req_count=13, grad_count=3)
    monkeypatch.setattr(config, "WORKBOOK_PATH", wb_path)

    with zipfile.ZipFile(wb_path) as z:
        before_sheet2 = z.read("xl/worksheets/sheet2.xml")

    # Remove Dylan (U102)
    assert roster.remove_buyer("U102") is True
    assert "U102" not in roster.get_buyers()

    res = log_writer.sync_roster_lists(workbook_path=wb_path)
    assert not res["grads_added"]

    with zipfile.ZipFile(wb_path) as z:
        after_sheet2 = z.read("xl/worksheets/sheet2.xml")

    assert after_sheet2 == before_sheet2


# ------------------------------------------------------------------------------
# 7. Row 50 hard floor, skipped report, and ADMIN_ALERT_CHANNEL notification
# ------------------------------------------------------------------------------

def test_sheet_full_skips_and_alerts_admin(tmp_path, monkeypatch):
    r_file = tmp_path / "roster.json"
    monkeypatch.setattr(roster, "ROSTER_PATH", str(r_file))

    # Seed roster with Req5..Req49 already filling the sheet
    existing_reqs = {f"U{r}": f"Req{r}" for r in range(5, 50)}
    roster.save_roster({"requesters": existing_reqs, "buyers": []})

    wb_path = str(tmp_path / "Purchasing-Log.xlsx")
    # Fill rows 5 to 49 with Req5..Req49
    create_fixture_workbook(wb_path, fill_to_row=49)
    monkeypatch.setattr(config, "WORKBOOK_PATH", wb_path)
    monkeypatch.setattr(config, "ADMIN_ALERT_CHANNEL", "C_ALERTS")

    mock_client = MagicMock()

    # Add a 46th requester
    roster.add_requester("U_OVERFLOW", "OverflowName")

    res = log_writer.sync_roster_lists(workbook_path=wb_path, client=mock_client)
    assert "OverflowName" in res["skipped"]

    with zipfile.ZipFile(wb_path) as z:
        sheet2_xml = z.read("xl/worksheets/sheet2.xml").decode("utf-8")

    # Row 50 notes block is untouched
    assert log_writer.get_cell_value(sheet2_xml, "A50") == "Notes: Do not overwrite"
    # Nothing written to D50
    assert log_writer.get_cell_value(sheet2_xml, "D50") is None

    # Alert posted to ADMIN_ALERT_CHANNEL
    mock_client.chat_postMessage.assert_called_once()
    call_args = mock_client.chat_postMessage.call_args[1]
    assert call_args["channel"] == "C_ALERTS"
    assert "OverflowName" in call_args["text"]
    assert "Roles & Lists tab needs more rows above the notes block" in call_args["text"]


# ------------------------------------------------------------------------------
# 8. Locked workbook does not fail roster changes
# ------------------------------------------------------------------------------

def test_locked_workbook_does_not_fail_add_buyer(tmp_path, clean_roster, monkeypatch):
    wb_path = str(tmp_path / "Purchasing-Log.xlsx")
    create_fixture_workbook(wb_path, req_count=13, grad_count=3)
    monkeypatch.setattr(config, "WORKBOOK_PATH", wb_path)

    # Create lock file
    lock_file = tmp_path / "~$Purchasing-Log.xlsx"
    lock_file.write_text("locked", encoding="utf-8")

    # add_buyer must return normally and ID must be in roster.json
    roster.add_buyer("U_LOCKED_BUYER")
    assert "U_LOCKED_BUYER" in roster.get_buyers()


# ------------------------------------------------------------------------------
# 9. Nonexistent workbook does not fail roster changes
# ------------------------------------------------------------------------------

def test_nonexistent_workbook_does_not_fail_add_requester(tmp_path, clean_roster, monkeypatch):
    monkeypatch.setattr(config, "WORKBOOK_PATH", str(tmp_path / "nonexistent.xlsx"))

    # add_requester must succeed and no exception escapes
    roster.add_requester("U_NONEXISTENT", "TestName")
    assert roster.get_requesters()["U_NONEXISTENT"] == "TestName"


# ------------------------------------------------------------------------------
# 10. Round-trip byte-identity of untouched parts and archive order
# ------------------------------------------------------------------------------

def test_round_trip_untouched_parts_and_archive_order(tmp_path, clean_roster, monkeypatch):
    wb_path = str(tmp_path / "Purchasing-Log.xlsx")
    create_fixture_workbook(wb_path, req_count=13, grad_count=3)
    monkeypatch.setattr(config, "WORKBOOK_PATH", wb_path)

    with zipfile.ZipFile(wb_path) as z:
        before_namelist = z.namelist()
        before_sheet1 = z.read("xl/worksheets/sheet1.xml")
        before_styles = z.read("xl/styles.xml")
        before_metadata = z.read("xl/metadata.xml")
        before_webext = z.read("xl/webextensions/webextension1.xml")

    # Add a new requester and sync
    roster.add_requester("U_SYNC", "SyncRequester")
    log_writer.sync_roster_lists(workbook_path=wb_path)

    with zipfile.ZipFile(wb_path) as z:
        after_namelist = z.namelist()
        after_sheet1 = z.read("xl/worksheets/sheet1.xml")
        after_styles = z.read("xl/styles.xml")
        after_metadata = z.read("xl/metadata.xml")
        after_webext = z.read("xl/webextensions/webextension1.xml")

    # Archive part order must be unchanged
    assert after_namelist == before_namelist
    # Untouched parts must be byte-identical
    assert after_sheet1 == before_sheet1
    assert after_styles == before_styles
    assert after_metadata == before_metadata
    assert after_webext == before_webext


# ------------------------------------------------------------------------------
# 11. x14:conditionalFormatting survives sync
# ------------------------------------------------------------------------------

def test_x14_conditional_formatting_survives_sync(tmp_path, clean_roster, monkeypatch):
    wb_path = str(tmp_path / "Purchasing-Log.xlsx")
    create_fixture_workbook(wb_path, req_count=13, grad_count=3)
    monkeypatch.setattr(config, "WORKBOOK_PATH", wb_path)

    roster.add_requester("U_SYNC2", "SyncRequester2")
    log_writer.sync_roster_lists(workbook_path=wb_path)

    with zipfile.ZipFile(wb_path) as z:
        sheet1_xml = z.read("xl/worksheets/sheet1.xml").decode("utf-8")

    assert "<x14:conditionalFormatting" in sheet1_xml


# ------------------------------------------------------------------------------
# 12. /roster-set-name accepts Hansel and Zehui, and VALID_REQUESTERS deleted from src/
# ------------------------------------------------------------------------------

def test_roster_set_name_accepts_hansel_and_zehui(clean_roster, monkeypatch):
    monkeypatch.setattr(config, "ADMIN_ALERT_CHANNEL", "C_ALERTS")
    client = MagicMock()
    requesters = roster.get_requesters()
    name_to_id = {n: uid for uid, n in requesters.items()}

    for name in ("Hansel", "Zehui"):
        user_id = name_to_id.get(name, f"U_{name.upper()}")
        ack = MagicMock()
        view = {
            "state": {"values": {"block_proposed_name": {"proposed_name": {"value": name}}}},
            "private_metadata": json.dumps({"user_id": user_id, "channel_id": "C_MAIN"}),
        }
        app.handle_roster_set_name_submit(ack, {"user": {"id": user_id}}, client, view)

        # ack() called with no errors (or ack.call_args[1].get("response_action") != "errors")
        ack.assert_called_once()
        call_kwargs = ack.call_args[1]
        assert call_kwargs.get("response_action") != "errors", f"{name} was rejected by modal validation"



def test_valid_requesters_appears_nowhere_in_src():
    pattern = re.compile(r"\bVALID_REQUESTERS\b")
    for root, _, files in os.walk(SRC_DIR):
        for fname in files:
            if fname.endswith(".py"):
                fpath = os.path.join(root, fname)
                with open(fpath, "r", encoding="utf-8") as f:
                    content = f.read()
                    match = pattern.search(content)
                    assert match is None, f"Found 'VALID_REQUESTERS' in {fpath}"
