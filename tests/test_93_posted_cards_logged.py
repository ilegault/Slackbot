"""Tests for Ticket 93: posted cards enter the request log.

Covers ADR 0013 decision 7 and ADR 0011 decision 3 (amended):
- Posting a card (modal or EPIF drop) creates the request-log entry, with posted_at and no approved_at.
- Approval updates that same entry (one history per request); a batch thread holding several
  posted cards is matched by card, never by thread.
- Declined and superseded cards are flagged in the log.
- The nudge never acts on an entry nobody has approved; a log failure never blocks posting.
"""
import json
import os
from datetime import date
from unittest.mock import MagicMock, patch

import pytest

from src import config, lifecycle, log_writer, nudge, queue_worker, roster, slack_io, store, validators

CHANNEL = "C_PURCHASING"


@pytest.fixture(autouse=True)
def env(tmp_path, monkeypatch):
    roster_file = str(tmp_path / "roster.json")
    monkeypatch.setattr(roster, "ROSTER_PATH", roster_file)
    roster._DATA = None
    with open(roster_file, "w", encoding="utf-8") as f:
        json.dump({
            "admins": ["U_ADMIN"], "approvers": ["U_CHARLIE"], "buyers": ["U_BUYER_A", "U_BUYER_B"],
            "requesters": {"U_REQ": "Alex", "U_CHARLIE": "Charlie H.", "U_BUYER_A": "Alice", "U_BUYER_B": "Bob"},
            "vendors": [],
        }, f)
    monkeypatch.setattr(roster, "_trigger_roster_sync", lambda: None)
    monkeypatch.setattr(config, "PURCHASING_CHANNEL", CHANNEL)
    monkeypatch.setattr(config, "ADMIN_ALERT_CHANNEL", "C_ADMIN")
    epifs = tmp_path / "EPIFs"
    boms = tmp_path / "BOMs"
    epifs.mkdir()
    boms.mkdir()
    monkeypatch.setattr(config, "EPIFS_DIR", str(epifs))
    monkeypatch.setattr(config, "BOMS_DIR", str(boms))
    monkeypatch.setattr(validators, "validate", lambda *a, **k: [])
    monkeypatch.setattr(log_writer, "append_row", MagicMock(return_value=17))
    monkeypatch.setattr(log_writer, "build_row", lambda parsed, req: {})
    monkeypatch.setattr(log_writer, "update_row", lambda row, fields: None)
    monkeypatch.setattr(log_writer, "get_row_info", lambda row: {})
    monkeypatch.setattr(log_writer, "save_epif", lambda content, name: os.path.join(config.EPIFS_DIR, name))

    def fake_submit(action_fn, *args, **kwargs):
        result = action_fn()
        if kwargs.get("success_callback"):
            kwargs["success_callback"](result)
        return result

    monkeypatch.setattr(queue_worker, "submit_write_task", fake_submit)


def _entries():
    return store.load_store()


def _client(card_ts="500.001", messages=None):
    client = MagicMock()
    client.chat_postMessage.return_value = {"ts": card_ts, "ok": True}
    client.conversations_open.return_value = {"channel": {"id": "D_X"}}
    client.conversations_replies.return_value = {"messages": messages or []}
    return client


def _modal(client):
    meta = {
        "resolved_name": "Alex", "user_id": "U_REQ", "vendor_choice": "DigiKey",
        "vendor_custom": None, "route": "Workday", "is_pending_name": False,
    }
    stage2 = {
        "item_description": "Oscilloscope probe", "total_price": "120.00",
        "vendor_contact_name": "Support", "vendor_contact_email": "support@digikey.com",
        "project_id": "PG000025831", "fund": "133", "delivery_room": "ERB 212",
        "purpose": "Sensor testing", "category": "Research/Lab Supplies (3105)",
        "payment_method": "P-card", "date_of_purchase": "09/16/26",
    }
    lifecycle._process_interview_completion(MagicMock(), client, {"user": {"id": "U_REQ"}}, meta, stage2, None)


def _parsed():
    return {
        "item_description": "Shaft Couplings", "purpose": "Test stand", "total_price": 50.0,
        "vendor": "Ruland", "vendor_contact_name": "Sales", "vendor_contact_email": "s@ruland.com",
        "date_of_purchase": date(2026, 9, 22), "project_id": "PG000025831", "fund": "133",
        "category": "Supplies", "delivery_room": "ERB 212", "payment_method": "Workday",
        "link": "", "name_of_system": "", "asset_id": "",
    }


def _drop(client, thread_ts="1000.000", user_id="U_REQ"):
    with (
        patch("src.lifecycle.slack_io.download", return_value=b"%PDF-fake"),
        patch("src.lifecycle.epif_parser.parse_epif", return_value=_parsed()),
        patch("src.lifecycle.slack_io.resolve_requester", return_value="Alex"),
    ):
        lifecycle.handle_epif_drop(
            client=client, say=lambda **kw: None, channel=CHANNEL, thread_ts=thread_ts,
            user_id=user_id, file_obj={"name": "epif.pdf", "url_private_download": "x"}, event_ts="2000.000",
        )


def _approve(client, thread_ts, card_ts):
    lifecycle.finalize_purchase_request(
        client=client, say=MagicMock(), channel=CHANNEL, thread_ts=thread_ts, event_ts="9.9",
        parsed=_parsed(), requester="Alex", notify_target="U_REQ", assignee_id="U_BUYER_A",
        assignee_name="Alice", approver="U_CHARLIE", card_ts=card_ts,
    )


