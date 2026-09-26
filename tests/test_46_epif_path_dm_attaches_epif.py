"""Tests for Ticket 46: EPIF-path buyer gets the filled EPIF in the DM, and the thread says to email purchasing."""
import json
import os
from datetime import date
from unittest.mock import MagicMock

import pytest

from src import config, lifecycle, log_writer, queue_worker, roster, slack_io, validators

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SAMPLES = os.path.join(PROJECT_ROOT, "samples")
FIXTURES = os.path.join(PROJECT_ROOT, "tests", "fixtures")

def _valid_request(total_price=50.0, category="Supplies"):
    return {
        "item_description": "Shaft Couplings",
        "purpose": "Motor test stand alignment",
        "total_price": total_price,
        "vendor": "Test Vendor",
        "vendor_contact_name": "Sales",
        "vendor_contact_email": "sales@ruland.com",
        "date_of_purchase": date(2026, 9, 22),
        "project_id": "PG000025831",
        "fund": "133",
        "category": category,
        "delivery_room": "ERB 212",
        "payment_method": "Workday",
        "link": "https://ruland.com",
        "name_of_system": "",
        "asset_id": ""
    }

@pytest.fixture(autouse=True)
def clean_roster(tmp_path, monkeypatch):
    roster_file = str(tmp_path / "roster.json")
    monkeypatch.setattr(roster, "ROSTER_PATH", roster_file)
    roster._DATA = None
    data = {
        "admins": ["U_ADMIN"],
        "approvers": ["U_CHARLIE"],
        "buyers": ["U_BUYER"],
        "requesters": {
            "U_ADMIN": "Isaac",
            "U_CHARLIE": "Charlie H.",
            "U_BUYER": "Dylan",
            "U_REQ": "Alex",
        },
        "vendors": [],
    }
    with open(roster_file, "w", encoding="utf-8") as f:
        json.dump(data, f)

    monkeypatch.setattr(validators, "validate", lambda *args, **kwargs: [])
    # mock log_writer behavior so it doesn't try to write to a real zip file during tests
    def fake_save_epif(content, archive_name):
        path = os.path.join(config.EPIFS_DIR, archive_name)
        with open(path, "wb") as f:
            f.write(content or b"")
        return path
    monkeypatch.setattr(log_writer, "save_epif", fake_save_epif)

    def fake_save_bom(xlsx_bytes, fname):
        path = os.path.join(config.BOMS_DIR, fname)
        with open(path, "wb") as f:
            f.write(xlsx_bytes or b"")
        return path
    from src import log_writer as lw_mod
    monkeypatch.setattr(lw_mod, "save_bom", fake_save_bom)

    monkeypatch.setattr(log_writer, "append_row", lambda row_vals: 17)
    monkeypatch.setattr(log_writer, "build_row", lambda parsed, req: {})
    monkeypatch.setattr(log_writer, "update_row", lambda row, fields: None)
    monkeypatch.setattr(log_writer, "get_row_info", lambda row: {})

@pytest.fixture
def temp_epifs_dir(tmp_path, monkeypatch):
    d = str(tmp_path / "EPIFs")
    os.makedirs(d)
    monkeypatch.setattr(config, "EPIFS_DIR", d)
    monkeypatch.setattr(config, "TEMPLATE_DIR", FIXTURES)
    return d

@pytest.fixture
def temp_boms_dir(tmp_path, monkeypatch):
    d = str(tmp_path / "BOMs")
    os.makedirs(d)
    monkeypatch.setattr(config, "BOMS_DIR", d)
    return d

@pytest.fixture
def sync_queue(monkeypatch):
    def fake_submit(action_fn, *args, **kwargs):
        # We also need to trigger the success callback which does the thread messages
        result = action_fn()
        if "success_callback" in kwargs and kwargs["success_callback"]:
            kwargs["success_callback"](result)
        return result
    monkeypatch.setattr(queue_worker, "submit_write_task", fake_submit)

def test_epif_path_dm_attaches_epif_and_thread_message(temp_epifs_dir, temp_boms_dir, sync_queue):
    client = MagicMock()
    client.conversations_open.return_value = {"channel": {"id": "D_BUYER"}}
    say = MagicMock()

    parsed = _valid_request(total_price=50.0, category="Supplies")
    pdf_bytes = b"fake_pdf_content"

    lifecycle.finalize_purchase_request(
        client=client,
        say=say,
        channel="C123",
        thread_ts="111.222",
        event_ts="111.333",
        parsed=parsed,
        requester="U_REQ",
        notify_target="U_REQ",
        assignee_id="U_BUYER",
        assignee_name="Dylan",
        approver="U_CHARLIE",
        pdf_bytes=pdf_bytes,
        file_name="uploaded_epif.pdf"
    )

    say_calls = say.call_args_list
    say_text = say_calls[0][1]["text"]
    assert "👤 Assigned to <@U_BUYER> (Dylan) to email to purchasing." in say_text

    client.files_upload_v2.assert_called_once()
    upload_kwargs = client.files_upload_v2.call_args[1]
    assert upload_kwargs["channel"] == "D_BUYER"
    assert "_EPIF.pdf" in upload_kwargs["filename"] or "_EPIF_" in upload_kwargs["filename"]

    tell_calls = [c for c in client.chat_postMessage.call_args_list if c[1].get("channel") == "U_BUYER"]
    assert tell_calls
    dm_text = tell_calls[0][1]["text"]
    assert "to purchasing (Tina / Ally / Lisa):" in dm_text
    assert "```" in dm_text

