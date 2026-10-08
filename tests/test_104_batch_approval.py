"""Tests for Ticket 104: Several EPIFs in a thread approve as a batch.

Acceptance criteria:
- [ ] New tests/test_104_batch_approval.py: a thread with EPIFs for vendors A and B from one uploader.
      Keyword approval writes two rows (vendors A and B) to the temp workbook and posts two approved
      cards, each showing its own vendor. Assert on the chat_postMessage calls carrying blocks.
- [ ] A thread with two EPIFs from the same uploader for vendor A (older total $10, newer total $20)
      writes one row with total 20.00.
- [ ] The same vendor from two different uploaders is not collapsed: two rows.
- [ ] Cancel on either card of a two-EPIF batch blanks both rows. Drive handle_cancel as
      tests/test_05_decline_cancel.py does, on the temp workbook.
- [ ] A single-EPIF thread still posts exactly one card, and finalize_purchase_request called without
      new_card still updates an existing thread card in place (the existing tests in
      tests/test_14_approve_payload.py and tests/test_40_bare_thread_approval.py pass unchanged).

May fake: the Slack client, downloads, epif_parser.parse_epif (return per-file dicts).
Must be real: the collapse, finalize_purchase_request, the workbook writes and the blanking on a temp copy.
"""
import datetime
import json
import os
import zipfile
from unittest.mock import MagicMock

import pytest

from src import (
    config,
    epif_parser,
    lifecycle,
    log_writer,
    queue_worker,
    roster,
    slack_io,
)

FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")
EPIF_TEMPLATE = os.path.join(FIXTURES, "EPIF_TEMPLATE_HIRST.pdf")


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
            "U_REQ2": "Taylor",
        },
        "vendors": [],
    }
    with open(roster_file, "w", encoding="utf-8") as f:
        json.dump(data, f)
    return roster_file


@pytest.fixture
def dirs(tmp_path, monkeypatch):
    out = {}
    for name in ("BOMS_DIR", "QUOTES_DIR", "EPIFS_DIR"):
        d = str(tmp_path / name)
        os.makedirs(d)
        monkeypatch.setattr(config, name, d)
        out[name] = d
    monkeypatch.setattr(config, "EPIF_TEMPLATE_PATH", EPIF_TEMPLATE)
    monkeypatch.setattr(config, "ADMIN_ALERT_CHANNEL", "C_ADMIN")
    return out


@pytest.fixture
def temp_workbook(tmp_path, monkeypatch):
    from tests.test_29_approval_archives_bom import create_test_workbook
    p = str(tmp_path / "Purchasing-Log.xlsx")
    create_test_workbook(p)
    monkeypatch.setattr(config, "WORKBOOK_PATH", p)
    return p


@pytest.fixture
def sync_queue(monkeypatch):
    def _sync(action_fn, channel="", thread_ts="", user_id="", task_type="append",
              description="", success_callback=None, failure_callback=None, client=None):
        try:
            res = action_fn()
        except Exception as exc:
            if failure_callback:
                failure_callback(exc)
            return
        if success_callback:
            success_callback(res)
    monkeypatch.setattr(queue_worker, "submit_write_task", _sync)


def _row(temp_workbook):
    with zipfile.ZipFile(temp_workbook) as zf:
        xml = zf.read(config.SHEET_XML).decode("utf-8")
    return xml, log_writer.find_first_empty_row(xml) - 1


def _make_parsed(vendor: str, total_price: float, item_desc: str = "Test Supplies"):
    return {
        "item_description": item_desc,
        "purpose": "Experiment setup",
        "total_price": total_price,
        "vendor": vendor,
        "vendor_contact_name": "Sales",
        "vendor_contact_email": f"sales@{vendor.lower().replace(' ', '')}.com",
        "date_of_purchase": datetime.date(2026, 9, 22),
        "project_id": "PG000025831",
        "fund": "133",
        "category": "Research/Lab Supplies (3105)",
        "delivery_room": "ERB 212",
        "payment_method": "P-card",
        "link": f"https://{vendor.lower().replace(' ', '')}.com",
        "name_of_system": "",
        "asset_id": "",
    }


