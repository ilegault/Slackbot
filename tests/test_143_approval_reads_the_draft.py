"""Tests for Ticket 143: Approval reads the item links back from the draft BOM.

Acceptance criteria:
- [ ] test_archived_bom_has_the_drafts_links_and_reasons
- [ ] test_newest_bot_draft_wins_and_requester_files_are_ignored
- [ ] test_missing_draft_still_approves_and_asks_for_replace_bom
- [ ] test_mismatched_draft_is_refused
- [ ] test_items_with_links_skip_the_lookup
"""
import datetime
import json
import os
import zipfile
from datetime import date
from unittest.mock import MagicMock

import openpyxl
import pytest

from src import bom, config, lifecycle, log_writer, queue_worker, roster, slack_io
from tests.test_29_approval_archives_bom import create_test_workbook


@pytest.fixture(autouse=True)
def clean_roster(tmp_path, monkeypatch):
    """Ensure a fresh isolated roster for each test."""
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
    return roster_file


@pytest.fixture
def temp_workbook(tmp_path, monkeypatch):
    """Create a temp copy of Purchasing-Log.xlsx and set config.WORKBOOK_PATH."""
    copy_path = str(tmp_path / "Purchasing-Log.xlsx")
    create_test_workbook(copy_path)
    monkeypatch.setattr(config, "WORKBOOK_PATH", copy_path)
    return copy_path


@pytest.fixture
def temp_boms_dir(tmp_path, monkeypatch):
    """Create a temp BOMs directory and set config.BOMS_DIR."""
    boms_path = str(tmp_path / "BOMs")
    os.makedirs(boms_path, exist_ok=True)
    monkeypatch.setattr(config, "BOMS_DIR", boms_path)
    return boms_path


@pytest.fixture
def sync_queue(monkeypatch):
    """Execute queue write tasks synchronously."""
    def _sync_submit(action_fn, channel="", thread_ts="", user_id="", task_type="append",
                     description="", success_callback=None, failure_callback=None, client=None):
        try:
            res = action_fn()
            if success_callback:
                success_callback(res)
        except Exception as exc:
            if failure_callback:
                failure_callback(exc)

    monkeypatch.setattr(queue_worker, "submit_write_task", _sync_submit)
    return _sync_submit


