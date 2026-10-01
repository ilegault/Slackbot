"""Tests for Ticket 76: Approval and assignment are written to the request log.

Covers ADR 0011 decision 3:
- Every approval creates one entry in requests.json (the request log).
- An unassigned approval sets buyer_id and buyer_set_at to None.
- Reassignment updates buyer_id, buyer, buyer_set_at, and appends to history in requests.json.
- Log failures never block Slack actions and alert the admin alert channel.
- Assignments on threads with no log entry complete silently with no alert.
- The request log never holds a stage or state key.
"""
import json
import os
from datetime import date
from unittest.mock import MagicMock

import pytest

from src import config, lifecycle, log_writer, queue_worker, roster, slack_io, store, validators


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
        "asset_id": "",
    }


@pytest.fixture
def clean_roster(tmp_path, monkeypatch):
    roster_file = str(tmp_path / "roster.json")
    monkeypatch.setattr(roster, "ROSTER_PATH", roster_file)
    roster._DATA = None
    data = {
        "admins": ["U_ADMIN"],
        "approvers": ["U_CHARLIE"],
        "buyers": ["U_BUYER_A", "U_BUYER_B"],
        "requesters": {
            "U_ADMIN": "Isaac",
            "U_CHARLIE": "Charlie H.",
            "U_BUYER_A": "Alice",
            "U_BUYER_B": "Bob",
            "U_REQ": "Alex",
        },
        "vendors": [],
    }
    with open(roster_file, "w", encoding="utf-8") as f:
        json.dump(data, f)

    monkeypatch.setattr(validators, "validate", lambda *args, **kwargs: [])
    monkeypatch.setattr(log_writer, "append_row", MagicMock(return_value=17))
    monkeypatch.setattr(log_writer, "build_row", lambda parsed, req: {})
    monkeypatch.setattr(log_writer, "update_row", lambda row, fields: None)
    monkeypatch.setattr(log_writer, "get_row_info", lambda row: {})

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

    monkeypatch.setattr(log_writer, "save_bom", fake_save_bom)
    yield


@pytest.fixture
def temp_store(tmp_path, monkeypatch):
    store_file = str(tmp_path / "requests.json")
    monkeypatch.setattr(store, "STORE_PATH", store_file)
    return store_file


@pytest.fixture
def temp_epifs_dir(tmp_path, monkeypatch):
    d = str(tmp_path / "EPIFs")
    os.makedirs(d, exist_ok=True)
    monkeypatch.setattr(config, "EPIFS_DIR", d)
    return d


@pytest.fixture
def temp_boms_dir(tmp_path, monkeypatch):
    d = str(tmp_path / "BOMs")
    os.makedirs(d, exist_ok=True)
    monkeypatch.setattr(config, "BOMS_DIR", d)
    return d


@pytest.fixture
def sync_queue(monkeypatch):
    def fake_submit(action_fn, *args, **kwargs):
        result = action_fn()
        if "success_callback" in kwargs and kwargs["success_callback"]:
            kwargs["success_callback"](result)
        return result

    monkeypatch.setattr(queue_worker, "submit_write_task", fake_submit)


def _make_fake_client(thread_ts="111.222", card_ts="111.444"):
    client = MagicMock()
    client.conversations_open.return_value = {"channel": {"id": "D_BUYER"}}
    client.chat_postMessage.return_value = {"ts": card_ts, "ok": True, "channel": "C_PURCHASING"}
    client.conversations_replies.return_value = {
        "messages": [
            {"text": "Can someone approve this purchase?", "ts": thread_ts, "user": "U_REQ"}
        ]
    }
    return client


def test_approval_creates_one_entry(clean_roster, temp_store, temp_epifs_dir, temp_boms_dir, sync_queue):
    """AC 1: Approval creates one entry in requests.json with thread_ts, card_ts, buyer_id, approved_at, etc."""
    client = _make_fake_client()
    say = MagicMock()
    parsed = _valid_request()

    lifecycle.finalize_purchase_request(
        client=client,
        say=say,
        channel="C_PURCHASING",
        thread_ts="111.222",
        event_ts="111.333",
        parsed=parsed,
        requester="Alex",
        notify_target="U_REQ",
        assignee_id="U_BUYER_A",
        assignee_name="Alice",
        approver="U_CHARLIE",
    )

    with open(temp_store, "r", encoding="utf-8") as f:
        data = json.load(f)

    assert len(data) == 1, f"Expected exactly one entry in requests.json, got {len(data)}"
    req_id, entry = next(iter(data.items()))
    assert entry["channel"] == "C_PURCHASING"
    assert entry["thread_ts"] == "111.222"
    assert entry["card_ts"] == "111.444"
    assert entry["buyer_id"] == "U_BUYER_A"
    assert entry["buyer"] == "Alice"
    assert entry["rows"] == [17]
    assert entry["approved_at"] is not None
    assert entry["buyer_set_at"] is not None
    assert entry.get("cancelled") is False
    assert any(h.startswith("Approved by") for h in entry.get("history", []))
    assert "state" not in entry
    assert "stage" not in entry


