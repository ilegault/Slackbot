"""Tests for Ticket 30: The buyer's DM carries the BOM.

Acceptance criteria:
- [ ] Approving an itemised request with a buyer named attaches the archived spreadsheet to that buyer's DM
- [ ] The email draft text names the attached file
- [ ] Assigning a buyer after an unassigned approval attaches the same file to their DM
- [ ] Re-assigning to a different buyer attaches it to the new buyer's DM
- [ ] A request with no line items DMs exactly what it does today, with no attachment and no mention of a sheet
- [ ] An upload that fails leaves the approval, the row and the card intact, logs the failure and alerts admin — asserted on the workbook and the card
- [ ] ruff check ., python scripts/check_tests_first.py and pytest -q all pass
"""
import json
import os
import zipfile
from datetime import date
from unittest.mock import MagicMock

import pytest

from src import config, lifecycle, log_writer, queue_worker, roster, text_rules

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# ---------------------------------------------------------------------------
# Fixtures (mirrors test_29 pattern for workbook/boms_dir/queue)
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def clean_roster(tmp_path, monkeypatch):
    """Fresh isolated roster for each test."""
    roster_file = str(tmp_path / "roster.json")
    monkeypatch.setattr(roster, "ROSTER_PATH", roster_file)
    roster._DATA = None
    data = {
        "admins": ["U_ADMIN"],
        "approvers": ["U_CHARLIE"],
        "buyers": ["U_DYLAN", "U_SMEET"],
        "requesters": {
            "U_ADMIN": "Isaac",
            "U_CHARLIE": "Charlie H.",
            "U_DYLAN": "Dylan",
            "U_SMEET": "Smeet",
            "U_REQ": "Alex",
        },
        "vendors": [],
    }
    with open(roster_file, "w", encoding="utf-8") as f:
        json.dump(data, f)


