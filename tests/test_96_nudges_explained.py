"""Tests for ticket 96 -- App Home and /purchasing-help explain nudges.

nudge_settings.SETTINGS_PATH is a temp file (conftest); blocks and nudge_settings are real.
"""
import copy
import json
from pathlib import Path

from src import blocks, nudge_settings


def test_defaults_rendered():
    text = blocks.nudge_summary_text(copy.deepcopy(nudge_settings.DEFAULTS))
    assert "*Approved* — off" in text
    assert "*Processed* — every 3 working days after approval until processed, by DM to the buyer" in text
    assert "*Confirmed* — every 5 working days" in text
    assert "*Delivered* — every 10 working days after confirmation until delivered, in the channel" in text
    assert text.rstrip().endswith("_Working days are Monday–Friday. Checked weekdays at 9:00._")


def test_both_and_singular():
    s = copy.deepcopy(nudge_settings.DEFAULTS)
    s["processed"] = {"enabled": True, "every": 1, "dm": True, "channel": True}
    text = blocks.nudge_summary_text(s)
    assert (
        "every 1 working day after approval until processed, by DM to the buyer and in the channel"
        in text
    )
    assert "1 working days" not in text


def test_live_on_app_home_and_in_help():
    s = copy.deepcopy(nudge_settings.DEFAULTS)
    s["delivered"]["every"] = 15
    Path(nudge_settings.SETTINGS_PATH).write_text(json.dumps(s))

    view = blocks.build_app_home_view("U_X")
    headers = [
        b["text"]["text"] for b in view["blocks"] if b["type"] == "header"
    ]
    assert "⏰ Nudges" in headers
    view_json = json.dumps(view, ensure_ascii=False)
    assert "every 15 working days after confirmation" in view_json

    help_text = blocks.get_help_message()
    assert blocks.nudge_summary_text(nudge_settings.load()) in help_text
    assert "every 15 working days after confirmation" in help_text


def test_nudges_section_follows_request_stages():
    headers = [
        b["text"]["text"]
        for b in blocks.build_app_home_view("U_X")["blocks"]
        if b["type"] == "header"
    ]
    assert headers.index("⏰ Nudges") == headers.index("📋 Request Stages") + 1


def test_requester_and_delivered_wording():
    view_json = json.dumps(blocks.build_app_home_view("U_X"), ensure_ascii=False)
    help_text = blocks.get_help_message()
    for text in (view_json, help_text):
        assert "*Mark Delivered* (also the requester)" in text
        assert "The requester can mark this too." in text
        assert "*Mark Processed* and *Mark Confirmed* (the assigned buyer or an admin)" in text