def test_unassigned_approval(clean_roster, temp_store, temp_epifs_dir, temp_boms_dir, sync_queue):
    """AC 2: Approval with no buyer named sets buyer_id is None and buyer_set_at is None."""
    client = _make_fake_client()
    say = MagicMock()
    parsed = _valid_request()

    lifecycle.finalize_purchase_request(
        client=client,
        say=say,
        channel="C_PURCHASING",
        thread_ts="111.222",
        event_ts="111.333",
        parsed=parsed,
        requester="Alex",
        notify_target="U_REQ",
        assignee_id=None,
        assignee_name=None,
        approver="U_CHARLIE",
    )

    with open(temp_store, "r", encoding="utf-8") as f:
        data = json.load(f)

    assert len(data) == 1
    req_id, entry = next(iter(data.items()))
    assert entry["buyer_id"] is None
    assert entry["buyer_set_at"] is None
    assert entry["approved_at"] is not None
    assert any(h.startswith("Approved by") for h in entry.get("history", []))
    assert "state" not in entry
    assert "stage" not in entry


def test_reassignment_updates_entry(clean_roster, temp_store, temp_epifs_dir, temp_boms_dir, sync_queue):
    """AC 3: After approval, lifecycle.handle_assign updates buyer_id, buyer_set_at, and appends history."""
    client = _make_fake_client()
    say = MagicMock()
    parsed = _valid_request()

    lifecycle.finalize_purchase_request(
        client=client,
        say=say,
        channel="C_PURCHASING",
        thread_ts="111.222",
        event_ts="111.333",
        parsed=parsed,
        requester="Alex",
        notify_target="U_REQ",
        assignee_id="U_BUYER_A",
        assignee_name="Alice",
        approver="U_CHARLIE",
    )

    with open(temp_store, "r", encoding="utf-8") as f:
        data_before = json.load(f)
    approved_at = list(data_before.values())[0]["approved_at"]

    # Reassign to Buyer B (Bob) by Buyer A (Alice)
    req_data = {
        "parsed": parsed,
        "item_description": parsed["item_description"],
        "assignee_id": "U_BUYER_A",
        "assignee": "Alice",
        "row": 17,
    }
    history = ["Approved by Charlie H. on 09/30/26 12:00"]

    success = lifecycle.handle_assign(
        client=client,
        say=say,
        channel="C_PURCHASING",
        thread_ts="111.222",
        user_id="U_BUYER_A",
        event_ts="111.555",
        target_user_id="U_BUYER_B",
        req_data=req_data,
        msg_ts="111.444",
        history=history,
        current_state="approved",
    )
    assert success is True

    with open(temp_store, "r", encoding="utf-8") as f:
        data_after = json.load(f)

    assert len(data_after) == 1
    req_id, entry = next(iter(data_after.items()))
    assert entry["buyer_id"] == "U_BUYER_B"
    assert entry["buyer"] == "Bob"
    assert entry["buyer_set_at"] is not None
    assert entry["buyer_set_at"] >= approved_at
    assert entry["history"][-1].startswith("Reassigned to")


def test_log_failure_never_blocks_and_alerts(clean_roster, temp_store, temp_epifs_dir, temp_boms_dir, sync_queue, monkeypatch):
    """AC 4: With store.create monkeypatched to raise, approval succeeds and alerts admin alert channel."""
    client = _make_fake_client()
    say = MagicMock()
    parsed = _valid_request()

    def buggy_create(*args, **kwargs):
        raise IOError("Disk full or permission denied")

    monkeypatch.setattr(store, "create", buggy_create)

    alerts = []
    monkeypatch.setattr(slack_io, "alert_admins", lambda cl, text: alerts.append(text))

    lifecycle.finalize_purchase_request(
        client=client,
        say=say,
        channel="C_PURCHASING",
        thread_ts="111.222",
        event_ts="111.333",
        parsed=parsed,
        requester="Alex",
        notify_target="U_REQ",
        assignee_id="U_BUYER_A",
        assignee_name="Alice",
        approver="U_CHARLIE",
    )

    # Workbook row still appended
    log_writer.append_row.assert_called_once()
    # Card post still attempted
    assert client.chat_postMessage.called
    # Admin alert channel notified with message containing 'request log'
    assert len(alerts) == 1, f"Expected 1 alert, got {len(alerts)}: {alerts}"
    assert "request log" in alerts[0].lower()


def test_no_entry_no_noise(clean_roster, temp_store, temp_epifs_dir, temp_boms_dir, sync_queue, monkeypatch):
    """AC 5: handle_assign on thread with no log entry completes silently without alerting."""
    client = _make_fake_client()
    say = MagicMock()
    parsed = _valid_request()

    alerts = []
    monkeypatch.setattr(slack_io, "alert_admins", lambda cl, text: alerts.append(text))

    req_data = {
        "parsed": parsed,
        "item_description": parsed["item_description"],
        "assignee_id": None,
        "assignee": None,
        "row": 17,
    }
    history = []

    # Store file does not exist yet (or is empty)
    success = lifecycle.handle_assign(
        client=client,
        say=say,
        channel="C_PURCHASING",
        thread_ts="111.999",
        user_id="U_BUYER_A",
        event_ts="111.555",
        target_user_id="U_BUYER_A",
        req_data=req_data,
        msg_ts="111.444",
        history=history,
        current_state="approved",
    )
    assert success is True
    # No store file was created, or if created it's empty
    if os.path.exists(temp_store):
        with open(temp_store, "r", encoding="utf-8") as f:
            data = json.load(f)
        assert len(data) == 0

    assert len(alerts) == 0


def test_find_id_by_thread(temp_store):
    """Helper test for store.find_id_by_thread."""
    assert store.find_id_by_thread("C1", "T1") is None

    req_id = store.create(channel="C1", thread_ts="T1", requester="Alex")
    assert store.find_id_by_thread("C1", "T1") == req_id
    assert store.find_id_by_thread("C1", "T2") is None
    assert store.find_id_by_thread("C2", "T1") is None
