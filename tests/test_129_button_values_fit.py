"""Tests for Ticket 129: every button value fits for the largest request the forms allow.

Slack refuses a card whose button `value` is over 2,000 characters (`invalid_blocks`). It stopped
a card being posted on 2026-09-29 and an Edit on 2026-10-13. The fake client here enforces the
same limit on every post and update, so a card the real Slack would refuse fails the test.

Acceptance criteria:
- [ ] test_every_button_value_fits_for_the_largest_request
- [ ] test_a_large_edit_reaches_the_card
- [ ] test_largest_request_moves_through_the_stages
"""
import copy
import datetime
import json
import os
from unittest.mock import MagicMock, patch

import pytest
from slack_sdk.errors import SlackApiError

from src import app, blocks, config, queue_worker, roster
from tests.test_45_epif_approval_archives import create_test_workbook

FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")
TEMPLATE = os.path.join(FIXTURES, "EPIF_TEMPLATE_HIRST.pdf")
CHANNEL = "C_PURCHASING"
THREAD = "1000.000"
LIMIT = 2000


def _stage2_max_lengths() -> dict:
    """The max_length of every text input on the real Screen 2, by action_id."""
    view = blocks.build_stage2_view({"route": "epif", "vendor_choice": "Ruland"})
    return {
        b["element"]["action_id"]: b["element"]["max_length"]
        for b in view["blocks"]
        if b.get("element", {}).get("type") == "plain_text_input" and b["element"].get("max_length")
    }


def _largest_request(route: str = "epif", source: str = "modal") -> tuple[dict, list]:
    """A request with every text field at its form maximum, 10 quotes, a 1,500-character paste,
    an EPIF's 28 raw fields at 200 characters and 12 history lines of 120 characters."""
    caps = _stage2_max_lengths()
    parsed = {
        "item_description": "i" * caps["item_description"],
        "purpose": "p" * caps["purpose"],
        "total_price": 250.0,
        "vendor": "Ruland",
        "vendor_contact_name": "n" * 100,
        "vendor_contact_email": "e" * 90 + "@vendor.com",
        "date_of_purchase": "2026-10-06",
        "project_id": "PG000025831",
        "fund": "133",
        "category": "Fabrication Component (4670) > $200",
        "delivery_room": "ERB 212",
        "payment_method": "P-card" if route == "epif" else config.WORKDAY_PAYMENT_METHOD,
        "link": "https://example.com/" + "l" * 180,
        "name_of_system": "s" * 100,
        "asset_id": "a" * 50,
        "raw_fields": {f"Field {i}": "r" * 200 for i in range(28)},
    }
    request = {
        "parsed": parsed,
        "requester": "Alex",
        "user_id": "U_REQ",
        "is_pending_name": False,
        "thread_ts": THREAD,
        "source": source,
        "line_items": "1 | Item | PN-1 | 5.00 | https://example.com | description\n" * 26,
        "attachments": [
            {"id": f"F{i}", "name": f"quote_{i}_" + "q" * 60 + ".pdf", "role": "quote"} for i in range(10)
        ],
        "assignee_id": "U_BUYER",
        "assignee": "Dylan",
        "dm_channel": "D_BUYER",
        "dm_ts": "9.9",
        "epif_file": "Ruland_EPIF_$250.00_PG000025831.pdf",
    }
    history = [f"{i:02d} " + "h" * 117 for i in range(12)]
    return request, history


def _values(blks) -> list[str]:
    out = []
    for b in blks:
        for el in b.get("elements", []) if b.get("type") == "actions" else []:
            if "value" in el:
                out.append(el["value"])
            for opt in el.get("options", []):
                out.append(opt.get("value", ""))
    return out


def test_every_button_value_fits_for_the_largest_request():
    request, history = _largest_request()
    assert len(request["line_items"]) >= config.MAX_LINE_ITEMS_LEN
    checked = 0
    for source in ("modal", "epif"):
        request["source"] = source
        for state in ("posted", "waiting_for_details", "approved", "processed", "confirmed"):
            for value in _values(blocks.build_request_blocks(
                state, request, history=history, thread_channel=CHANNEL, card_ts="1000.100",
            )):
                assert len(value) <= LIMIT, (source, state, len(value))
                checked += 1
    for state in ("approved", "processed", "confirmed"):
        for route in ("epif", "workday"):
            dm = blocks.build_dm_card_blocks(state, request, CHANNEL, THREAD, "1000.100", route=route, history=history)
            for value in _values(dm):
                assert len(value) <= LIMIT, ("dm", state, route, len(value))
                checked += 1
            for b in dm:
                assert len(b.get("block_id", "")) <= 255
    assert checked > 20


# ---------------------------------------------------------------------------
# A fake Slack that refuses what Slack refuses
# ---------------------------------------------------------------------------