def _valid_request(total_price=150.0):
    return {
        "item_description": "Shaft Couplings",
        "purpose": "Motor test stand alignment",
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


def _card_items_without_links():
    return [
        {"qty": 2, "name": "Coupling A", "part_number": "CP-1", "unit_price": 25.0, "description": "5mm"},
        {"qty": 2, "name": "Coupling B", "part_number": "CP-2", "unit_price": 35.0, "description": "8mm"},
        {"qty": 1, "name": "Coupling C", "part_number": "CP-3", "unit_price": 30.0, "description": "10mm"},
    ]


def _setup_fake_client(thread_messages, card_payload):
    client = MagicMock()
    client.auth_test.return_value = {"ok": True, "user_id": "B_BOT"}
    client.conversations_open.return_value = {"channel": {"id": "D_BUYER"}}
    client.chat_postMessage.return_value = {"ok": True, "ts": "500.0"}
    client.chat_update.return_value = {"ok": True}
    client.reactions_add.return_value = {"ok": True}

    messages = [
        {
            "ts": "100.00",
            "metadata": {
                "event_type": "purchase_request",
                "event_payload": card_payload,
            },
            "blocks": [],
        }
    ] + thread_messages
    client.conversations_replies.return_value = {"messages": messages}
    return client


def test_archived_bom_has_the_drafts_links_and_reasons(temp_workbook, temp_boms_dir, sync_queue, monkeypatch):
    """Card items (three, no link key) + draft carrying 1 link and 2 reasons -> archived BOM has hyperlinks and reasons."""
    parsed = _valid_request(150.0)
    card_items = _card_items_without_links()

    draft_items = [
        {"qty": 2, "name": "Coupling A", "part_number": "CP-1", "unit_price": 25.0, "description": "5mm",
         "link": "https://example.com/coupling-a"},
        {"qty": 2, "name": "Coupling B", "part_number": "CP-2", "unit_price": 35.0, "description": "8mm",
         "no_link_reason": "No web page"},
        {"qty": 1, "name": "Coupling C", "part_number": "CP-3", "unit_price": 30.0, "description": "10mm",
         "no_link_reason": "Covered by another row's link"},
    ]
    draft_bytes = bom.build_bom_workbook(parsed, draft_items)

    draft_file = {"id": "F_DRAFT", "name": "DRAFT_HIRST_LAB_BOM_Shaft-Couplings_11.02.2026.xlsx"}
    thread_msgs = [
        {"user": "B_BOT", "ts": "101.00", "files": [draft_file]},
    ]
    card_payload = {
        "parsed": parsed,
        "requester": "Alex",
        "user_id": "U_REQ",
        "items": card_items,
        "shipping": 0.0,
        "thread_ts": "100.00",
    }
    client = _setup_fake_client(thread_msgs, card_payload)
    say = MagicMock()

    monkeypatch.setattr(slack_io, "download_file", lambda f: draft_bytes)
    monkeypatch.setattr(slack_io, "resolve_requester", lambda cl, uid: "Alex" if uid == "U_REQ" else "Dylan")
    draft_spy = MagicMock(side_effect=slack_io.newest_bot_draft_bom)
    monkeypatch.setattr(slack_io, "newest_bot_draft_bom", draft_spy)

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
        items=card_items,
        approver="U_CHARLIE",
    )

    expected_fname = f"HIRST_LAB_BOM_Shaft-Couplings_{datetime.date.today():%m.%d.%Y}.xlsx"
    saved_bom_path = os.path.join(temp_boms_dir, expected_fname)
    assert os.path.exists(saved_bom_path)

    wb = openpyxl.load_workbook(saved_bom_path)
    ws = wb.active
    assert ws["D6"].hyperlink is not None
    assert ws["D6"].hyperlink.target == "https://example.com/coupling-a"
    assert ws["A6"].hyperlink is not None
    assert ws["A6"].hyperlink.target == "https://example.com/coupling-a"
    assert ws["D7"].value == "No web page"
    assert ws["D8"].value == "Covered by another row's link"


def test_newest_bot_draft_wins_and_requester_files_are_ignored(temp_workbook, temp_boms_dir, sync_queue, monkeypatch):
    """Two bot drafts (ts 1.1, 1.2) + requester-posted draft -> archive carries links of ts 1.2 draft."""
    parsed = _valid_request(150.0)
    card_items = _card_items_without_links()

    draft_items_old = [
        {"qty": 2, "name": "Coupling A", "part_number": "CP-1", "unit_price": 25.0, "description": "5mm",
         "link": "https://example.com/old-coupling-a"},
        {"qty": 2, "name": "Coupling B", "part_number": "CP-2", "unit_price": 35.0, "description": "8mm"},
        {"qty": 1, "name": "Coupling C", "part_number": "CP-3", "unit_price": 30.0, "description": "10mm"},
    ]
    draft_items_new = [
        {"qty": 2, "name": "Coupling A", "part_number": "CP-1", "unit_price": 25.0, "description": "5mm",
         "link": "https://example.com/new-coupling-a"},
        {"qty": 2, "name": "Coupling B", "part_number": "CP-2", "unit_price": 35.0, "description": "8mm"},
        {"qty": 1, "name": "Coupling C", "part_number": "CP-3", "unit_price": 30.0, "description": "10mm"},
    ]
    draft_items_req = [
        {"qty": 2, "name": "Coupling A", "part_number": "CP-1", "unit_price": 25.0, "description": "5mm",
         "link": "https://example.com/requester-coupling-a"},
        {"qty": 2, "name": "Coupling B", "part_number": "CP-2", "unit_price": 35.0, "description": "8mm"},
        {"qty": 1, "name": "Coupling C", "part_number": "CP-3", "unit_price": 30.0, "description": "10mm"},
    ]

    bytes_map = {
        "F_OLD": bom.build_bom_workbook(parsed, draft_items_old),
        "F_NEW": bom.build_bom_workbook(parsed, draft_items_new),
        "F_REQ": bom.build_bom_workbook(parsed, draft_items_req),
    }

    thread_msgs = [
        {"user": "B_BOT", "ts": "1.1", "files": [{"id": "F_OLD", "name": "DRAFT_HIRST_LAB_BOM_1.xlsx"}]},
        {"user": "B_BOT", "ts": "1.2", "files": [{"id": "F_NEW", "name": "DRAFT_HIRST_LAB_BOM_2.xlsx"}]},
        {"user": "U_REQ", "ts": "1.3", "files": [{"id": "F_REQ", "name": "DRAFT_HIRST_LAB_BOM_3.xlsx"}]},
    ]
    card_payload = {
        "parsed": parsed,
        "requester": "Alex",
        "user_id": "U_REQ",
        "items": card_items,
        "shipping": 0.0,
        "thread_ts": "100.00",
    }
    client = _setup_fake_client(thread_msgs, card_payload)
    say = MagicMock()

    monkeypatch.setattr(slack_io, "download_file", lambda f: bytes_map[f["id"]])
    monkeypatch.setattr(slack_io, "resolve_requester", lambda cl, uid: "Alex" if uid == "U_REQ" else "Dylan")

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
        items=card_items,
        approver="U_CHARLIE",
    )

    expected_fname = f"HIRST_LAB_BOM_Shaft-Couplings_{datetime.date.today():%m.%d.%Y}.xlsx"
    saved_bom_path = os.path.join(temp_boms_dir, expected_fname)
    assert os.path.exists(saved_bom_path)

    wb = openpyxl.load_workbook(saved_bom_path)
    ws = wb.active
    assert ws["D6"].hyperlink is not None
    assert ws["D6"].hyperlink.target == "https://example.com/new-coupling-a"