# ---------------------------------------------------------------------------
# Unit tests for epif_parser.collapse_epifs
# ---------------------------------------------------------------------------

def test_collapse_epifs_pure_logic():
    """Unit tests verifying epif_parser.collapse_epifs behavior."""
    # Empty list
    assert epif_parser.collapse_epifs([]) == []

    # Single EPIF
    ep1 = {"user": "U1", "ts": "100.0", "parsed": {"vendor": "Vendor A"}}
    assert epif_parser.collapse_epifs([ep1]) == [ep1]

    # Same uploader, same vendor -> keeps newest by ts
    ep2_old = {"user": "U1", "ts": "100.0", "parsed": {"vendor": "Vendor A", "total_price": 10.0}}
    ep2_new = {"user": "U1", "ts": "200.0", "parsed": {"vendor": "Vendor A", "total_price": 20.0}}
    res = epif_parser.collapse_epifs([ep2_old, ep2_new])
    assert len(res) == 1
    assert res[0]["ts"] == "200.0"
    assert res[0]["parsed"]["total_price"] == 20.0

    # Same uploader, same vendor with whitespace/case differences -> collapses to newest
    ep3_a = {"user": "U1", "ts": "100.0", "parsed": {"vendor": "  Vendor A  "}}
    ep3_b = {"user": "U1", "ts": "150.0", "parsed": {"vendor": "vendor a"}}
    res3 = epif_parser.collapse_epifs([ep3_a, ep3_b])
    assert len(res3) == 1
    assert res3[0]["ts"] == "150.0"

    # Same uploader, different vendors -> keeps both, sorted oldest first
    ep_va = {"user": "U1", "ts": "300.0", "parsed": {"vendor": "Vendor A"}}
    ep_vb = {"user": "U1", "ts": "100.0", "parsed": {"vendor": "Vendor B"}}
    res4 = epif_parser.collapse_epifs([ep_va, ep_vb])
    assert len(res4) == 2
    assert [x["parsed"]["vendor"] for x in res4] == ["Vendor B", "Vendor A"]

    # Different uploaders, same vendor -> keeps both, sorted oldest first
    ep_u1 = {"user": "U1", "ts": "200.0", "parsed": {"vendor": "Vendor A"}}
    ep_u2 = {"user": "U2", "ts": "100.0", "parsed": {"vendor": "Vendor A"}}
    res5 = epif_parser.collapse_epifs([ep_u1, ep_u2])
    assert len(res5) == 2
    assert [x["user"] for x in res5] == ["U2", "U1"]


# ---------------------------------------------------------------------------
# Criterion 1: Two vendors from one uploader writes two rows & two approved cards
# ---------------------------------------------------------------------------

