"""Tests for Ticket 81: Quotes field on /new-purchase.

WHY THIS EXISTS:
----------------
Ticket 81 / ADR 0012 Decisions 1, 2, 5; ADR 0006 Decision 5; ADR 0001:
Covers attaching vendor quote PDFs on interview Screen 2 of /new-purchase:
1. Screen 2 renders an optional Quotes file input (PDF only, up to 10 files) when not editing.
2. Edit mode (meta['is_edit'] = True) does NOT show the Quotes file input (handled by Ticket 86).
3. Two quotes submitted in Screen 2 are stored in card metadata event_payload['attachments'],
   never appear in any button value, show 'Quotes: 2' on the card, and re-upload both files to thread.
4. Attached quotes survive Screen 3 (Fabrication category requiring asset details).
5. A failed download for one file is loud: posts warning in thread, sends DM to requester,
   and does not abort card posting or other attachments.
6. Submitting without files leaves metadata without 'attachments' key and triggers no file operations.
7. Pure extraction helper extract_modal_files handles missing keys and truncates long filenames.
"""
import json
from unittest.mock import MagicMock

import pytest

from src import app, blocks, config, roster, slack_io, text_rules


@pytest.fixture(autouse=True)
def isolate_roster(tmp_path, monkeypatch):
    """Ensure tests run against a clean isolated roster.json copy."""
    test_roster_file = str(tmp_path / "roster.json")
    monkeypatch.setattr(roster, "ROSTER_PATH", test_roster_file)
    roster.load_roster()
    return test_roster_file


def _sample_stage1_meta(
    vendor_choice="DigiKey",
    vendor_custom="",
    route="workday",
    resolved_name="Isaac",
    user_id="U_ISAAC",
    is_pending_name=False,
    is_edit=False,
):
    return {
        "vendor_choice": vendor_choice,
        "vendor_custom": vendor_custom,
        "route": route,
        "resolved_name": resolved_name,
        "user_id": user_id,
        "is_pending_name": is_pending_name,
        "is_edit": is_edit,
    }


def _make_stage2_view_submission(
    meta: dict,
    total_price: str = "100.00",
    item_description: str = "Electronic components",
    purpose: str = "Sensor instrumentation",
    link: str = "https://example.com/parts",
    category: str = "Research/Lab Supplies (3105)",
    project_id: str = "PG000025831",
    fund: str = "144",
    delivery_room: str = "ERB 212",
    vendor_contact_name: str = "Rep",
    vendor_contact_email: str = "rep@digikey.com",
    date_of_purchase: str = "2026-10-05",
    payment_method: str = "Workday",
    line_items: str = "",
    quotes_files: list[dict] | None = None,
):
    values = {
        "block_item_description": {
            "item_description": {"type": "plain_text_input", "value": item_description}
        },
        "block_purpose": {
            "purpose": {"type": "plain_text_input", "value": purpose}
        },
        "block_link": {
            "link": {"type": "plain_text_input", "value": link}
        },
        "block_total_price": {
            "total_price": {"type": "plain_text_input", "value": total_price}
        },
        "block_vendor_contact_name": {
            "vendor_contact_name": {"type": "plain_text_input", "value": vendor_contact_name}
        },
        "block_vendor_contact_email": {
            "vendor_contact_email": {"type": "plain_text_input", "value": vendor_contact_email}
        },
        "block_date_of_purchase": {
            "date_of_purchase": {"type": "datepicker", "selected_date": date_of_purchase}
        },
        "block_delivery_room": {
            "delivery_room": {"type": "static_select", "selected_option": {"value": delivery_room}}
        },
        "block_project_id": {
            "project_id": {"type": "static_select", "selected_option": {"value": project_id}}
        },
        "block_fund": {
            "fund": {"type": "static_select", "selected_option": {"value": fund}}
        },
        "block_category": {
            "category": {"type": "static_select", "selected_option": {"value": category}}
        },
    }
    if meta.get("route") == "epif":
        values["block_payment_method"] = {
            "payment_method": {"type": "static_select", "selected_option": {"value": payment_method}}
        }
    if line_items:
        values["block_line_items"] = {
            "line_items": {"type": "plain_text_input", "value": line_items}
        }
    if quotes_files is not None:
        values["block_quotes"] = {
            "quotes": {"type": "file_input", "files": quotes_files}
        }
    return {
        "private_metadata": json.dumps(meta),
        "state": {"values": values},
    }