def test_unassigned_epif_path_thread_message(temp_epifs_dir, temp_boms_dir, sync_queue):
    client = MagicMock()
    say = MagicMock()

    parsed = _valid_request(total_price=50.0, category="Supplies")
    pdf_bytes = b"fake_pdf_content"

    lifecycle.finalize_purchase_request(
        client=client,
        say=say,
        channel="C123",
        thread_ts="111.222",
        event_ts="111.333",
        parsed=parsed,
        requester="U_REQ",
        notify_target="U_REQ",
        approver="U_CHARLIE",
        pdf_bytes=pdf_bytes,
        file_name="uploaded_epif.pdf"
    )

    say_calls = say.call_args_list
    say_text = say_calls[0][1]["text"]
    assert "⚠️ *Needs a buyer to email to purchasing.*" in say_text

def test_workday_path_makes_no_upload(temp_epifs_dir, temp_boms_dir, sync_queue):
    client = MagicMock()
    client.conversations_open.return_value = {"channel": {"id": "D_BUYER"}}
    say = MagicMock()

    parsed = _valid_request(total_price=50.0, category="Software")

    lifecycle.finalize_purchase_request(
        client=client,
        say=say,
        channel="C123",
        thread_ts="111.222",
        event_ts="111.333",
        parsed=parsed,
        requester="U_REQ",
        notify_target="U_REQ",
        assignee_id="U_BUYER",
        assignee_name="Dylan",
        approver="U_CHARLIE"
    )

    say_calls = say.call_args_list
    say_text = say_calls[0][1]["text"]
    assert "👤 Assigned to <@U_BUYER> (Dylan) to place in Workday." in say_text

    client.files_upload_v2.assert_not_called()

def test_epif_path_with_bom_uploads_both(temp_epifs_dir, temp_boms_dir, sync_queue):
    client = MagicMock()
    client.conversations_open.return_value = {"channel": {"id": "D_BUYER"}}
    say = MagicMock()

    parsed = _valid_request(total_price=50.0, category="Supplies")

    items = [
        {"desc": "Item 1", "qty": 1, "unit_price": 20.0, "total": 20.0, "part_number": "", "link": ""},
        {"desc": "Item 2", "qty": 1, "unit_price": 30.0, "total": 30.0, "part_number": "", "link": ""},
    ]

    pdf_bytes = b"fake_pdf_content"

    lifecycle.finalize_purchase_request(
        client=client,
        say=say,
        channel="C123",
        thread_ts="111.222",
        event_ts="111.333",
        parsed=parsed,
        requester="U_REQ",
        notify_target="U_REQ",
        assignee_id="U_BUYER",
        assignee_name="Dylan",
        approver="U_CHARLIE",
        items=items,
        pdf_bytes=pdf_bytes,
        file_name="uploaded_epif.pdf"
    )

    assert client.files_upload_v2.call_count == 3
    dm_calls = [call for call in client.files_upload_v2.call_args_list if call[1].get("channel") == "D_BUYER"]
    assert len(dm_calls) == 2
    filenames = [call[1]["filename"] for call in dm_calls]
    assert any("_BOM.xlsx" in f for f in filenames)
    assert any(f.endswith("_TestVendor_EPIF.pdf") or "_EPIF_" in f for f in filenames)

def test_handle_assign_uploads_epif(temp_epifs_dir, temp_boms_dir, sync_queue, monkeypatch):
    client = MagicMock()
    client.conversations_open.return_value = {"channel": {"id": "D_BUYER"}}
    say = MagicMock()

    fake_epif_fname = "0001_TestVendor_EPIF.pdf"
    fake_epif_path = os.path.join(temp_epifs_dir, fake_epif_fname)
    with open(fake_epif_path, "wb") as f:
        f.write(b"fake pdf content")

    req_data = {
        "state": "approved",
        "epif_file": fake_epif_fname,
        "parsed": _valid_request(total_price=50.0, category="Supplies")
    }

    monkeypatch.setattr(slack_io, "find_row_in_thread", lambda *a, **k: 1)
    monkeypatch.setattr(slack_io, "resolve_requester", lambda *a, **k: "Dylan")
    from src import interview
    monkeypatch.setattr(interview, "get_request_route", lambda *a, **k: "epif")

    lifecycle.handle_assign(
        client=client,
        say=say,
        channel="C123",
        thread_ts="111.222",
        event_ts="111.333",
        user_id="U_ADMIN",
        target_user_id="U_BUYER",
        req_data=req_data,
        current_state="approved",
        history=[],
        msg_ts="111.222"
    )

    client.files_upload_v2.assert_called_once()
    upload_kwargs = client.files_upload_v2.call_args[1]
    assert upload_kwargs["filename"] == fake_epif_fname