def test_batch_approval_two_vendors_one_uploader(temp_workbook, dirs, sync_queue, monkeypatch):
    """A thread with EPIFs for vendors A and B from one uploader.

    Keyword approval writes two rows (vendors A and B) to the temp workbook and posts
    two approved cards, each showing its own vendor. Assert on the chat_postMessage calls carrying blocks.
    """
    file_a = {"id": "F_A", "name": "VendorA_EPIF.pdf"}
    file_b = {"id": "F_B", "name": "VendorB_EPIF.pdf"}
    parsed_a = _make_parsed("Vendor A", 50.0, item_desc="Optics Parts")
    parsed_b = _make_parsed("Vendor B", 75.0, item_desc="Vacuum Flanges")

    # Mock client and thread replies
    client = MagicMock()
    client.auth_test.return_value = {"ok": True, "user_id": "B_BOT"}
    client.conversations_replies.return_value = {
        "messages": [
            {"user": "U_REQ", "ts": "100.0", "files": [file_a]},
            {"user": "U_REQ", "ts": "101.0", "files": [file_b]},
        ]
    }

    # Fake downloads and parse_epif per ticket allowance
    pdf_bytes_map = {"F_A": b"%PDF-A", "F_B": b"%PDF-B"}
    monkeypatch.setattr(slack_io, "download", lambda f: pdf_bytes_map[f["id"]])
    monkeypatch.setattr(epif_parser, "read_fields", lambda b: {"Amount of Purchase": "1", "Vendor": "V"})
    monkeypatch.setattr(
        epif_parser,
        "parse_epif",
        lambda b: parsed_a if b == b"%PDF-A" else parsed_b,
    )
    monkeypatch.setattr(slack_io, "find_card_in_thread", lambda *a, **kw: (None, None, [], None))

    post_message_calls = []

    def fake_postMessage(**kwargs):
        post_message_calls.append(kwargs)
        return {"ok": True, "ts": f"post_ts_{len(post_message_calls)}"}

    client.chat_postMessage.side_effect = fake_postMessage
    say = MagicMock()

    lifecycle.handle_epif_processing(
        client=client,
        say=say,
        channel="C_PURCHASING",
        thread_ts="100.0",
        approver="U_CHARLIE",
        event_ts="102.0",
    )

    # 1. Workbook: two rows written (rows 17 and 18)
    xml, last_row = _row(temp_workbook)
    assert last_row == 18, f"Expected 2 rows written, got last row {last_row}"

    vendor_col = config.FIELD_TO_COLUMN["Vendor"]
    row17_vendor = log_writer.get_cell_value(xml, f"{vendor_col}17")
    row18_vendor = log_writer.get_cell_value(xml, f"{vendor_col}18")
    assert row17_vendor == "Vendor A"
    assert row18_vendor == "Vendor B"

    # 2. Both EPIFs archived
    epif_files = os.listdir(dirs["EPIFS_DIR"])
    assert any("Vendor A" in f or "Vendor_A" in f or "VendorA" in f for f in epif_files)
    assert any("Vendor B" in f or "Vendor_B" in f or "VendorB" in f for f in epif_files)

    # 3. Assert on the chat_postMessage calls carrying blocks
    card_posts = [call for call in post_message_calls if "blocks" in call]
    assert len(card_posts) == 2, f"Expected exactly 2 card posts with blocks, got {len(card_posts)}"

    # Card 1 shows Vendor A, Card 2 shows Vendor B
    card1_str = json.dumps(card_posts[0]["blocks"])
    card2_str = json.dumps(card_posts[1]["blocks"])
    assert "Vendor A" in card1_str, f"Card 1 blocks should mention Vendor A: {card1_str}"
    assert "Vendor B" in card2_str, f"Card 2 blocks should mention Vendor B: {card2_str}"


# ---------------------------------------------------------------------------
# Criterion 2: Same uploader, same vendor collapses to newer
# ---------------------------------------------------------------------------

