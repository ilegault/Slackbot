"""Tests for Ticket 128: Resend EPIF button on the buyer's DM card.

Acceptance criteria:
- [ ] test_resend_epif_button_on_epif_path_only
- [ ] test_resend_epif_uploads_the_archived_files
- [ ] test_resend_epif_denied_for_others
- [ ] test_resend_epif_names_a_missing_file
"""
import json
import os
from unittest.mock import MagicMock

import pytest

from src import app, blocks, bom, config, lifecycle
from tests.test_125_change_epif_date import (  # noqa: F401  (fixtures and fakes shared with 125)
    CHANNEL,
    DM_CHANNEL,
    THREAD,
    FakeClient,
    _buttons,
    _has,
    _request,
    approved,
    isolated_roster,
)


class RowClient(FakeClient):
    """The 125 fake, with message text in thread reads so the logged row can be found."""

    def conversations_replies(self, **kw):
        out = super().conversations_replies(**kw)
        by_ts = {m["ts"]: m for (ch, _t), m in self.messages.items() if ch == kw["channel"]}
        for msg in out["messages"]:
            msg["text"] = by_ts[msg["ts"]].get("text", "")
        return out


@pytest.fixture
def with_bom_and_quote(approved, tmp_path, monkeypatch):  # noqa: F811
    """The approved request, whose card now also names an archived BOM and one archived quote."""
    client, card_ts, epif_path, _writes = approved
    client.__class__ = RowClient
    boms = tmp_path / "BOMs"
    quotes = tmp_path / "Quotes"
    boms.mkdir()
    quotes.mkdir()
    monkeypatch.setattr(config, "BOMS_DIR", str(boms))
    monkeypatch.setattr(config, "QUOTES_DIR", str(quotes))
    msg = client.messages[(CHANNEL, card_ts)]
    value = next(json.loads(e["value"]) for e in _buttons(msg["blocks"]) if e.get("value", "").startswith('{"state"'))
    req = value["request"]
    # The approval's "Logged to row N" thread line is sent through `say`, which the 125 fixture
    # does not keep, so the thread gets it here: this is how the archived quote's name is found.
    row = 17
    client.messages[(CHANNEL, "1500.00")] = {"ts": "1500.00", "channel": CHANNEL,
                                              "text": f"Logged to row {row}: Shaft Couplings"}
    req["bom_file"] = f"{row:04d}_Ruland_BOM.xlsx"
    req["quote_count"] = 1
    quote_name = bom.quote_filename(row, "Ruland", 1)
    (boms / req["bom_file"]).write_bytes(b"bom")
    (quotes / quote_name).write_bytes(b"%PDF quote")
    client.chat_update(
        channel=CHANNEL, ts=card_ts,
        blocks=blocks.build_request_blocks("approved", req, history=value["history"]),
        metadata=msg["metadata"],
    )
    client.uploads.clear()
    client.posts.clear()
    return client, card_ts, epif_path, req["bom_file"], quote_name, boms / req["bom_file"]


def test_resend_epif_button_on_epif_path_only():
    req = {"parsed": _request(), "assignee_id": "U_BUYER"}
    dm = lambda state, route: blocks.build_dm_card_blocks(  # noqa: E731
        state, req, CHANNEL, THREAD, "1.0", route=route)
    for state in ("approved", "processed", "confirmed"):
        assert _has(dm(state, "epif"), config.ACTION_RESEND_EPIF), state
        assert not _has(dm(state, "workday"), config.ACTION_RESEND_EPIF), state
    assert not _has(dm("delivered", "epif"), config.ACTION_RESEND_EPIF)


def _dm_click_body(client, card_ts, user_id):
    dm_blocks = blocks.build_dm_card_blocks(
        "approved", {"parsed": _request(), "assignee_id": "U_BUYER"}, CHANNEL, THREAD, card_ts, route="epif")
    btn = next(e for e in _buttons(dm_blocks) if e["action_id"] == config.ACTION_RESEND_EPIF)
    return {"user": {"id": user_id}, "trigger_id": "T", "channel": {"id": DM_CHANNEL},
            "message": {"ts": "9.9"}, "actions": [{"action_id": config.ACTION_RESEND_EPIF, "value": btn["value"]}]}


def test_resend_epif_uploads_the_archived_files(with_bom_and_quote):
    client, card_ts, epif_path, bom_name, quote_name, _bom_path = with_bom_and_quote
    ack, respond = MagicMock(), MagicMock()
    app.handle_resend_epif_action(ack, _dm_click_body(client, card_ts, "U_BUYER"), respond, client)

    ack.assert_called_once()
    assert sorted(u["filename"] for u in client.uploads) == sorted([os.path.basename(epif_path), bom_name, quote_name])
    assert {u["channel"] for u in client.uploads} == {DM_CHANNEL}
    assert respond.call_args.kwargs["text"].startswith("Sent again:")


def test_resend_epif_denied_for_others(with_bom_and_quote):
    client, card_ts, *_ = with_bom_and_quote
    ack, respond = MagicMock(), MagicMock()
    app.handle_resend_epif_action(ack, _dm_click_body(client, card_ts, "U_OTHER"), respond, client)

    assert client.uploads == []
    assert respond.call_args.kwargs["response_type"] == "ephemeral"
    assert "Only the assigned buyer or an admin" in respond.call_args.kwargs["text"]
    # An admin may.
    respond = MagicMock()
    app.handle_resend_epif_action(MagicMock(), _dm_click_body(client, card_ts, "U_ADMIN"), respond, client)
    assert len(client.uploads) == 3


def test_resend_epif_names_a_missing_file(with_bom_and_quote):
    client, card_ts, epif_path, bom_name, quote_name, bom_path = with_bom_and_quote
    bom_path.unlink()
    respond = MagicMock()
    app.handle_resend_epif_action(MagicMock(), _dm_click_body(client, card_ts, "U_BUYER"), respond, client)

    assert sorted(u["filename"] for u in client.uploads) == sorted([os.path.basename(epif_path), quote_name])
    text = respond.call_args.kwargs["text"]
    assert f"not found: {bom_name}" in text
    assert text.startswith("Sent again:")
    assert lifecycle  # the handler under test lives there; the listener only delegates