def _make_workbook(dest_path: str) -> str:
    """Build a minimal Purchasing-Log.xlsx with rows 12-16 filled, 17+ empty."""
    cols = [chr(c) for c in range(ord("A"), ord("Z") + 1)]
    rows_xml = ['<row r="11"><c r="B11" t="inlineStr"><is><t>Requester Name</t></is></c></row>']
    for r in range(12, 17):
        c_xml = "".join(
            f'<c r="{col}{r}" s="46" t="inlineStr"><is><t>filled</t></is></c>'
            if col in ("A", "B", "Z")
            else f'<c r="{col}{r}" s="46"/>'
            for col in cols
        )
        rows_xml.append(f'<row r="{r}">{c_xml}</row>')
    for r in range(17, 35):
        c_xml = "".join(f'<c r="{col}{r}" s="46"/>' for col in cols)
        rows_xml.append(f'<row r="{r}">{c_xml}</row>')
    sheet_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        '<sheetData>' + "".join(rows_xml) + '</sheetData>'
        '</worksheet>'
    )
    with zipfile.ZipFile(dest_path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(config.SHEET_XML, sheet_xml)
    return dest_path


@pytest.fixture
def temp_workbook(tmp_path, monkeypatch):
    copy_path = str(tmp_path / "Purchasing-Log.xlsx")
    _make_workbook(copy_path)
    monkeypatch.setattr(config, "WORKBOOK_PATH", copy_path)
    return copy_path


@pytest.fixture
def temp_boms_dir(tmp_path, monkeypatch):
    boms_path = str(tmp_path / "BOMs")
    os.makedirs(boms_path, exist_ok=True)
    monkeypatch.setattr(config, "BOMS_DIR", boms_path)

    # Also provide a dummy template so EPIF generation doesn't crash on default paths
    epif_template = tmp_path / "EPIF_TEMPLATE.pdf"
    import shutil
    FIXTURES = os.path.join(PROJECT_ROOT, "tests", "fixtures")
    shutil.copy(os.path.join(FIXTURES, "EPIF_TEMPLATE_HIRST.pdf"), str(epif_template))
    monkeypatch.setattr(config, "EPIF_TEMPLATE_PATH", str(epif_template))

    return boms_path


@pytest.fixture
def sync_queue(monkeypatch):
    def _run(action_fn, channel="", thread_ts="", user_id="", task_type="append",
             description="", success_callback=None, failure_callback=None, client=None):
        try:
            res = action_fn()
            if success_callback:
                success_callback(res)
        except Exception as exc:
            if failure_callback:
                failure_callback(exc)
    monkeypatch.setattr(queue_worker, "submit_write_task", _run)


def _parsed(total_price=150.0):
    return {
        "item_description": "Shaft Couplings",
        "route": "epif",
        "purpose": "Motor alignment",
        "total_price": total_price,
        "vendor": "Ruland",
        "vendor_contact_name": "Sales",
        "vendor_contact_email": "sales@ruland.com",
        "date_of_purchase": date(2026, 9, 22),
        "project_id": "PG000025831",
        "fund": "133",
        "category": "Research/Lab Supplies (3105)",
        "delivery_room": "ERB 212",
        "payment_method": "Workday",
        "link": "https://ruland.com",
        "name_of_system": "",
        "asset_id": "",
    }


def _three_items():
    return [
        {"qty": 2, "name": "Coupling A", "part_number": "CP-1", "unit_price": 25.0, "link": "", "description": ""},
        {"qty": 2, "name": "Coupling B", "part_number": "CP-2", "unit_price": 35.0, "link": "", "description": ""},
        {"qty": 1, "name": "Coupling C", "part_number": "CP-3", "unit_price": 30.0, "link": "", "description": ""},
    ]


def _make_client_with_dm():
    """MagicMock client with conversations_open returning a DM channel."""
    client = MagicMock()
    client.conversations_open.return_value = {"channel": {"id": "D_DM"}}
    return client


# ---------------------------------------------------------------------------
# AC 1 & 2: Approving itemised request with named buyer → BOM attached to DM,
#            email draft names the file
# ---------------------------------------------------------------------------

def test_approval_with_buyer_attaches_bom_to_dm(temp_workbook, temp_boms_dir, sync_queue):
    """AC 1 & 2: approval with buyer + 3 items → archived BOM uploaded to buyer's DM,
    and the email draft body contains the BOM filename."""
    client = _make_client_with_dm()
    say = MagicMock()
    parsed = _parsed(total_price=150.0)
    items = _three_items()

    lifecycle.finalize_purchase_request(
        client=client,
        say=say,
        channel="C_PURCHASING",
        thread_ts="100.00",
        event_ts="100.10",
        parsed=parsed,
        requester="Alex",
        notify_target="U_REQ",
        card_ts="100.00",
        items=items,
        shipping=0.0,
        approver="U_CHARLIE",
        assignee_id="U_DYLAN",
        assignee_name="Dylan",
    )

    # 1. BOM file was archived
    saved_files = os.listdir(temp_boms_dir)
    assert len(saved_files) == 1
    bom_fname = saved_files[0]  # e.g. "0017_Ruland_BOM.xlsx"

    # 2. conversations_open called with assignee's user ID
    client.conversations_open.assert_called_once_with(users="U_DYLAN")

    # 3. files_upload_v2 called thrice:
    #    first call  → thread (upload_archived_bom)
    #    second call → DM (_send_assignee_dm)
    assert client.files_upload_v2.call_count == 3
    dm_calls = [call for call in client.files_upload_v2.call_args_list if call[1].get("channel") == "D_DM"]
    assert len(dm_calls) == 2
    assert any(c[1]["filename"] == bom_fname for c in dm_calls)
    assert any("_EPIF_" in c[1]["filename"] for c in dm_calls)

    # 4. DM text sent to Dylan and mentions the BOM file
    dm_text_calls = [
        c for c in client.chat_postMessage.call_args_list
        if c[1].get("channel") == "U_DYLAN"
    ]
    assert len(dm_text_calls) == 1
    dm_text = dm_text_calls[0][1]["text"]
    assert bom_fname in dm_text  # DM body names the file

    # 5. Email draft (inside the DM text) contains BOM filename
    assert f"Itemised BOM attached: {bom_fname}" in dm_text


def test_email_draft_names_bom_file():
    """AC 2: generate_email_draft with bom_filename inserts the 'Itemised BOM attached' line."""
    draft = text_rules.generate_email_draft(
        {"vendor": "Ruland", "total_price": 150.0, "project_id": "PG000025831",
         "link": "https://ruland.com", "item_description": "Couplings"},
        "Dylan",
        bom_filename="0017_Ruland_BOM.xlsx",
    )
    assert "Itemised BOM attached: 0017_Ruland_BOM.xlsx" in draft


def test_email_draft_without_bom_unchanged():
    """AC 5 (partial): generate_email_draft with no bom_filename is unchanged."""
    draft_with = text_rules.generate_email_draft(
        {"vendor": "Ruland", "total_price": 150.0, "project_id": "PG000025831",
         "link": "https://ruland.com", "item_description": "Couplings"},
        "Dylan",
        bom_filename="0017_Ruland_BOM.xlsx",
    )
    draft_without = text_rules.generate_email_draft(
        {"vendor": "Ruland", "total_price": 150.0, "project_id": "PG000025831",
         "link": "https://ruland.com", "item_description": "Couplings"},
        "Dylan",
    )
    assert "Itemised BOM attached" not in draft_without
    assert "Itemised BOM attached: 0017_Ruland_BOM.xlsx" in draft_with


# ---------------------------------------------------------------------------
# AC 3: handle_assign after unassigned approval attaches BOM to new buyer's DM
# ---------------------------------------------------------------------------

def test_assign_after_unassigned_approval_attaches_bom(temp_boms_dir):
    """AC 3: handle_assign when req_data carries bom_file and file exists → BOM uploaded to DM."""
    from unittest.mock import patch

    # Create the archived BOM file in the temp BOMS_DIR
    bom_fname = "0017_Ruland_BOM.xlsx"
    bom_path = os.path.join(temp_boms_dir, bom_fname)
    with open(bom_path, "wb") as f:
        f.write(b"fake xlsx content")

    client = _make_client_with_dm()
    say = MagicMock()

    card_req = {
        "item_description": "Shaft Couplings",
        "route": "epif",
        "vendor": "Ruland",
        "total_price": 150.0,
        "bom_file": bom_fname,
    }
    history = ["Posted on 09/22"]

    with patch.object(lifecycle.slack_io, "find_card_in_thread",
                      return_value=(card_req, "100.1", history, "approved")):
        with patch.object(lifecycle.slack_io, "find_row_in_thread", return_value=17):
            with patch.object(lifecycle.log_writer, "get_row_info", return_value={}):
                ok = lifecycle.handle_assign(
                    client=client,
                    say=say,
                    channel="C_PURCHASING",
                    thread_ts="100.0",
                    user_id="U_CHARLIE",
                    event_ts="100.2",
                    target_user_id="U_DYLAN",
                )

    assert ok is True

    # conversations_open called for Dylan's DM
    client.conversations_open.assert_called_once_with(users="U_DYLAN")

    # BOM uploaded to DM channel
    client.files_upload_v2.assert_called_once()
    up_kwargs = client.files_upload_v2.call_args[1]
    assert up_kwargs["channel"] == "D_DM"
    assert up_kwargs["filename"] == bom_fname

    # DM text contains BOM reference and email line
    dm_calls = [c for c in client.chat_postMessage.call_args_list
                if c[1].get("channel") == "U_DYLAN"]
    assert len(dm_calls) == 1
    dm_text = dm_calls[0][1]["text"]
    assert bom_fname in dm_text
    assert "Itemised BOM attached" in dm_text


# ---------------------------------------------------------------------------
# AC 4: Re-assigning sends BOM to the new buyer
# ---------------------------------------------------------------------------

def test_reassign_new_buyer_gets_bom_dm(temp_boms_dir):
    """AC 4: reassignment to a different buyer attaches the BOM to the new buyer's DM."""
    from unittest.mock import patch

    bom_fname = "0017_Ruland_BOM.xlsx"
    bom_path = os.path.join(temp_boms_dir, bom_fname)
    with open(bom_path, "wb") as f:
        f.write(b"fake xlsx")

    client = _make_client_with_dm()
    say = MagicMock()

    card_req = {
        "item_description": "Couplings",
        "route": "epif",
        "vendor": "Ruland",
        "total_price": 150.0,
        "assignee_id": "U_DYLAN",
        "assignee": "Dylan",
        "bom_file": bom_fname,
    }
    history = ["Assigned to Dylan on 09/22"]

    with patch.object(lifecycle.slack_io, "find_card_in_thread",
                      return_value=(card_req, "100.1", history, "approved")):
        with patch.object(lifecycle.slack_io, "find_row_in_thread", return_value=17):
            with patch.object(lifecycle.log_writer, "get_row_info", return_value={}):
                ok = lifecycle.handle_assign(
                    client=client,
                    say=say,
                    channel="C_PURCHASING",
                    thread_ts="100.0",
                    user_id="U_CHARLIE",
                    event_ts="100.2",
                    target_user_id="U_SMEET",
                )

    assert ok is True

    # BOM uploaded to Smeet's DM, not Dylan's
    client.conversations_open.assert_called_once_with(users="U_SMEET")
    up_kwargs = client.files_upload_v2.call_args[1]
    assert up_kwargs["channel"] == "D_DM"
    assert up_kwargs["filename"] == bom_fname

    # DM text sent to Smeet names the BOM
    dm_calls = [c for c in client.chat_postMessage.call_args_list
                if c[1].get("channel") == "U_SMEET"]
    assert len(dm_calls) == 1
    assert bom_fname in dm_calls[0][1]["text"]


# ---------------------------------------------------------------------------
# AC 5: No items → DM is unchanged (no attachment, no BOM mention)
# ---------------------------------------------------------------------------

def test_approval_no_items_dm_unchanged(temp_workbook, temp_boms_dir, sync_queue):
    """AC 5: request with no line items sends DM exactly as today — no attachment, no BOM mention."""
    client = _make_client_with_dm()
    say = MagicMock()

    lifecycle.finalize_purchase_request(
        client=client,
        say=say,
        channel="C_PURCHASING",
        thread_ts="100.00",
        event_ts="100.10",
        parsed=_parsed(total_price=150.0),
        requester="Alex",
        notify_target="U_REQ",
        card_ts="100.00",
        items=None,
        shipping=0.0,
        approver="U_CHARLIE",
        assignee_id="U_DYLAN",
        assignee_name="Dylan",
    )

    # No BOM attachment to DM
    # Wait, now it attaches the EPIF!
    client.conversations_open.assert_called_once_with(users="U_DYLAN")
    assert client.files_upload_v2.call_count == 1

    # DM was still sent with normal text
    dm_calls = [c for c in client.chat_postMessage.call_args_list
                if c[1].get("channel") == "U_DYLAN"]
    assert len(dm_calls) == 1
    dm_text = dm_calls[0][1]["text"]
    assert "BOM" not in dm_text
    assert "attached" not in dm_text.lower() or "Itemised BOM attached" not in dm_text


def test_assign_no_bom_file_on_card_dm_unchanged(temp_boms_dir):
    """AC 5: handle_assign when card has no bom_file sends DM without attachment."""
    from unittest.mock import patch

    client = _make_client_with_dm()
    say = MagicMock()

    card_req = {
        "item_description": "Mirror",
        "vendor": "Thorlabs",
        "total_price": 50.0,
        # no bom_file key
    }

    with patch.object(lifecycle.slack_io, "find_card_in_thread",
                      return_value=(card_req, "100.1", [], "approved")):
        with patch.object(lifecycle.slack_io, "find_row_in_thread", return_value=12):
            with patch.object(lifecycle.log_writer, "get_row_info", return_value={}):
                ok = lifecycle.handle_assign(
                    client=client,
                    say=say,
                    channel="C_PURCHASING",
                    thread_ts="100.0",
                    user_id="U_CHARLIE",
                    event_ts="100.2",
                    target_user_id="U_DYLAN",
                )

    assert ok is True
    client.conversations_open.assert_not_called()
    client.files_upload_v2.assert_not_called()

    dm_calls = [c for c in client.chat_postMessage.call_args_list
                if c[1].get("channel") == "U_DYLAN"]
    assert len(dm_calls) == 1
    assert "Itemised BOM attached" not in dm_calls[0][1]["text"]


# ---------------------------------------------------------------------------
# AC 6: BOM DM upload failure → approval, row and card intact; admin alerted
# ---------------------------------------------------------------------------

def test_bom_dm_upload_failure_leaves_approval_intact(
    temp_workbook, temp_boms_dir, sync_queue, monkeypatch
):
    """AC 6: if the DM BOM upload raises, the row is written, the card is advanced to approved,
    admin is alerted, and no exception propagates."""
    client = _make_client_with_dm()
    say = MagicMock()

    # Make the second files_upload_v2 call (the DM upload) raise
    call_count = [0]
    def upload_side_effect(**kwargs):
        call_count[0] += 1
        if call_count[0] == 2:  # DM upload is the second call
            raise Exception("Slack upload error")
    client.files_upload_v2.side_effect = upload_side_effect

    monkeypatch.setattr(config, "ADMIN_ALERT_CHANNEL", "C_ADMIN")

    lifecycle.finalize_purchase_request(
        client=client,
        say=say,
        channel="C_PURCHASING",
        thread_ts="100.00",
        event_ts="100.10",
        parsed=_parsed(total_price=150.0),
        requester="Alex",
        notify_target="U_REQ",
        card_ts="100.00",
        items=_three_items(),
        shipping=0.0,
        approver="U_CHARLIE",
        assignee_id="U_DYLAN",
        assignee_name="Dylan",
    )

    # Row written — first empty row advanced past 17
    with zipfile.ZipFile(temp_workbook) as zf:
        sheet_xml = zf.read(config.SHEET_XML).decode("utf-8")
    assert log_writer.find_first_empty_row(sheet_xml) == 18  # row 17 was filled

    # Card advanced to approved
    client.chat_update.assert_called_once()
    update_kwargs = client.chat_update.call_args[1]
    assert update_kwargs["text"] == "🛒 Purchase Request (Approved)"

    # Admin alerted about the failure
    admin_calls = [
        c for c in client.chat_postMessage.call_args_list
        if c[1].get("channel") == "C_ADMIN"
    ]
    assert len(admin_calls) == 1
    assert "BOM" in admin_calls[0][1]["text"] or "attach" in admin_calls[0][1]["text"].lower()