def test_missing_draft_still_approves_and_asks_for_replace_bom(temp_workbook, temp_boms_dir, sync_queue, monkeypatch):
    """No draft in thread -> log row written, archived BOM has no link hyperlinks, card has off_template_bom, thread message asks for Replace BOM."""
    parsed = _valid_request(150.0)
    card_items = _card_items_without_links()

    card_payload = {
        "parsed": parsed,
        "requester": "Alex",
        "user_id": "U_REQ",
        "items": card_items,
        "shipping": 0.0,
        "thread_ts": "100.00",
    }
    client = _setup_fake_client([], card_payload)
    say = MagicMock()

    monkeypatch.setattr(slack_io, "resolve_requester", lambda cl, uid: "Alex" if uid == "U_REQ" else "Dylan")

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
        items=card_items,
        approver="U_CHARLIE",
    )

    # 1. Log row written
    with zipfile.ZipFile(temp_workbook) as zf:
        sheet_xml = zf.read(config.SHEET_XML).decode("utf-8")
    row_num = log_writer.find_first_empty_row(sheet_xml) - 1
    assert row_num == 17

    # 2. Archived BOM has no hyperlink in any Link cell
    expected_fname = f"HIRST_LAB_BOM_Shaft-Couplings_{datetime.date.today():%m.%d.%Y}.xlsx"
    saved_bom_path = os.path.join(temp_boms_dir, expected_fname)
    assert os.path.exists(saved_bom_path)
    wb = openpyxl.load_workbook(saved_bom_path)
    ws = wb.active
    assert ws["D6"].hyperlink is None
    assert ws["D7"].hyperlink is None
    assert ws["D8"].hyperlink is None

    # 3. Card metadata payload has off_template_bom is True
    assert client.chat_update.called
    update_meta = client.chat_update.call_args[1]["metadata"]["event_payload"]
    assert update_meta.get("off_template_bom") is True

    # 4. Thread message contains Replace BOM and couldn't recover the item links
    say_texts = " ".join(call.kwargs.get("text", "") for call in say.call_args_list)
    assert "Replace BOM" in say_texts
    assert "couldn't recover the item links" in say_texts


