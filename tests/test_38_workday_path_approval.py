import json
import os
import sys
from datetime import date
from unittest.mock import MagicMock, patch

import pytest

# Determine project root and src directory
_CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(_CURRENT_DIR) if os.path.basename(_CURRENT_DIR) == "tests" else _CURRENT_DIR
SRC_DIR = os.path.join(PROJECT_ROOT, "src")
for p in (PROJECT_ROOT, SRC_DIR):
    if p not in sys.path:
        sys.path.insert(0, p)

from src import app, config, lifecycle, log_writer, roster, slack_io, interview


@pytest.fixture(autouse=True)
def setup_test_roster(tmp_path, monkeypatch):
    test_roster_file = str(tmp_path / "roster.json")
    monkeypatch.setattr(roster, "ROSTER_PATH", test_roster_file)
    roster.load_roster()

    # Needs a dummy EPIF dir to check nothing was created
    epifs_dir = tmp_path / "EPIFs"
    epifs_dir.mkdir()
    monkeypatch.setattr(config, "EPIFS_DIR", str(epifs_dir))
    return test_roster_file


def test_workday_path_approval_dm_and_thread(monkeypatch, tmp_path):
    """A Workday-path approval posts 'to place in Workday' thread line,
    DMs the assignee without an email draft, and creates no EPIF."""
    client = MagicMock()
    say = MagicMock()

    # Setup roles
    roster.add_requester("U_CHARLIE", "Charlie Hirst")
    roster.add_approver("U_CHARLIE")
    roster.add_requester("U_SMEET", "Smeet")
    roster.add_buyer("U_SMEET")
    roster.add_requester("U_REQ", "Dylan")

    # Mock an approval event where the requester used the modal and picked a Workday vendor
    parsed_req = {
        "item_description": "Laser Optics Mount",
        "total_price": 149.99,
        "vendor": "Fisher Scientific",
        "vendor_contact_name": "Sales",
        "vendor_contact_email": "sales@fisher.com",
        "date_of_purchase": "2026-09-15",
        "delivery_room": "ERB 212",
        "project_id": "PG000025831",
        "fund": "133",
        "category": "Research/Lab Supplies (3105)",
        "payment_method": "Workday",
        "link": "https://fisher.com/item/123",
        "purpose": "Need a laser mount",
        "pi_of_funding": "Charlie Hirst",
        "end_user": "Dylan",
        "name_of_system": "",
        "asset_id": "",
    }
    req_payload = {
        "parsed": parsed_req,
        "requester": "Dylan",
        "user_id": "U_REQ",
        "is_pending_name": False,
        "route": "workday", # Essential for Workday path
        "thread_ts": "123.45",
    }

    # Fake Excel append
    monkeypatch.setattr(lifecycle.log_writer, "append_row", lambda vals, workbook_path=None: 21)
    monkeypatch.setattr(lifecycle.log_writer, "get_row_info", lambda row: {"row": row})

    # Make submit_write_task synchronous
    def sync_submit(action_fn, channel, thread_ts, user_id, task_type, description, success_callback, failure_callback, client=None):
        res = action_fn()
        success_callback(res)
    monkeypatch.setattr(lifecycle.queue_worker, "submit_write_task", sync_submit)

    body_approve = {
        "user": {"id": "U_CHARLIE"},
        "channel": {"id": "C_PURCHASE"},
        "message": {"ts": "123.50"},
        "container": {"message_ts": "123.50", "thread_ts": "123.45"},
        "actions": [{
            "action_id": "req_approve",
            "value": json.dumps({"state": "posted", "requester": "Dylan", "thread_ts": "123.45", "request": req_payload, "history": []}),
        }],
    }

    # Assign Smeet via the buyer dropdown on the posted card
    req_payload["assignee_id"] = "U_SMEET"
    req_payload["assignee"] = "Smeet"

    # Replace action value with assignment
    body_approve["actions"][0]["value"] = json.dumps({"state": "posted", "requester": "Dylan", "thread_ts": "123.45", "request": req_payload, "history": []})

    # Trigger action
    app.handle_req_approve_action(MagicMock(), body_approve, MagicMock(), client)

    # 1. Thread broadcast says "to place in Workday."
    say_calls = [c for c in client.chat_postMessage.call_args_list if c[1].get("channel") == "C_PURCHASE"]
    assert len(say_calls) == 1
    broadcast_text = say_calls[0][1]["text"]
    assert "👤 Assigned to <@U_SMEET> (Smeet) to place in Workday." in broadcast_text
    assert "Workday / ShopUW" not in broadcast_text

    # 2. DM to Smeet starts with 'Place this in Workday:', has item details, and NO email draft
    dm_calls = [c for c in client.chat_postMessage.call_args_list if c[1].get("channel") == "U_SMEET"]
    assert len(dm_calls) == 1
    dm_text = dm_calls[0][1]["text"]
    assert dm_text.startswith("Place this in Workday:\n")
    assert "• *Item:* Laser Optics Mount" in dm_text
    assert "• *Vendor:* Fisher Scientific" in dm_text
    assert "• *Price:* $149.99" in dm_text
    assert "• *Link:* https://fisher.com/item/123" in dm_text
    assert "• *Row:* 21" in dm_text
    assert "Subject:" not in dm_text
    assert "Hello Tina and Ally" not in dm_text

    # 3. No file upload logic was triggered for the assignee's DM
    assert not client.conversations_open.called
    if hasattr(client, "files_upload_v2"):
        assert not client.files_upload_v2.called
    if hasattr(client, "files_upload"):
        assert not client.files_upload.called

    # 4. No EPIF file appears in the EPIFs/ folder
    epifs_dir = getattr(config, "EPIFS_DIR")
    assert len(os.listdir(epifs_dir)) == 0