# ---------------------------------------------------------------------------
# 1. The field (AC 1)
# ---------------------------------------------------------------------------

def test_screen2_renders_quotes_field_when_not_edit():
    """AC: blocks.build_stage2_view(meta) contains block_quotes, optional True, filetypes ['pdf'], max_files 10."""
    meta = _sample_stage1_meta(is_edit=False)
    view = blocks.build_stage2_view(meta)
    blk_map = {b.get("block_id"): b for b in view.get("blocks", [])}

    assert "block_quotes" in blk_map, "block_quotes must be present when is_edit is False"
    block = blk_map["block_quotes"]
    assert block.get("type") == "input"
    assert block.get("optional") is True

    elem = block.get("element", {})
    assert elem.get("type") == "file_input"
    assert elem.get("action_id") == "quotes"
    assert elem.get("filetypes") == ["pdf"]
    assert elem.get("max_files") == 10

    label = block.get("label", {}).get("text", "")
    assert "Quotes" in label
    assert "PDF" in label

    hint = block.get("hint", {}).get("text", "")
    assert "Up to 10" in hint
    assert "@Purchasing quote" in hint


def test_screen2_edit_view_has_quotes_field_for_appending():
    """Superseded by ticket 86 (ADR 0012 decision 6): Edit now takes late quotes, so the
    edit view carries the same block_quotes file field (and block_bom) as Screen 2.
    The old assertion (no block_quotes on edit) described the pre-86 form."""
    meta = _sample_stage1_meta(is_edit=True)
    view = blocks.build_stage2_view(meta)
    blk_map = {b.get("block_id"): b for b in view.get("blocks", [])}

    assert blk_map["block_quotes"]["element"]["type"] == "file_input"
    assert blk_map["block_quotes"]["element"]["action_id"] == "quotes"
    assert "block_bom" in blk_map


# ---------------------------------------------------------------------------
# 2. extract_modal_files pure helper
# ---------------------------------------------------------------------------

def test_extract_modal_files_extracts_id_and_truncates_name():
    """AC: extract_modal_files extracts id and name truncated to 80 chars, or returns []."""
    values = {
        "block_quotes": {
            "quotes": {
                "type": "file_input",
                "files": [
                    {"id": "F1", "name": "quote_short.pdf"},
                    {"id": "F2", "name": "a" * 100 + ".pdf"},
                ],
            }
        }
    }
    extracted = text_rules.extract_modal_files(values, "block_quotes", "quotes")
    assert len(extracted) == 2
    assert extracted[0] == {"id": "F1", "name": "quote_short.pdf"}
    assert extracted[1]["id"] == "F2"
    assert len(extracted[1]["name"]) == 80
    assert extracted[1]["name"] == ("a" * 100 + ".pdf")[:80]

    # Missing block or action or files
    assert text_rules.extract_modal_files({}, "block_quotes", "quotes") == []
    assert text_rules.extract_modal_files({"block_quotes": {}}, "block_quotes", "quotes") == []
    assert text_rules.extract_modal_files({"block_quotes": {"quotes": {}}}, "block_quotes", "quotes") == []


# ---------------------------------------------------------------------------
# 3. Two quotes posted (AC 2)
# ---------------------------------------------------------------------------

