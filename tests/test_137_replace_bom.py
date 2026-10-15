"""Tests for Ticket 137: Replace BOM, from approval until processed.

Acceptance criteria:
- [ ] test_button_only_while_approved_with_a_bom
- [ ] test_replace_clears_the_off_template_flag
- [ ] test_replace_denied_for_others
- [ ] test_replace_refused_after_processed
"""
import json
import os
from unittest.mock import MagicMock

import pytest

from src import app, blocks, bom, config, lifecycle, slack_io
from tests.test_103_thread_files_at_approval import (  # noqa: F401  (fixtures are reused)
    clean_roster,
    dirs,
    sync_queue,
    temp_workbook,
)
from tests.test_136_thread_bom import _epif_bytes

FIXTURE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "BOM_TEMPLATE_FILLED_EXAMPLE.xlsx")
CHANNEL = "C_PURCHASING"
THREAD = "100.0"


class ThreadClient:
    """A Slack whose thread holds the dropped files and every message the bot posts, with blocks and metadata."""

    def __init__(self, file_messages):
        self.file_messages = file_messages
        self.messages: dict[tuple[str, str], dict] = {}
        self.uploads: list[dict] = []
        self.views_opened: list[dict] = []
        self.views_updated: list[dict] = []
        self._n = 0

    def auth_test(self):
        return {"ok": True, "user_id": "B_BOT"}

    def chat_postMessage(self, **kw):
        self._n += 1
        channel = "D_BUYER" if kw["channel"].startswith("U_") else kw["channel"]
        ts = f"{500 + self._n}.0"
        self.messages[(channel, ts)] = dict(kw, channel=channel, ts=ts)
        return {"ok": True, "ts": ts, "channel": channel}

    def chat_update(self, **kw):
        key = (kw["channel"], kw["ts"])
        self.messages[key] = dict(self.messages.get(key, {}), **kw)
        return {"ok": True}

    def conversations_replies(self, **kw):
        stored = [
            {"ts": m["ts"], "text": m.get("text", ""), "blocks": m.get("blocks", []),
             "metadata": m.get("metadata", {}), "user": "B_BOT"}
            for (ch, _t), m in self.messages.items() if ch == kw["channel"]
        ]
        return {"messages": [*self.file_messages, *stored]}

    def conversations_open(self, **kw):
        return {"channel": {"id": "D_BUYER"}}

    def files_info(self, file):
        return {"file": {"id": file, "name": file}}

    def files_upload_v2(self, **kw):
        self.uploads.append(kw)
        return {"ok": True}

    def chat_getPermalink(self, **kw):
        return {"permalink": "https://example.test/p"}

    def users_info(self, **kw):
        return {"user": {"profile": {"display_name": "x"}}}

    def views_open(self, **kw):
        self.views_opened.append(kw)
        return {"ok": True}

    def views_update(self, **kw):
        self.views_updated.append(kw)
        return {"ok": True}

    def card_blocks(self, channel=CHANNEL):
        return [m for (ch, _t), m in self.messages.items() if ch == channel and m.get("metadata")][0]


@pytest.fixture
def approved_off_template(temp_workbook, dirs, sync_queue, monkeypatch):  # noqa: F811
    """Ticket 136's off-template approval: a Filled-EPIF PDF at $858.50 and a CSV BOM in the thread."""
    with open(FIXTURE, "rb") as f:
        files = {"F_EPIF": _epif_bytes(858.50), "F_BOM": b"item,qty,price\nflask,2,10\n", "F_NEW": f.read()}
    client = ThreadClient([
        {"user": "U_REQ", "ts": "100.0", "files": [{"id": "F_EPIF", "name": "Duniway_EPIF.pdf"}]},
        {"user": "U_REQ", "ts": "101.0", "files": [{"id": "F_BOM", "name": "order.csv"}]},
    ])
    monkeypatch.setattr(slack_io, "download", lambda f: files[f["id"]])
    monkeypatch.setattr(slack_io, "download_file", lambda f: files[f["id"]])
    monkeypatch.setattr(slack_io, "resolve_requester", lambda cl, uid: {"U_REQ": "Alex", "U_BUYER": "Dylan"}.get(uid, "Someone"))
    monkeypatch.setattr(app, "_run_in_background", lambda fn, *a: fn(*a))

    def say(text, thread_ts=None, **kw):
        client.chat_postMessage(channel=CHANNEL, thread_ts=thread_ts, text=text)

    lifecycle.handle_epif_processing(
        client=client, say=say, channel=CHANNEL, thread_ts=THREAD, approver="U_CHARLIE",
        event_ts="102.0", assignee_id="U_BUYER", assignee_name="Dylan",
    )
    card = client.card_blocks()
    return client, card["ts"], dirs