class LimitedSlack:
    """Stores messages with blocks and metadata, and refuses a button value over 2,000 characters."""

    def __init__(self):
        self.messages: dict[tuple[str, str], dict] = {}
        self.uploads: list[dict] = []
        self.posts: list[dict] = []
        self.refused: list[str] = []
        self._n = 0

    def _check(self, kw):
        for b in kw.get("blocks") or []:
            for el in b.get("elements", []) if b.get("type") == "actions" else []:
                if len(el.get("value", "")) > LIMIT:
                    self.refused.append(el.get("action_id", "?"))
                    raise SlackApiError(
                        "invalid_blocks: must be less than 2001 characters",
                        {"ok": False, "error": "invalid_blocks"},
                    )

    def chat_postMessage(self, **kw):
        self._check(kw)
        self._n += 1
        channel = "D_BUYER" if kw["channel"].startswith("U_") else kw["channel"]
        ts = f"{2000 + self._n}.00"
        self.posts.append(kw)
        self.messages[(channel, ts)] = dict(kw, channel=channel, ts=ts)
        return {"ok": True, "ts": ts, "channel": channel}

    def chat_update(self, **kw):
        self._check(kw)
        key = (kw["channel"], kw["ts"])
        self.messages[key] = dict(self.messages.get(key, {}), **kw)
        return {"ok": True}

    def conversations_replies(self, **kw):
        msgs = [m for (ch, _t), m in self.messages.items() if ch == kw["channel"]]
        return {"messages": [{"ts": m["ts"], "blocks": m.get("blocks", []), "metadata": m.get("metadata", {}),
                              "text": m.get("text", "")} for m in msgs]}

    def conversations_open(self, **kw):
        return {"channel": {"id": "D_BUYER"}}

    def files_upload_v2(self, **kw):
        self.uploads.append(kw)
        return {"ok": True}

    def chat_getPermalink(self, **kw):
        return {"permalink": "https://example.test/p"}

    def users_info(self, **kw):
        return {"user": {"profile": {"display_name": "x"}}}

    def card(self, ts):
        return self.messages[(CHANNEL, ts)]


@pytest.fixture(autouse=True)
def isolated_roster(tmp_path, monkeypatch):
    roster_file = str(tmp_path / "roster.json")
    monkeypatch.setattr(roster, "ROSTER_PATH", roster_file)
    roster._DATA = None
    with open(roster_file, "w", encoding="utf-8") as f:
        json.dump({"admins": ["U_ADMIN"], "approvers": ["U_CHARLIE"], "buyers": ["U_BUYER"],
                   "requesters": {"U_REQ": "Alex", "U_BUYER": "Dylan", "U_CHARLIE": "Charlie H.",
                                  "U_ADMIN": "Isaac"}, "vendors": []}, f)
    yield
    roster._DATA = None


def _post_card(client, request, history=None, state="posted"):
    """Post the card as the lifecycle does: blocks from the real builder, the request in metadata."""
    resp = client.chat_postMessage(
        channel=CHANNEL, thread_ts=THREAD, text="🛒 Purchase Request",
        blocks=blocks.build_request_blocks(state, request, history=history),
        metadata={"event_type": "purchase_request", "event_payload": {**request, "state": state}},
    )
    return resp["ts"]


def _click(client, ts, action_id, user_id, handler, *, respond=None):
    """Deliver a button click the way Bolt does: the global middleware first, then the listener."""
    msg = client.card(ts)
    el = next(e for b in msg["blocks"] if b.get("type") == "actions"
              for e in b["elements"] if e.get("action_id") == action_id)
    body = {
        "type": "block_actions", "user": {"id": user_id}, "channel": {"id": CHANNEL},
        "container": {"message_ts": ts, "thread_ts": THREAD},
        "message": {"ts": ts, "thread_ts": THREAD, "blocks": copy.deepcopy(msg["blocks"])},
        "actions": [{"action_id": action_id, "value": el["value"]}],
        "trigger_id": "T",
    }
    ran = []
    app.expand_slim_card_value(client=client, body=body, next=lambda: ran.append(True))
    assert ran, "the middleware must pass the click on"
    handler(MagicMock(), body, respond or MagicMock(), client)


# ---------------------------------------------------------------------------
# 2. Edit
# ---------------------------------------------------------------------------

def _edit_submission(card_ts, purpose, caps):
    values = {
        "block_item_description": {"item_description": {"type": "plain_text_input", "value": "i" * caps["item_description"]}},
        "block_purpose": {"purpose": {"type": "plain_text_input", "value": purpose}},
        "block_link": {"link": {"type": "plain_text_input", "value": "https://example.com/" + "l" * 180}},
        "block_total_price": {"total_price": {"type": "plain_text_input", "value": "250.00"}},
        "block_vendor_contact_name": {"vendor_contact_name": {"type": "plain_text_input", "value": "n" * 100}},
        "block_vendor_contact_email": {"vendor_contact_email": {"type": "plain_text_input", "value": "e" * 90 + "@vendor.com"}},
        "block_delivery_room": {"delivery_room": {"type": "static_select", "selected_option": {"value": "ERB 212"}}},
        "block_project_id": {"project_id": {"type": "static_select", "selected_option": {"value": "PG000025831"}}},
        "block_fund": {"fund": {"type": "static_select", "selected_option": {"value": "133"}}},
        "block_category": {"category": {"type": "static_select",
                                        "selected_option": {"value": "Fabrication Component (4670) > $200"}}},
        "block_asset_id": {"asset_id": {"type": "plain_text_input", "value": "a" * 50}},
        "block_name_of_system": {"name_of_system": {"type": "plain_text_input", "value": "s" * 100}},
    }
    meta = {"is_edit": True, "channel": CHANNEL, "thread_ts": THREAD, "card_ts": card_ts,
            "vendor_choice": "Ruland", "vendor_custom": "", "route": "workday"}
    return {"user": {"id": "U_REQ"}}, {"state": {"values": values}, "private_metadata": json.dumps(meta)}