def test_same_vendor_same_uploader_collapses_to_newer(temp_workbook, dirs, sync_queue, monkeypatch):
    """A thread with two EPIFs from the same uploader for vendor A (older total $10, newer total $20)

    writes ONE row with total 20.00.
    """
    file_old = {"id": "F_OLD", "name": "VendorA_draft1.pdf"}
    file_new = {"id": "F_NEW", "name": "VendorA_draft2.pdf"}
    parsed_old = _make_parsed("Vendor A", 10.0, item_desc="Draft 1")
    parsed_new = _make_parsed("Vendor A", 20.0, item_desc="Draft 2")

    client = MagicMock()
    client.auth_test.return_value = {"ok": True, "user_id": "B_BOT"}
    client.conversations_replies.return_value = {
        "messages": [
            {"user": "U_REQ", "ts": "100.0", "files": [file_old]},
            {"user": "U_REQ", "ts": "101.0", "files": [file_new]},
        ]
    }

    pdf_bytes_map = {"F_OLD": b"%PDF-OLD", "F_NEW": b"%PDF-NEW"}
    monkeypatch.setattr(slack_io, "download", lambda f: pdf_bytes_map[f["id"]])
    monkeypatch.setattr(epif_parser, "read_fields", lambda b: {"Amount of Purchase": "1", "Vendor": "V"})
    monkeypatch.setattr(
        epif_parser,
        "parse_epif",
        lambda b: parsed_old if b == b"%PDF-OLD" else parsed_new,
    )
    monkeypatch.setattr(slack_io, "find_card_in_thread", lambda *a, **kw: (None, None, [], None))

    post_message_calls = []
    client.chat_postMessage.side_effect = lambda **kw: post_message_calls.append(kw) or {"ok": True, "ts": "105.0"}
    say = MagicMock()

    lifecycle.handle_epif_processing(
        client=client,
        say=say,
        channel="C_PURCHASING",
        thread_ts="100.0",
        approver="U_CHARLIE",
        event_ts="102.0",
    )

    # Exactly ONE row written
    xml, last_row = _row(temp_workbook)
    assert last_row == 17, f"Expected exactly 1 row written, got last row {last_row}"

    # Written row has total 20.00
    row17_price = log_writer.get_cell_value(xml, f"{config.COLUMN_TOTAL_PRICE}17")
    assert float(row17_price) == 20.0, f"Expected total 20.00, got {row17_price}"

    # Exactly one card posted
    card_posts = [c for c in post_message_calls if "blocks" in c]
    assert len(card_posts) == 1, f"Expected 1 card posted, got {len(card_posts)}"


# ---------------------------------------------------------------------------
# Criterion 3: Same vendor from two different uploaders is NOT collapsed
# ---------------------------------------------------------------------------

def test_different_uploaders_same_vendor_not_collapsed(temp_workbook, dirs, sync_queue, monkeypatch):
    """The same vendor from two different uploaders is not collapsed: two rows."""
    file_alex = {"id": "F_ALEX", "name": "VendorA_Alex.pdf"}
    file_taylor = {"id": "F_TAYLOR", "name": "VendorA_Taylor.pdf"}
    parsed_alex = _make_parsed("Vendor A", 10.0, item_desc="Alex order")
    parsed_taylor = _make_parsed("Vendor A", 20.0, item_desc="Taylor order")

    client = MagicMock()
    client.auth_test.return_value = {"ok": True, "user_id": "B_BOT"}
    client.conversations_replies.return_value = {
        "messages": [
            {"user": "U_REQ", "ts": "100.0", "files": [file_alex]},
            {"user": "U_REQ2", "ts": "101.0", "files": [file_taylor]},
        ]
    }

    pdf_bytes_map = {"F_ALEX": b"%PDF-ALEX", "F_TAYLOR": b"%PDF-TAYLOR"}
    monkeypatch.setattr(slack_io, "download", lambda f: pdf_bytes_map[f["id"]])
    monkeypatch.setattr(epif_parser, "read_fields", lambda b: {"Amount of Purchase": "1", "Vendor": "V"})
    monkeypatch.setattr(
        epif_parser,
        "parse_epif",
        lambda b: parsed_alex if b == b"%PDF-ALEX" else parsed_taylor,
    )
    monkeypatch.setattr(slack_io, "find_card_in_thread", lambda *a, **kw: (None, None, [], None))

    post_message_calls = []
    client.chat_postMessage.side_effect = lambda **kw: post_message_calls.append(kw) or {"ok": True, "ts": f"ts_{len(post_message_calls)}"}
    say = MagicMock()

    lifecycle.handle_epif_processing(
        client=client,
        say=say,
        channel="C_PURCHASING",
        thread_ts="100.0",
        approver="U_CHARLIE",
        event_ts="102.0",
    )

    # TWO rows written
    xml, last_row = _row(temp_workbook)
    assert last_row == 18, f"Expected 2 rows written, got last row {last_row}"

    row17_price = log_writer.get_cell_value(xml, f"{config.COLUMN_TOTAL_PRICE}17")
    row18_price = log_writer.get_cell_value(xml, f"{config.COLUMN_TOTAL_PRICE}18")
    assert float(row17_price) == 10.0
    assert float(row18_price) == 20.0

    card_posts = [c for c in post_message_calls if "blocks" in c]
    assert len(card_posts) == 2, f"Expected 2 cards posted, got {len(card_posts)}"