def test_mismatched_draft_is_refused(temp_workbook, temp_boms_dir, sync_queue, monkeypatch):
    """Draft row quantity differs from card -> same outcome as missing draft."""
    parsed = _valid_request(150.0)
    card_items = _card_items_without_links()

    # Draft with qty 5 instead of 2 for item 2
    draft_items = [
        {"qty": 2, "name": "Coupling A", "part_number": "CP-1", "unit_price": 25.0, "description": "5mm",
         "link": "https://example.com/coupling-a"},
        {"qty": 5, "name": "Coupling B", "part_number": "CP-2", "unit_price": 35.0, "description": "8mm"},
        {"qty": 1, "name": "Coupling C", "part_number": "CP-3", "unit_price": 30.0, "description": "10mm"},
    ]
    draft_bytes = bom.build_bom_workbook(parsed, draft_items)

    draft_file = {"id": "F_DRAFT", "name": "DRAFT_HIRST_LAB_BOM_Shaft-Couplings_11.02.2026.xlsx"}
    thread_msgs = [
        {"user": "B_BOT", "ts": "101.00", "files": [draft_file]},
    ]
    card_payload = {
        "parsed": parsed,
        "requester": "Alex",
        "user_id": "U_REQ",
        "items": card_items,
        "shipping": 0.0,
        "thread_ts": "100.00",
    }
    client = _setup_fake_client(thread_msgs, card_payload)
    say = MagicMock()

    monkeypatch.setattr(slack_io, "download_file", lambda f: draft_bytes)
    monkeypatch.setattr(slack_io, "resolve_requester", lambda cl, uid: "Alex" if uid == "U_REQ" else "Dylan")
    draft_spy = MagicMock(side_effect=slack_io.newest_bot_draft_bom)
    monkeypatch.setattr(slack_io, "newest_bot_draft_bom", draft_spy)

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
        items=card_items,
        approver="U_CHARLIE",
    )

    with zipfile.ZipFile(temp_workbook) as zf:
        sheet_xml = zf.read(config.SHEET_XML).decode("utf-8")
    row_num = log_writer.find_first_empty_row(sheet_xml) - 1
    assert row_num == 17

    expected_fname = f"HIRST_LAB_BOM_Shaft-Couplings_{datetime.date.today():%m.%d.%Y}.xlsx"
    saved_bom_path = os.path.join(temp_boms_dir, expected_fname)
    assert os.path.exists(saved_bom_path)
    wb = openpyxl.load_workbook(saved_bom_path)
    ws = wb.active
    assert ws["D6"].hyperlink is None

    assert client.chat_update.called
    update_meta = client.chat_update.call_args[1]["metadata"]["event_payload"]
    assert update_meta.get("off_template_bom") is True

    say_texts = " ".join(call.kwargs.get("text", "") for call in say.call_args_list)
    assert "Replace BOM" in say_texts
    assert "couldn't recover the item links" in say_texts


def test_items_with_links_skip_the_lookup(temp_workbook, temp_boms_dir, sync_queue, monkeypatch):
    """Card items that carry link keys skip draft lookup and keep their own links."""
    parsed = _valid_request(150.0)
    card_items = [
        {"qty": 2, "name": "Coupling A", "part_number": "CP-1", "unit_price": 25.0, "description": "5mm",
         "link": "https://card.example.com/coupling-a"},
        {"qty": 2, "name": "Coupling B", "part_number": "CP-2", "unit_price": 35.0, "description": "8mm",
         "link": "https://card.example.com/coupling-b"},
        {"qty": 1, "name": "Coupling C", "part_number": "CP-3", "unit_price": 30.0, "description": "10mm",
         "link": "https://card.example.com/coupling-c"},
    ]

    draft_items = [
        {"qty": 2, "name": "Coupling A", "part_number": "CP-1", "unit_price": 25.0, "description": "5mm",
         "link": "https://draft.example.com/coupling-a"},
        {"qty": 2, "name": "Coupling B", "part_number": "CP-2", "unit_price": 35.0, "description": "8mm",
         "link": "https://draft.example.com/coupling-b"},
        {"qty": 1, "name": "Coupling C", "part_number": "CP-3", "unit_price": 30.0, "description": "10mm",
         "link": "https://draft.example.com/coupling-c"},
    ]
    draft_bytes = bom.build_bom_workbook(parsed, draft_items)

    draft_file = {"id": "F_DRAFT", "name": "DRAFT_HIRST_LAB_BOM_Shaft-Couplings_11.02.2026.xlsx"}
    thread_msgs = [
        {"user": "B_BOT", "ts": "101.00", "files": [draft_file]},
    ]
    card_payload = {
        "parsed": parsed,
        "requester": "Alex",
        "user_id": "U_REQ",
        "items": card_items,
        "shipping": 0.0,
        "thread_ts": "100.00",
    }
    client = _setup_fake_client(thread_msgs, card_payload)
    say = MagicMock()

    monkeypatch.setattr(slack_io, "download_file", lambda f: draft_bytes)
    monkeypatch.setattr(slack_io, "resolve_requester", lambda cl, uid: "Alex" if uid == "U_REQ" else "Dylan")
    draft_spy = MagicMock(side_effect=slack_io.newest_bot_draft_bom)
    monkeypatch.setattr(slack_io, "newest_bot_draft_bom", draft_spy)

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
        items=card_items,
        approver="U_CHARLIE",
    )

    expected_fname = f"HIRST_LAB_BOM_Shaft-Couplings_{datetime.date.today():%m.%d.%Y}.xlsx"
    saved_bom_path = os.path.join(temp_boms_dir, expected_fname)
    assert os.path.exists(saved_bom_path)

    wb = openpyxl.load_workbook(saved_bom_path)
    ws = wb.active
    assert ws["D6"].hyperlink is not None
    assert ws["D6"].hyperlink.target == "https://card.example.com/coupling-a"
    assert ws["D7"].hyperlink is not None
    assert ws["D7"].hyperlink.target == "https://card.example.com/coupling-b"
    assert ws["D8"].hyperlink is not None
    assert ws["D8"].hyperlink.target == "https://card.example.com/coupling-c"

    # Card does NOT have off_template_bom
    update_meta = client.chat_update.call_args[1]["metadata"]["event_payload"]
    assert update_meta.get("off_template_bom") is None or update_meta.get("off_template_bom") is False
    draft_spy.assert_not_called()