def test_two_quotes_posted_in_metadata_and_uploaded_to_thread(monkeypatch):
    """AC: Submitting with files F1 a.pdf and F2 b.pdf posts card with attachments in metadata,

    no button value containing 'attachments', card text containing 'Quotes: 2',
    and two files_upload_v2 calls with card ts, filenames and download content.
    """
    monkeypatch.setattr(config, "PURCHASING_CHANNEL", "C_PURCHASING")
    roster.add_requester("U_ISAAC", "Isaac")

    client = MagicMock()
    client.chat_postMessage.return_value = {"ok": True, "ts": "1234.5678"}
    client.files_info.side_effect = lambda file: {"ok": True, "file": {"id": file, "name": f"{file}.pdf"}}

    fake_bytes = {
        "F1": b"%PDF-1.4 content of a.pdf",
        "F2": b"%PDF-1.4 content of b.pdf",
    }
    monkeypatch.setattr(slack_io, "download_file", lambda f: fake_bytes[f["id"]])

    ack = MagicMock()
    body = {"user": {"id": "U_ISAAC"}}
    meta = _sample_stage1_meta()
    quotes_files = [
        {"id": "F1", "name": "a.pdf"},
        {"id": "F2", "name": "b.pdf"},
    ]
    view = _make_stage2_view_submission(meta, quotes_files=quotes_files)

    app.handle_stage2_submit(ack, body, client, view)

    ack.assert_called_once_with()
    channel_calls = [c for c in client.chat_postMessage.call_args_list if c[1].get("channel") == "C_PURCHASING"]
    assert len(channel_calls) == 1
    call_kw = channel_calls[0][1]

    # Verify metadata
    payload = call_kw["metadata"]["event_payload"]
    assert payload.get("attachments") == [
        {"role": "quote", "id": "F1", "name": "a.pdf"},
        {"role": "quote", "id": "F2", "name": "b.pdf"},
    ]

    # Verify no button value contains "attachments"
    for b in call_kw["blocks"]:
        if b.get("type") == "actions":
            for elem in b.get("elements", []):
                val = elem.get("value", "")
                assert "attachments" not in val, f"Button value leaked 'attachments': {val}"

    # Verify card text contains "Quotes: 2"
    card_mrkdwn = ""
    for b in call_kw["blocks"]:
        if b.get("type") == "section":
            card_mrkdwn += b.get("text", {}).get("text", "")
    assert "Quotes: 2" in card_mrkdwn or "Quotes: 2" in call_kw.get("text", "")

    # Verify exactly two files_upload_v2 calls with card ts and downloaded bytes
    upload_calls = client.files_upload_v2.call_args_list
    assert len(upload_calls) == 2

    assert upload_calls[0].kwargs["channel"] == "C_PURCHASING"
    assert upload_calls[0].kwargs["thread_ts"] == "1234.5678"
    assert upload_calls[0].kwargs["filename"] == "a.pdf"
    assert upload_calls[0].kwargs["content"] == fake_bytes["F1"]

    assert upload_calls[1].kwargs["channel"] == "C_PURCHASING"
    assert upload_calls[1].kwargs["thread_ts"] == "1234.5678"
    assert upload_calls[1].kwargs["filename"] == "b.pdf"
    assert upload_calls[1].kwargs["content"] == fake_bytes["F2"]


# ---------------------------------------------------------------------------
# 4. Survives Screen 3 (AC 3)
# ---------------------------------------------------------------------------

def test_quotes_survive_screen3_fabrication(monkeypatch):
    """AC: Same files with Fabrication category (Screen 3 shown), then Screen 3 submitted

    -> the posted card's attachments holds both entries.
    """
    monkeypatch.setattr(config, "PURCHASING_CHANNEL", "C_PURCHASING")
    roster.add_requester("U_ISAAC", "Isaac")

    client = MagicMock()
    client.chat_postMessage.return_value = {"ok": True, "ts": "3333.4444"}
    client.files_info.side_effect = lambda file: {"ok": True, "file": {"id": file, "name": f"{file}.pdf"}}
    monkeypatch.setattr(slack_io, "download_file", lambda f: b"fake content")

    ack2 = MagicMock()
    body = {"user": {"id": "U_ISAAC"}}
    meta = _sample_stage1_meta()
    quotes_files = [
        {"id": "F1", "name": "a.pdf"},
        {"id": "F2", "name": "b.pdf"},
    ]
    # Fabrication category forces Screen 3
    view2 = _make_stage2_view_submission(
        meta,
        category="Fabrication Component (4670) > $200",
        quotes_files=quotes_files,
    )

    app.handle_stage2_submit(ack2, body, client, view2)

    # Screen 2 should advance to Screen 3 (response_action="update")
    ack2.assert_called_once()
    call_kwargs = ack2.call_args[1]
    assert call_kwargs.get("response_action") == "update"
    stage3_view = call_kwargs["view"]

    # Now simulate Screen 3 submission
    ack3 = MagicMock()
    view3 = {
        "private_metadata": stage3_view["private_metadata"],
        "state": {
            "values": {
                "block_asset_id": {"asset_id": {"value": "AST-12345"}},
                "block_name_of_system": {"name_of_system": {"value": "Vacuum Chamber"}},
            }
        },
    }

    app.handle_stage3_submit(ack3, body, client, view3)

    ack3.assert_called_once_with()
    channel_calls = [c for c in client.chat_postMessage.call_args_list if c[1].get("channel") == "C_PURCHASING"]
    assert len(channel_calls) == 1
    call_kw = channel_calls[0][1]

    payload = call_kw["metadata"]["event_payload"]
    assert payload.get("attachments") == [
        {"role": "quote", "id": "F1", "name": "a.pdf"},
        {"role": "quote", "id": "F2", "name": "b.pdf"},
    ]