# ---------------------------------------------------------------------------
# Criterion 4: Cancel on either card of a two-EPIF batch blanks both rows
# ---------------------------------------------------------------------------

def test_cancel_on_either_card_blanks_both_rows(temp_workbook, dirs, sync_queue, monkeypatch):
    """Cancel on either card of a two-EPIF batch blanks both rows.

    Drive handle_cancel as tests/test_05_decline_cancel.py does, on the temp workbook.
    """
    file_a = {"id": "F_A", "name": "VendorA.pdf"}
    file_b = {"id": "F_B", "name": "VendorB.pdf"}
    parsed_a = _make_parsed("Vendor A", 50.0)
    parsed_b = _make_parsed("Vendor B", 75.0)

    thread_replies_messages = [
        {"user": "U_REQ", "ts": "100.0", "files": [file_a]},
        {"user": "U_REQ", "ts": "101.0", "files": [file_b]},
    ]

    client = MagicMock()
    client.auth_test.return_value = {"ok": True, "user_id": "B_BOT"}
    client.conversations_replies.side_effect = lambda **kw: {"messages": thread_replies_messages}

    pdf_bytes_map = {"F_A": b"%PDF-A", "F_B": b"%PDF-B"}
    monkeypatch.setattr(slack_io, "download", lambda f: pdf_bytes_map[f["id"]])
    monkeypatch.setattr(epif_parser, "read_fields", lambda b: {"Amount of Purchase": "1", "Vendor": "V"})
    monkeypatch.setattr(
        epif_parser,
        "parse_epif",
        lambda b: parsed_a if b == b"%PDF-A" else parsed_b,
    )
    monkeypatch.setattr(slack_io, "find_card_in_thread", lambda *a, **kw: (None, None, [], None))

    posted_cards = []

    def fake_postMessage(**kwargs):
        if "blocks" in kwargs:
            ts = f"card_ts_{len(posted_cards) + 1}"
            posted_cards.append((ts, kwargs))
            return {"ok": True, "ts": ts}
        return {"ok": True, "ts": "other_ts"}

    client.chat_postMessage.side_effect = fake_postMessage

    def fake_say(text="", thread_ts=None):
        thread_replies_messages.append({"text": text, "ts": f"say_{len(thread_replies_messages)}"})

    # 1. Drive keyword approval
    lifecycle.handle_epif_processing(
        client=client,
        say=fake_say,
        channel="C_PURCHASING",
        thread_ts="100.0",
        approver="U_CHARLIE",
        event_ts="102.0",
    )

    xml, last_row = _row(temp_workbook)
    assert last_row == 18
    assert len(posted_cards) == 2
    # Verify rows 17 and 18 have data before cancel
    assert log_writer.get_cell_value(xml, "B17") == "Alex"
    assert log_writer.get_cell_value(xml, "B18") == "Alex"

    # 2. Cancel on card 1: blanks both rows
    card1_ts, card1_kwargs = posted_cards[0]
    cancel_res = lifecycle.handle_cancel(
        client=client,
        say=fake_say,
        channel="C_PURCHASING",
        thread_ts="100.0",
        msg_ts=card1_ts,
        user_id="U_CHARLIE",
        req_data=card1_kwargs.get("metadata", {}).get("event_payload", {}),
        state="approved",
        history=[],
    )
    assert cancel_res is not False

    # Check both rows 17 and 18 are blanked
    xml_after, _ = _row(temp_workbook)
    for r in (17, 18):
        for col in "BCDEFGHIJKLMNOPQRSTUVWXY":
            val = log_writer.get_cell_value(xml_after, f"{col}{r}")
            assert val is None, f"Cell {col}{r} should be blank, got {val!r}"


# ---------------------------------------------------------------------------
# Criterion 5: Single-EPIF thread posts one card; finalize without new_card
# updates existing card
# ---------------------------------------------------------------------------

