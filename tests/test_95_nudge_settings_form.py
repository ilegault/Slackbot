"""Tests for ticket 95: admin edits nudge settings from App Home (ADR 0013 decision 3)."""
import json
import os
import sys
from unittest.mock import MagicMock

import pytest

_CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(_CURRENT_DIR)
for p in (PROJECT_ROOT, os.path.join(PROJECT_ROOT, "src")):
    if p not in sys.path:
        sys.path.insert(0, p)

from src import app, blocks, config, nudge_settings, roster


@pytest.fixture(autouse=True)
def temp_files(tmp_path, monkeypatch):
    rp = str(tmp_path / "roster.json")
    with open(rp, "w", encoding="utf-8") as f:
        json.dump({"requesters": {"U_ADM": "Admin", "U_X": "Xavier"}, "admins": ["U_ADM"],
                   "approvers": [], "buyers": [], "vendors": []}, f)
    monkeypatch.setattr(roster, "ROSTER_PATH", rp)
    monkeypatch.setattr(nudge_settings, "SETTINGS_PATH", str(tmp_path / "nudge_settings.json"))
    monkeypatch.setattr(config, "ADMIN_ALERT_CHANNEL", "C_ALERTS")
    return tmp_path


def _buttons(view):
    return [e for b in view["blocks"] if b.get("type") == "actions" for e in b.get("elements", [])]


def _form_values(delivered_every="15", delivered_send=("dm", "channel"), processed_send=("dm",), every="3"):
    def chk(vals):
        return {"selected_options": [{"value": v} for v in vals]}
    values = {}
    for s in nudge_settings.STAGES:
        values[f"block_{s}_enabled"] = {"enabled": chk(["on"])}
        values[f"block_{s}_every"] = {"every": {"value": every}}
        values[f"block_{s}_send"] = {"send": chk(processed_send)}
    values["block_delivered_every"] = {"every": {"value": delivered_every}}
    values["block_delivered_send"] = {"send": chk(delivered_send)}
    return {"state": {"values": values}}


def _submit(user, view):
    ack, client = MagicMock(), MagicMock()
    app.handle_nudge_settings_submit(ack, {"user": {"id": user}}, client, view)
    return ack, client


def test_only_admins_see_button():
    adm = [b["action_id"] for b in _buttons(blocks.build_app_home_view("U_ADM"))]
    usr = [b.get("action_id") for b in _buttons(blocks.build_app_home_view("U_X"))]
    assert "open_nudge_settings" in adm
    assert "open_nudge_settings" not in usr


def test_form_is_prefilled_from_defaults():
    view = blocks.build_nudge_settings_view(nudge_settings.DEFAULTS)
    assert view["callback_id"] == config.NUDGE_SETTINGS_CALLBACK_ID
    by_id = {b["block_id"]: b for b in view["blocks"] if b.get("block_id")}
    for s in nudge_settings.STAGES:
        for k in ("enabled", "every", "send"):
            assert f"block_{s}_{k}" in by_id
    assert len(by_id) == 12
    assert by_id["block_delivered_every"]["element"]["initial_value"] == "10"
    send = by_id["block_delivered_send"]["element"]["initial_options"]
    assert [o["value"] for o in send] == ["channel"]
    assert "initial_options" not in by_id["block_approved_enabled"]["element"]
    assert [o["value"] for o in by_id["block_processed_enabled"]["element"]["initial_options"]] == ["on"]


def test_admin_save_writes_file_publishes_home_and_alerts():
    ack, client = _submit("U_ADM", _form_values())
    ack.assert_called_once_with()
    assert nudge_settings.load()["delivered"] == {"enabled": True, "every": 15, "dm": True, "channel": True}
    assert client.views_publish.call_args[1]["user_id"] == "U_ADM"
    assert client.chat_postMessage.call_count == 1
    kw = client.chat_postMessage.call_args[1]
    assert kw["channel"] == "C_ALERTS" and "<@U_ADM>" in kw["text"]


def test_validation_errors_and_file_unchanged(temp_files):
    ack, client = _submit("U_ADM", _form_values(processed_send=()))
    errors = ack.call_args[1]["errors"]
    assert ack.call_args[1]["response_action"] == "errors"
    assert errors["block_processed_send"] == "Pick DM, Channel or both."
    assert not os.path.exists(nudge_settings.SETTINGS_PATH)
    client.chat_postMessage.assert_not_called()

    ack, _ = _submit("U_ADM", _form_values(every="0"))
    assert "block_approved_every" in ack.call_args[1]["errors"]
    assert not os.path.exists(nudge_settings.SETTINGS_PATH)


def test_non_admin_click_gets_dm_and_no_modal():
    ack, client = MagicMock(), MagicMock()
    app.handle_open_nudge_settings_action(ack, {"user": {"id": "U_X"}, "trigger_id": "T"}, client)
    client.views_open.assert_not_called()
    assert client.chat_postMessage.call_args[1]["channel"] == "U_X"
    assert "Only admins" in client.chat_postMessage.call_args[1]["text"]


def test_admin_click_opens_prefilled_modal():
    ack, client = MagicMock(), MagicMock()
    app.handle_open_nudge_settings_action(ack, {"user": {"id": "U_ADM"}, "trigger_id": "T"}, client)
    view = client.views_open.call_args[1]["view"]
    assert view["callback_id"] == config.NUDGE_SETTINGS_CALLBACK_ID


def test_non_admin_submit_refused_and_file_unchanged():
    ack, client = _submit("U_X", _form_values())
    assert ack.call_args[1]["errors"] == {"block_approved_enabled": "Only admins can change nudge settings."}
    assert not os.path.exists(nudge_settings.SETTINGS_PATH)
    client.chat_postMessage.assert_not_called()
    client.views_publish.assert_not_called()
