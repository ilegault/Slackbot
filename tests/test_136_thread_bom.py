"""Tests for Ticket 136: a thread's .xlsx is read at approval; an Off-template BOM is flagged, never blocking.

Acceptance criteria:
- [ ] test_clean_template_in_thread_is_read
- [ ] test_off_template_bom_still_approves_and_asks_for_a_replacement
- [ ] test_total_mismatch_is_off_template
"""
import datetime
import json
import os
from unittest.mock import MagicMock

from src import bom, config, epif_filler, lifecycle, log_writer, slack_io
from tests.test_103_thread_files_at_approval import (  # noqa: F401  (fixtures are reused)
    EPIF_TEMPLATE,
    _row,
    clean_roster,
    dirs,
    sync_queue,
    temp_workbook,
)

BOM_FIXTURE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "BOM_TEMPLATE_FILLED_EXAMPLE.xlsx")


def _epif_bytes(total: float) -> bytes:
    with open(EPIF_TEMPLATE, "rb") as f:
        template = f.read()
    return epif_filler.fill_epif(template, {
        "item_description": "Copper gaskets", "purpose": "Flange seals", "total_price": total,
        "vendor": "Duniway", "vendor_contact_name": "Sales", "vendor_contact_email": "sales@duniway.com",
        "date_of_purchase": datetime.date(2026, 10, 6), "project_id": "PG000025831", "fund": "133",
        "category": "Research/Lab Supplies (3105)", "delivery_room": "ERB 212", "payment_method": "P-card",
        "link": "https://duniway.com", "name_of_system": "", "asset_id": "",
    })


def _approve(monkeypatch, total: float, bom_name: str, bom_bytes: bytes):
    """Approve a thread holding a Filled-EPIF PDF and one BOM file; returns (client, say)."""
    files = {"F_EPIF": _epif_bytes(total), "F_BOM": bom_bytes}
    client = MagicMock()
    client.auth_test.return_value = {"ok": True, "user_id": "B_BOT"}
    client.conversations_open.return_value = {"channel": {"id": "D_BUYER"}}
    client.chat_postMessage.return_value = {"ok": True, "ts": "500.0"}
    client.files_info.side_effect = lambda file: {"file": {"id": file, "name": "x"}}
    client.conversations_replies.return_value = {"messages": [
        {"user": "U_REQ", "ts": "100.0", "files": [{"id": "F_EPIF", "name": "Duniway_EPIF.pdf"}]},
        {"user": "U_REQ", "ts": "101.0", "files": [{"id": "F_BOM", "name": bom_name}]},
    ]}
    monkeypatch.setattr(slack_io, "download", lambda f: files[f["id"]])
    monkeypatch.setattr(slack_io, "download_file", lambda f: files[f["id"]])
    monkeypatch.setattr(slack_io, "resolve_requester", lambda cl, uid: "Alex" if uid == "U_REQ" else "Dylan")
    monkeypatch.setattr(slack_io, "find_card_in_thread", lambda *a, **kw: (None, None, [], None))
    say = MagicMock()
    lifecycle.handle_epif_processing(
        client=client, say=say, channel="C_PURCHASING", thread_ts="100.0", approver="U_CHARLIE",
        event_ts="102.0", assignee_id="U_BUYER", assignee_name="Dylan",
    )
    return client, say


def _thread_texts(say) -> str:
    return "\n".join(c.kwargs.get("text", "") for c in say.call_args_list)


def _card_payload(client) -> dict:
    cards = [c.kwargs for c in client.chat_postMessage.call_args_list
             if c.kwargs.get("metadata") and c.kwargs["metadata"].get("event_type") == "purchase_request"]
    return cards[0]["metadata"]["event_payload"]


def _all_blocks_text(client) -> str:
    return json.dumps([c.kwargs.get("blocks") for c in client.chat_postMessage.call_args_list], ensure_ascii=False)


def test_clean_template_in_thread_is_read(temp_workbook, dirs, sync_queue, monkeypatch):  # noqa: F811
    with open(BOM_FIXTURE, "rb") as f:
        fixture_bytes = f.read()
    expected_items, problems = bom.read_bom_template(fixture_bytes)
    assert problems == [] and len(expected_items) == 4

    client, say = _approve(monkeypatch, 858.50, "order.xlsx", fixture_bytes)

    assert len(_card_payload(client)["items"]) == 4
    (archived,) = os.listdir(dirs["BOMS_DIR"])
    assert archived.startswith("HIRST_LAB_BOM_") and archived.endswith(".xlsx")
    with open(os.path.join(dirs["BOMS_DIR"], archived), "rb") as f:
        archived_items, archived_problems = bom.read_bom_template(f.read())
    assert archived_problems == []
    assert archived_items == expected_items
    assert "isn't ready for purchasing" not in _thread_texts(say)
    assert "BOM not in the lab template" not in _all_blocks_text(client)
    xml, row = _row(temp_workbook)
    assert log_writer.get_cell_value(xml, f"{config.COLUMN_NOTES}{row}") == f"BOM: {archived} (4 items)"


def test_off_template_bom_still_approves_and_asks_for_a_replacement(temp_workbook, dirs, sync_queue, monkeypatch):  # noqa: F811
    client, say = _approve(monkeypatch, 858.50, "order.csv", b"item,qty,price\nflask,2,10\n")

    # The approval went ahead: the row is written and the file is archived as given.
    xml, row = _row(temp_workbook)
    assert row == 17
    (archived,) = os.listdir(dirs["BOMS_DIR"])
    assert archived.endswith(".csv")
    with open(os.path.join(dirs["BOMS_DIR"], archived), "rb") as f:
        assert f.read() == b"item,qty,price\nflask,2,10\n"

    said = _thread_texts(say)
    assert "<@U_REQ>" in said and "Replace BOM" in said and "isn't ready for purchasing" in said
    payload = _card_payload(client)
    assert payload["off_template_bom"] is True
    assert "lab BOM template" in payload["off_template_problem"]
    assert "BOM not in the lab template" in _all_blocks_text(client)


def test_total_mismatch_is_off_template(temp_workbook, dirs, sync_queue, monkeypatch):  # noqa: F811
    with open(BOM_FIXTURE, "rb") as f:
        fixture_bytes = f.read()
    client, say = _approve(monkeypatch, 900.00, "order.xlsx", fixture_bytes)

    said = _thread_texts(say)
    assert "$858.50" in said and "$900.00" in said and "Replace BOM" in said
    assert _card_payload(client)["off_template_bom"] is True
    (archived,) = os.listdir(dirs["BOMS_DIR"])
    with open(os.path.join(dirs["BOMS_DIR"], archived), "rb") as f:
        assert f.read() == fixture_bytes
    _xml, row = _row(temp_workbook)
    assert row == 17
    assert bom  # the reader and total check are the real ones