def test_single_epif_thread_posts_one_card(temp_workbook, dirs, sync_queue, monkeypatch):
    """A single-EPIF thread still posts exactly one card."""
    file_a = {"id": "F_A", "name": "VendorA.pdf"}
    parsed_a = _make_parsed("Vendor A", 50.0)

    client = MagicMock()
    client.auth_test.return_value = {"ok": True, "user_id": "B_BOT"}
    client.conversations_replies.return_value = {
        "messages": [
            {"user": "U_REQ", "ts": "100.0", "files": [file_a]},
        ]
    }

    monkeypatch.setattr(slack_io, "download", lambda f: b"%PDF-A")
    monkeypatch.setattr(epif_parser, "read_fields", lambda b: {"Amount of Purchase": "1", "Vendor": "V"})
    monkeypatch.setattr(epif_parser, "parse_epif", lambda b: parsed_a)
    monkeypatch.setattr(slack_io, "find_card_in_thread", lambda *a, **kw: (None, None, [], None))

    post_message_calls = []
    client.chat_postMessage.side_effect = lambda **kw: post_message_calls.append(kw) or {"ok": True, "ts": "105.0"}
    say = MagicMock()

    lifecycle.handle_epif_processing(
        client=client,
        say=say,
        channel="C_PURCHASING",
        thread_ts="100.0",
        approver="U_CHARLIE",
        event_ts="102.0",
    )

    card_posts = [c for c in post_message_calls if "blocks" in c]
    assert len(card_posts) == 1, f"Expected exactly 1 card posted, got {len(card_posts)}"


def test_finalize_without_new_card_updates_existing_card_in_place(temp_workbook, dirs, sync_queue, monkeypatch):
    """finalize_purchase_request called without new_card updates an existing thread card in place."""
    client = MagicMock()
    say = MagicMock()

    existing_req = {"item_description": "Existing Card Req", "state": "posted"}
    # Card exists at ts="555.0"
    monkeypatch.setattr(slack_io, "find_card_in_thread", lambda *a, **kw: (existing_req, "555.0", [], "posted"))

    parsed = _make_parsed("Vendor A", 50.0)

    lifecycle.finalize_purchase_request(
        client=client,
        say=say,
        channel="C_PURCHASING",
        thread_ts="100.0",
        event_ts="101.0",
        parsed=parsed,
        requester="Alex",
        notify_target="U_REQ",
        # new_card omitted (defaults to False)
    )

    # chat_update must be called for the existing card
    client.chat_update.assert_called_once()
    update_kwargs = client.chat_update.call_args[1]
    assert update_kwargs["ts"] == "555.0"

    # chat_postMessage must NOT be called for a new card (no blocks post)
    card_posts = [call for call in client.chat_postMessage.call_args_list if "blocks" in call[1]]
    assert len(card_posts) == 0


def test_finalize_with_new_card_posts_fresh_card_ignoring_found(temp_workbook, dirs, sync_queue, monkeypatch):
    """finalize_purchase_request called with new_card=True ignores found card and posts fresh card."""
    client = MagicMock()
    say = MagicMock()

    existing_req = {"item_description": "Existing Card Req", "state": "posted"}
    # A card exists in the thread
    monkeypatch.setattr(slack_io, "find_card_in_thread", lambda *a, **kw: (existing_req, "555.0", [], "posted"))

    parsed = _make_parsed("Vendor A", 50.0)

    lifecycle.finalize_purchase_request(
        client=client,
        say=say,
        channel="C_PURCHASING",
        thread_ts="100.0",
        event_ts="101.0",
        parsed=parsed,
        requester="Alex",
        notify_target="U_REQ",
        new_card=True,
    )

    # chat_update must NOT be called
    client.chat_update.assert_not_called()

    # chat_postMessage must be called to post a fresh card
    card_posts = [call for call in client.chat_postMessage.call_args_list if "blocks" in call[1]]
    assert len(card_posts) == 1
    post_kwargs = card_posts[0][1]
    assert post_kwargs["text"] == "🛒 Purchase Request (Approved)"