def test_find_id_by_card():
    a = store.create(CHANNEL, "T1", "Alex", card_ts="A")
    b = store.create(CHANNEL, "T1", "Alex", card_ts="B")
    assert store.find_id_by_card(CHANNEL, "A") == a
    assert store.find_id_by_card(CHANNEL, "B") == b
    assert store.find_id_by_card(CHANNEL, "Z") is None
    assert store.find_id_by_card("C_OTHER", "A") is None


def test_modal_posting_creates_entry():
    _modal(_client("500.001"))
    entries = _entries()
    assert len(entries) == 1
    e = next(iter(entries.values()))
    assert e["card_ts"] == "500.001"
    assert e["thread_ts"] == "500.001"
    assert e["requester_id"] == "U_REQ"
    assert e["posted_at"]
    assert not e.get("approved_at")
    assert any(h.startswith("Posted by Alex") for h in e["history"])


def test_epif_drop_posting_creates_entry():
    _drop(_client("2000.200"))
    entries = _entries()
    assert len(entries) == 1
    e = next(iter(entries.values()))
    assert e["card_ts"] == "2000.200"
    assert e["thread_ts"] == "1000.000"
    assert e["requester_id"] == "U_REQ"
    assert e["posted_at"] and not e.get("approved_at")


def test_approval_updates_the_same_entry():
    client = _client("500.001")
    _modal(client)
    _approve(client, "500.001", "500.001")
    entries = _entries()
    assert len(entries) == 1
    e = next(iter(entries.values()))
    assert e["card_ts"] == "500.001"
    assert e["approved_at"]
    assert e["rows"] == [17]
    assert any(h.startswith("Posted by") for h in e["history"])
    assert any(h.startswith("Approved by") for h in e["history"])


def test_batch_approval_touches_only_its_own_entry():
    first = store.create(CHANNEL, "T1", "Alex", card_ts="A", posted_at="2026-10-01T09:00:00", history=["Posted by Alex"])
    second = store.create(CHANNEL, "T1", "Alex", card_ts="B", posted_at="2026-10-01T09:01:00", history=["Posted by Alex"])
    client = _client("B")
    _approve(client, "T1", "B")
    entries = _entries()
    assert len(entries) == 2
    assert entries[second]["approved_at"]
    assert not entries[first].get("approved_at")
    assert entries[first]["rows"] == []


def test_batch_approval_without_card_match_never_overwrites_a_posted_entry():
    """Thread fallback may only reuse an entry that was never posted (no posted_at)."""
    first = store.create(CHANNEL, "T1", "Alex", card_ts="A", posted_at="2026-10-01T09:00:00")
    client = _client("NEWCARD")
    _approve(client, "T1", None)
    entries = _entries()
    assert len(entries) == 2
    assert not entries[first].get("approved_at")


def test_decline_flags_entry():
    client = _client("500.001")
    _modal(client)
    lifecycle.handle_decline(client, CHANNEL, "500.001", "U_CHARLIE", {"parsed": _parsed()}, ["Posted by Alex"])
    e = next(iter(_entries().values()))
    assert e["declined"] is True
    assert any(h.startswith("Declined by") for h in e["history"])
    assert not e.get("approved_at")


def test_supersede_flags_old_entry_and_new_card_gets_own():
    old_id = store.create(CHANNEL, "1000.000", "Alex", card_ts="1000.100", posted_at="2026-10-01T09:00:00")
    parsed = _parsed()
    payload = {"parsed": parsed, "requester": "Alex", "user_id": "U_REQ", "is_pending_name": False, "source": "epif"}
    from src import blocks
    old_msg = {
        "ts": "1000.100", "thread_ts": "1000.000", "text": "x",
        "blocks": blocks.build_request_blocks("posted", payload),
        "metadata": {"event_type": "purchase_request", "event_payload": payload},
    }
    client = _client("2000.200", messages=[old_msg])
    _drop(client, thread_ts="1000.000")
    entries = _entries()
    assert entries[old_id]["superseded"] is True
    new = [e for k, e in entries.items() if k != old_id]
    assert len(new) == 1 and new[0]["card_ts"] == "2000.200"
    assert not new[0].get("superseded")


def test_nudge_ignores_posted_entries(monkeypatch):
    # Post through the real flow so the entry exists only because posting created it,
    # then age it three working days: the nudge must still say nothing about it.
    _modal(_client("500.001"))
    request_id = store.find_id_by_card(CHANNEL, "500.001")
    assert request_id is not None
    assert not store.get(request_id).get("approved_at")
    store.update(request_id, posted_at="2026-10-01T09:00:00")
    client = MagicMock()
    nudged = nudge.run_nudges(client, date(2026, 10, 6))
    assert nudged == []
    client.chat_postMessage.assert_not_called()
    client.chat_postEphemeral.assert_not_called()


def test_store_failure_never_blocks_posting(monkeypatch):
    def boom(*a, **k):
        raise OSError("disk full")

    monkeypatch.setattr(store, "create", boom)
    alert = MagicMock()
    monkeypatch.setattr(slack_io, "alert_admins", alert)
    client = _client("500.001")
    _modal(client)
    assert client.chat_postMessage.called
    assert alert.called
    assert any("request log" in str(c.args[1]) for c in alert.call_args_list)