def _pointer_body(client, card_ts, user_id, action_id=config.ACTION_REPLACE_BOM):
    dm = blocks.build_dm_card_blocks(
        "approved", {"parsed": {}, "bom_file": "x.xlsx"}, CHANNEL, THREAD, card_ts, route="epif")
    btn = next(e for b in dm if b.get("type") == "actions" for e in b["elements"] if e["action_id"] == action_id)
    return {"user": {"id": user_id}, "trigger_id": "T", "channel": {"id": "D_BUYER"}, "message": {"ts": "9.9"},
            "actions": [{"action_id": action_id, "value": btn["value"]}]}


def _has(blks, action_id):
    return any(e.get("action_id") == action_id for b in blks if b.get("type") == "actions" for e in b["elements"])


def test_button_only_while_approved_with_a_bom():
    req = {"parsed": {"item_description": "x", "total_price": 5.0}, "bom_file": "HIRST_LAB_BOM_x_10.15.2026.xlsx",
           "assignee_id": "U_BUYER", "thread_ts": THREAD}
    assert _has(blocks.build_request_blocks("approved", req), config.ACTION_REPLACE_BOM)
    assert _has(blocks.build_dm_card_blocks("approved", req, CHANNEL, THREAD, "1.0", route="epif"), config.ACTION_REPLACE_BOM)
    for state in ("processed", "confirmed"):
        assert not _has(blocks.build_request_blocks(state, req), config.ACTION_REPLACE_BOM)
        assert not _has(blocks.build_dm_card_blocks(state, req, CHANNEL, THREAD, "1.0", route="epif"), config.ACTION_REPLACE_BOM)
    no_bom = {k: v for k, v in req.items() if k != "bom_file"}
    assert not _has(blocks.build_request_blocks("approved", no_bom), config.ACTION_REPLACE_BOM)
    assert not _has(blocks.build_dm_card_blocks("approved", no_bom, CHANNEL, THREAD, "1.0", route="epif"), config.ACTION_REPLACE_BOM)


