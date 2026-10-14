"""Tests for Ticket 133: "Send me the BOM template" button, and /blank-template sends it too.

Covers (ADR 0019): the button after the BOM file field on Screen 2, the hint, the DM upload of
the committed template through the real Bolt listener registry, /blank-template sending both
templates, and the admin alert when the template file is missing. The Slack client is faked;
the template file and the listener registry are real.
"""
from unittest.mock import MagicMock

import openpyxl

from src import app, blocks, config, ops

ACTION = "send_bom_template"
FILENAME = "HIRST_LAB_BOM_TEMPLATE.xlsx"


def _meta():
    return {
        "resolved_name": "Isaac",
        "user_id": "U123",
        "vendor_choice": "DigiKey",
        "vendor_custom": None,
        "route": "Workday",
        "is_pending_name": False,
    }


def _find_listener(action_id):
    for listener in app.app._listeners:
        for matcher in getattr(listener, "matchers", []):
            func = getattr(matcher, "func", None)
            for cell in getattr(func, "__closure__", None) or []:
                if cell.cell_contents == action_id:
                    return listener
    raise ValueError(f"No listener registered for action '{action_id}'")


def _client():
    client = MagicMock()
    client.conversations_open.return_value = {"channel": {"id": "D_DM"}}
    return client


def test_screen2_offers_the_template():
    assert config.ACTION_SEND_BOM_TEMPLATE == ACTION
    bl = blocks.build_stage2_view(_meta())["blocks"]
    idx = next(i for i, b in enumerate(bl) if b.get("block_id") == "block_bom")
    assert "lab BOM template" in bl[idx]["hint"]["text"]
    assert bl[idx]["hint"]["text"] == "Two or more items? Fill in the lab BOM template."
    nxt = bl[idx + 1]
    assert nxt["type"] == "actions"
    assert [e["action_id"] for e in nxt["elements"]] == [ACTION]
    assert nxt["elements"][0]["text"]["text"] == "Send me the BOM template"


def test_button_dms_the_template():
    client = _client()
    ack = MagicMock()
    body = {"user": {"id": "U123"}, "actions": [{"action_id": ACTION}], "view": {"id": "V1"}}
    _find_listener(ACTION).ack_function(ack=ack, body=body, client=client)
    ack.assert_called_once()
    client.conversations_open.assert_called_once_with(users="U123")
    assert client.files_upload_v2.call_count == 1
    kw = client.files_upload_v2.call_args.kwargs
    assert kw["filename"] == FILENAME
    assert kw["channel"] == "D_DM"
    wb = openpyxl.load_workbook(kw["file"])
    assert wb.sheetnames
    wb.close()
    client.views_update.assert_not_called()
    client.views_open.assert_not_called()


def test_blank_template_sends_both(tmp_path, monkeypatch):
    epif = tmp_path / "EPIF_TEMPLATE_HIRST.pdf"
    epif.write_bytes(b"%PDF-1.4 fake")
    monkeypatch.setattr(config, "EPIF_TEMPLATE_PATH", str(epif))
    client = _client()
    ops.handle_template_command(client, MagicMock(), channel="C1", thread_ts=None, user_id="U123")
    names = [c.kwargs["filename"] for c in client.files_upload_v2.call_args_list]
    assert "EPIF_TEMPLATE_HIRST.pdf" in names
    assert FILENAME in names


def test_missing_template_alerts_admin(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "BOM_TEMPLATE_PATH", str(tmp_path / "gone.xlsx"))
    monkeypatch.setattr(config, "ADMIN_ALERT_CHANNEL", "C_ADMIN")
    client = _client()
    assert ops.send_bom_template(client, "U123") is False
    client.files_upload_v2.assert_not_called()
    assert client.chat_postMessage.call_count == 1
    kw = client.chat_postMessage.call_args.kwargs
    assert kw["channel"] == "C_ADMIN"
    assert "BOM_TEMPLATE_PATH" in kw["text"]