# ---------------------------------------------------------------------------
# 5. Loud failure on download error (AC 4)
# ---------------------------------------------------------------------------

def test_failed_download_is_loud_not_silent(monkeypatch):
    """AC: slack_io.download_file raising for F2 only -> a.pdf uploaded, thread post

    and requester DM naming b.pdf, card still posted.
    """
    monkeypatch.setattr(config, "PURCHASING_CHANNEL", "C_PURCHASING")
    roster.add_requester("U_ISAAC", "Isaac")

    client = MagicMock()
    client.chat_postMessage.return_value = {"ok": True, "ts": "5555.6666"}
    client.files_info.side_effect = lambda file: {"ok": True, "file": {"id": file, "name": f"{file}.pdf"}}

    def fake_download(file_obj):
        if file_obj.get("id") == "F2":
            raise RuntimeError("Slack timeout on F2")
        return b"%PDF-1.4 a.pdf content"

    monkeypatch.setattr(slack_io, "download_file", fake_download)

    ack = MagicMock()
    body = {"user": {"id": "U_ISAAC"}}
    meta = _sample_stage1_meta()
    quotes_files = [
        {"id": "F1", "name": "a.pdf"},
        {"id": "F2", "name": "b.pdf"},
    ]
    view = _make_stage2_view_submission(meta, quotes_files=quotes_files)

    app.handle_stage2_submit(ack, body, client, view)

    ack.assert_called_once_with()

    # Card was still posted
    channel_cards = [c for c in client.chat_postMessage.call_args_list if c[1].get("channel") == "C_PURCHASING" and not c[1].get("thread_ts")]
    assert len(channel_cards) == 1

    # a.pdf was uploaded
    upload_calls = client.files_upload_v2.call_args_list
    assert len(upload_calls) == 1
    assert upload_calls[0].kwargs["filename"] == "a.pdf"

    # Thread post warning about b.pdf
    thread_warnings = [
        c for c in client.chat_postMessage.call_args_list
        if c[1].get("channel") == "C_PURCHASING" and c[1].get("thread_ts") == "5555.6666"
    ]
    assert len(thread_warnings) == 1
    thread_text = thread_warnings[0][1].get("text", "")
    assert "Couldn't attach `b.pdf`" in thread_text
    assert "@Purchasing quote" in thread_text

    # DM to requester about b.pdf
    dm_warnings = [
        c for c in client.chat_postMessage.call_args_list
        if c[1].get("channel") == "U_ISAAC"
    ]
    # Note: user might get confirmation DM too, find the warning DM
    dm_warning_texts = [c[1].get("text", "") for c in dm_warnings if "Couldn't attach `b.pdf`" in c[1].get("text", "")]
    assert len(dm_warning_texts) == 1
    assert "@Purchasing quote" in dm_warning_texts[0]


# ---------------------------------------------------------------------------
# 6. No files, no change (AC 5)
# ---------------------------------------------------------------------------

def test_no_files_no_attachments_key_and_no_file_calls(monkeypatch):
    """AC: Submitting without block_quotes -> card payload has no attachments key,

    files_info and files_upload_v2 are never called.
    """
    monkeypatch.setattr(config, "PURCHASING_CHANNEL", "C_PURCHASING")
    roster.add_requester("U_ISAAC", "Isaac")

    client = MagicMock()
    client.chat_postMessage.return_value = {"ok": True, "ts": "7777.8888"}

    ack = MagicMock()
    body = {"user": {"id": "U_ISAAC"}}
    meta = _sample_stage1_meta()
    view = _make_stage2_view_submission(meta, quotes_files=None)

    app.handle_stage2_submit(ack, body, client, view)

    ack.assert_called_once_with()
    channel_calls = [c for c in client.chat_postMessage.call_args_list if c[1].get("channel") == "C_PURCHASING"]
    assert len(channel_calls) == 1
    call_kw = channel_calls[0][1]

    payload = call_kw["metadata"]["event_payload"]
    assert "attachments" not in payload

    client.files_info.assert_not_called()
    client.files_upload_v2.assert_not_called()