def test_replace_clears_the_off_template_flag(approved_off_template):
    client, card_ts, folders = approved_off_template
    (csv_name,) = os.listdir(folders["BOMS_DIR"])
    assert csv_name.endswith(".csv")
    payload = client.card_blocks()["metadata"]["event_payload"]
    assert payload["off_template_bom"] is True
    assert "BOM not in the lab template" in json.dumps(client.messages[("D_BUYER", payload["dm_ts"])]["blocks"], ensure_ascii=False)
    client.uploads.clear()

    # The requester opens the form from the DM card's pointer, submits the template, and passes the check.
    respond = MagicMock()
    app.handle_replace_bom_action(MagicMock(), _pointer_body(client, card_ts, "U_REQ"), respond, client)
    assert client.views_opened and client.views_opened[0]["view"]["callback_id"] == config.REPLACE_BOM_CALLBACK_ID
    form = client.views_opened[0]["view"]
    form["id"] = "V_REPLACE"
    form["state"] = {"values": {"block_bom": {"bom": {"files": [{"id": "F_NEW", "name": "fixed.xlsx"}]}}}}
    first = MagicMock()
    app.handle_replace_bom_submit(first, {"user": {"id": "U_REQ"}}, client, form)
    assert first.call_args.kwargs["response_action"] == "update"
    shown = client.views_updated[-1]["view"]
    assert "4 items" in json.dumps(shown, ensure_ascii=False)
    check = {"id": "V_REPLACE", "private_metadata": shown["private_metadata"],
             "state": {"values": {"block_bom_reupload": {"bom_reupload": {"files": []}}}}}
    done = MagicMock()
    app.handle_bom_check_submit(done, {"user": {"id": "U_REQ"}, "view": {"id": "V_REPLACE"}}, client, check)
    done.assert_called_once_with()

    names = [n for n in os.listdir(folders["BOMS_DIR"]) if n.endswith(".xlsx")]
    assert len(names) == 1
    with open(os.path.join(folders["BOMS_DIR"], names[0]), "rb") as f:
        items, problems = bom.read_bom_template(f.read())
    assert problems == [] and len(items) == 4
    new_payload = client.card_blocks()["metadata"]["event_payload"]
    assert "off_template_bom" not in new_payload and new_payload["bom_file"] == names[0]
    assert len(new_payload["items"]) == 4
    assert "BOM not in the lab template" not in json.dumps(
        client.messages[("D_BUYER", payload["dm_ts"])]["blocks"], ensure_ascii=False)
    assert [u["filename"] for u in client.uploads if u["channel"] == "D_BUYER"] == [names[0]]
    assert any(f"BOM replaced by {names[0]}" in m.get("text", "") for m in client.messages.values())


def test_replace_denied_for_others(approved_off_template):
    client, card_ts, folders = approved_off_template
    before = {n: open(os.path.join(folders["BOMS_DIR"], n), "rb").read() for n in os.listdir(folders["BOMS_DIR"])}
    client.uploads.clear()
    respond = MagicMock()
    app.handle_replace_bom_action(MagicMock(), _pointer_body(client, card_ts, "U_STRANGER"), respond, client)

    assert respond.call_args.kwargs["response_type"] == "ephemeral"
    assert client.views_opened == []
    assert lifecycle.handle_replace_bom(client, CHANNEL, THREAD, card_ts, "U_STRANGER", [{"x": 1}]) is False
    assert client.uploads == []
    assert {n: open(os.path.join(folders["BOMS_DIR"], n), "rb").read() for n in os.listdir(folders["BOMS_DIR"])} == before


def test_replace_refused_after_processed(approved_off_template):
    client, card_ts, folders = approved_off_template
    app.handle_replace_bom_action(MagicMock(), _pointer_body(client, card_ts, "U_REQ"), MagicMock(), client)
    form = client.views_opened[0]["view"]
    form["state"] = {"values": {"block_bom": {"bom": {"files": [{"id": "F_NEW", "name": "fixed.xlsx"}]}}}}

    # The buyer marks it processed while the form is open.
    card = client.card_blocks()
    value = next(json.loads(e["value"]) for b in card["blocks"] if b.get("type") == "actions"
                 for e in b["elements"] if e.get("value", "").startswith('{"state"'))
    client.chat_update(channel=CHANNEL, ts=card_ts,
                       blocks=blocks.build_request_blocks("processed", value["request"], history=value["history"]))
    before = {n: open(os.path.join(folders["BOMS_DIR"], n), "rb").read() for n in os.listdir(folders["BOMS_DIR"])}
    client.uploads.clear()

    ack = MagicMock()
    app.handle_replace_bom_submit(ack, {"user": {"id": "U_REQ"}}, client, form)
    assert ack.call_args.kwargs["response_action"] == "errors"
    assert lifecycle.handle_replace_bom(client, CHANNEL, THREAD, card_ts, "U_REQ", [{"x": 1}]) is False
    assert client.uploads == []
    assert {n: open(os.path.join(folders["BOMS_DIR"], n), "rb").read() for n in os.listdir(folders["BOMS_DIR"])} == before