def test_a_large_edit_reaches_the_card():
    caps = _stage2_max_lengths()
    request, history = _largest_request(route="workday")
    request["parsed"]["item_description"] = "i" * caps["item_description"]
    request.pop("dm_channel"), request.pop("dm_ts"), request.pop("epif_file")
    request.pop("assignee_id"), request.pop("assignee")
    request.pop("attachments"), request.pop("line_items")
    request["parsed"]["payment_method"] = config.WORKDAY_PAYMENT_METHOD
    client = LimitedSlack()
    card_ts = _post_card(client, request, history)

    new_purpose = "edited " + "q" * (caps["purpose"] - 7)
    body, view = _edit_submission(card_ts, new_purpose, caps)
    ack = MagicMock()
    with patch("src.app.roster.get_valid_requesters", return_value={"U_REQ": "Alex"}):
        app.handle_edit_submit(ack, body, client, view)

    assert client.refused == []
    shown = json.dumps(client.card(card_ts)["blocks"][0])
    assert "edited qqq" in shown
    assert client.card(card_ts)["metadata"]["event_payload"]["parsed"]["purpose"] == new_purpose


# ---------------------------------------------------------------------------
# 3. Through the stages
# ---------------------------------------------------------------------------

def test_largest_request_moves_through_the_stages(tmp_path, monkeypatch):
    wb = str(tmp_path / "Purchasing-Log.xlsx")
    create_test_workbook(wb)
    epifs = str(tmp_path / "EPIFs")
    os.makedirs(epifs)
    monkeypatch.setattr(config, "WORKBOOK_PATH", wb)
    monkeypatch.setattr(config, "EPIFS_DIR", epifs)
    monkeypatch.setattr(config, "EPIF_TEMPLATE_PATH", TEMPLATE)

    def _sync(action_fn, channel="", thread_ts="", user_id="", task_type="append",
              description="", success_callback=None, failure_callback=None, client=None):
        try:
            res = action_fn()
            if success_callback:
                success_callback(res)
        except Exception as exc:
            if failure_callback:
                failure_callback(exc)

    monkeypatch.setattr(queue_worker, "submit_write_task", _sync)

    request, history = _largest_request(route="epif", source="modal")
    for key in ("line_items", "attachments", "dm_channel", "dm_ts", "epif_file", "assignee_id", "assignee"):
        request.pop(key)
    request["parsed"]["date_of_purchase"] = datetime.date(2026, 10, 6)
    request["parsed"].pop("raw_fields")
    client = LimitedSlack()
    ts = _post_card(client, request, history[:1])

    # Charlie approves with the buyer picked; the card, the DM card and every update must be accepted.
    request_with_buyer = {**request, "assignee_id": "U_BUYER", "assignee": "Dylan"}
    client.messages[(CHANNEL, ts)]["metadata"]["event_payload"].update(
        assignee_id="U_BUYER", assignee="Dylan")
    client.messages[(CHANNEL, ts)]["blocks"] = blocks.build_request_blocks(
        "posted", request_with_buyer, history=history[:1])
    respond = MagicMock()
    _click(client, ts, "req_approve", "U_CHARLIE", app.handle_req_approve_action, respond=respond)
    assert client.refused == []
    assert any(el.get("action_id") == "req_processed"
               for b in client.card(ts)["blocks"] if b.get("type") == "actions" for el in b["elements"]), \
        "the card should be approved"

    _click(client, ts, "req_processed", "U_BUYER", app.handle_req_processed_action)
    assert client.refused == []
    assert any(el.get("action_id") == "req_confirmed"
               for b in client.card(ts)["blocks"] if b.get("type") == "actions" for el in b["elements"])

    _click(client, ts, "req_confirmed", "U_BUYER", app.handle_req_confirmed_action)
    assert client.refused == []
    assert any(el.get("action_id") == "req_delivered"
               for b in client.card(ts)["blocks"] if b.get("type") == "actions" for el in b["elements"])
    # Whatever was asked of Slack along the way was accepted, and the purpose was never lost.
    payload = client.card(ts)["metadata"]["event_payload"]
    assert payload["parsed"]["purpose"] == "p" * _stage2_max_lengths()["purpose"]