def test_merge_links_pure_cases():
    """Unit tests for bom.merge_links matching, stripping, and refusal cases."""
    card = [{"name": " Part A ", "qty": "2", "unit_price": 10.0}]
    draft = [{"item_name": "Part A", "quantity": 2, "link": "https://example.com/a", "no_link_reason": ""}]
    res = bom.merge_links(card, draft)
    assert res is not None
    assert len(res) == 1
    assert res[0]["link"] == "https://example.com/a"
    assert res[0]["no_link_reason"] == ""
    assert res[0] is not card[0]  # must be a copy

    # Length mismatch
    assert bom.merge_links(card, []) is None

    # Name mismatch
    diff_name = [{"name": "Part B", "qty": 2}]
    assert bom.merge_links(card, diff_name) is None

    # Quantity mismatch
    diff_qty = [{"name": "Part A", "qty": 3}]
    assert bom.merge_links(card, diff_qty) is None

    # Invalid quantity
    bad_qty = [{"name": "Part A", "qty": "not-a-number"}]
    assert bom.merge_links(card, bad_qty) is None


def test_newest_bot_draft_bom_unit():
    """Unit tests for slack_io.newest_bot_draft_bom filtering and ordering."""
    client = MagicMock()
    client.auth_test.return_value = {"ok": True, "user_id": "B_BOT"}

    # No files or no bot files
    client.conversations_replies.return_value = {"messages": [
        {"user": "U_REQ", "ts": "1.0", "files": [{"name": "DRAFT_HIRST_LAB_BOM_1.xlsx"}]},
        {"user": "B_BOT", "ts": "2.0", "files": [{"name": "quote.pdf"}]},
    ]}
    assert slack_io.newest_bot_draft_bom(client, "C_TEST", "1.0") is None

    # Picks newest by timestamp among bot files matching prefix
    client.conversations_replies.return_value = {"messages": [
        {"user": "B_BOT", "ts": "1.0", "files": [{"name": "DRAFT_HIRST_LAB_BOM_old.xlsx", "id": "F1"}]},
        {"bot_id": "BOT123", "ts": "3.0", "files": [{"name": "DRAFT_HIRST_LAB_BOM_new.xlsx", "id": "F2"}]},
        {"user": "U_REQ", "ts": "4.0", "files": [{"name": "DRAFT_HIRST_LAB_BOM_user.xlsx", "id": "F3"}]},
    ]}
    newest = slack_io.newest_bot_draft_bom(client, "C_TEST", "1.0")
    assert newest is not None
    assert newest["id"] == "F2"

    # API exception handled gracefully
    client.conversations_replies.side_effect = RuntimeError("Slack down")
    assert slack_io.newest_bot_draft_bom(client, "C_TEST", "1.0") is None

