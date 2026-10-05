"""Tests for Ticket 86: Edit keeps, removes or replaces quotes and the BOM.

Acceptance criteria exercised (ADR 0012 decision 6, ADR 0006 decision 8):
- [ ] The Edit form lists current quotes as pre-ticked checkboxes (not via private_metadata)
- [ ] Unticking removes a quote, a new quote is appended, only new files are re-posted
- [ ] A new BOM replaces the old one
- [ ] The not-both rule runs against the FINAL state (a kept BOM counts)
- [ ] Edit items on an EPIF-born card gets the same checkboxes and removal
- [ ] bom.merge_attachments / bom.describe_attachment_changes, directly
"""
import json
from unittest.mock import MagicMock, patch

import pytest

from src import app, blocks, bom, slack_io
from tests.test_27_line_items_epif_path import _make_thread_message, _sample_epif_card_payload
from tests.test_32_edit_a_posted_card import (
    _make_body,
    _make_client,
    _make_edit_view_submission,
    _sample_modal_card_payload,
)

BOM_OLD = {"role": "bom", "id": "FB0", "name": "old.xlsx"}
Q1 = {"role": "quote", "id": "F1", "name": "a.pdf"}
Q2 = {"role": "quote", "id": "F2", "name": "b.pdf"}
META = {
    "is_edit": True, "channel": "C_CHAN", "thread_ts": "1000.000", "card_ts": "1000.100",
    "vendor_choice": "VWR-AVANTOR", "vendor_custom": "", "route": "workday",
}


def _card(attachments=(BOM_OLD, Q1, Q2)):
    payload = _sample_modal_card_payload()
    if attachments:
        payload["attachments"] = [dict(a) for a in attachments]
    return payload


@pytest.fixture(autouse=True)
def downloads(monkeypatch):
    monkeypatch.setattr(slack_io, "download_file", lambda f: b"bytes-" + f["id"].encode())


def _client(card):
    client = _make_client(card)
    client.files_info.side_effect = lambda file: {"file": {"id": file}}
    return client


def _submit_edit(client, values_extra, line_items_text=""):
    body = _make_edit_view_submission(META, line_items_text=line_items_text)
    body["view"]["state"]["values"].update(values_extra)
    ack = MagicMock()
    with (
        patch("src.app.roster.get_valid_requesters", return_value={"U_ISAAC": "Isaac"}),
        patch("src.lifecycle.slack_io.resolve_requester", return_value="Isaac"),
    ):
        app.handle_edit_submit(ack, body, client, body["view"])
    return ack


def _keep(*ids):
    return {"block_keep_quotes": {"keep_quotes": {"selected_options": [{"value": i} for i in ids]}}}


def _files(block, action, *files):
    return {block: {action: {"files": [{"id": i, "name": n} for i, n in files]}}}


def _thread_lines(client):
    return [c[1]["text"] for c in client.chat_postMessage.call_args_list if c[1].get("thread_ts") == "1000.000"]


def _saved(client):
    return client.chat_update.call_args[1]["metadata"]["event_payload"]["attachments"]


# 1. The form

def test_edit_form_lists_current_quotes_pre_ticked():
    client = _client(_card())
    body = _make_body("U_ISAAC", "C_CHAN", "1000.100", "1000.000")
    with (
        patch("src.app.roster.is_buyer", return_value=False),
        patch("src.app.admin.is_admin_user", return_value=False),
        patch("src.app.slack_io.resolve_requester", return_value="Isaac"),
    ):
        app.handle_req_edit_action(lambda: None, body, MagicMock(), client)
    view = client.views_open.call_args[1]["view"]
    by_id = {b["block_id"]: b for b in view["blocks"]}
    keep = by_id["block_keep_quotes"]["element"]
    assert keep["action_id"] == "keep_quotes"
    assert [(o["value"], o["text"]["text"]) for o in keep["options"]] == [("F1", "a.pdf"), ("F2", "b.pdf")]
    assert keep["initial_options"] == keep["options"]
    assert "block_bom" in by_id and "block_quotes" in by_id
    assert "a.pdf" not in view["private_metadata"]


def test_edit_form_without_quotes_has_no_keep_block():
    client = _client(_card(attachments=()))
    body = _make_body("U_ISAAC", "C_CHAN", "1000.100", "1000.000")
    with (
        patch("src.app.roster.is_buyer", return_value=False),
        patch("src.app.admin.is_admin_user", return_value=False),
        patch("src.app.slack_io.resolve_requester", return_value="Isaac"),
    ):
        app.handle_req_edit_action(lambda: None, body, MagicMock(), client)
    ids = [b["block_id"] for b in client.views_open.call_args[1]["view"]["blocks"]]
    assert "block_keep_quotes" not in ids
    assert "block_bom" in ids and "block_quotes" in ids
    assert blocks.keep_quotes_input([]) is None


# 2. Submit behaviour

def test_remove_one_quote_and_add_another():
    client = _client(_card())
    values = {**_keep("F1"), **_files("block_quotes", "quotes", ("F3", "c.pdf"))}
    ack = _submit_edit(client, values)
    ack.assert_called_once_with()
    saved = _saved(client)
    assert [(a["role"], a["name"]) for a in saved] == [("bom", "old.xlsx"), ("quote", "a.pdf"), ("quote", "c.pdf")]
    assert client.files_upload_v2.call_count == 1
    assert client.files_upload_v2.call_args[1]["filename"] == "c.pdf"
    line = [t for t in _thread_lines(client) if "Edited by" in t]
    assert len(line) == 1 and "removed quote b.pdf" in line[0] and "added quote c.pdf" in line[0]


def test_new_bom_replaces_old():
    client = _client(_card())
    values = {
        **_keep("F1", "F2"),
        **_files("block_bom", "bom", ("FB1", "new.xlsx")),
        "block_bom_one_vendor": {"bom_one_vendor": {"selected_options": [{"value": "one_vendor"}]}},
    }
    ack = _submit_edit(client, values)
    ack.assert_called_once_with()
    saved = _saved(client)
    assert [a["name"] for a in saved if a["role"] == "bom"] == ["new.xlsx"]
    assert [a["name"] for a in saved if a["role"] == "quote"] == ["a.pdf", "b.pdf"]
    assert [c[1]["filename"] for c in client.files_upload_v2.call_args_list] == ["new.xlsx"]
    assert any("replaced BOM with new.xlsx" in t for t in _thread_lines(client))


def test_new_bom_without_one_vendor_box_is_refused():
    client = _client(_card())
    ack = _submit_edit(client, {**_keep("F1", "F2"), **_files("block_bom", "bom", ("FB1", "new.xlsx"))})
    assert ack.call_args[1]["errors"] == bom.attachment_errors([BOM_OLD], False, "")
    assert "block_bom_one_vendor" in ack.call_args[1]["errors"]
    client.chat_update.assert_not_called()


def test_pasting_items_while_card_keeps_bom_is_refused():
    client = _client(_card())
    ack = _submit_edit(client, _keep("F1", "F2"), line_items_text="1 | Coupling | C-1 | 100.00 | |")
    ack.assert_called_once_with(
        response_action="errors", errors={"block_bom": "Attach a BOM or paste line items, not both."}
    )
    client.chat_update.assert_not_called()
    client.files_upload_v2.assert_not_called()


def test_unchanged_files_post_nothing_but_untick_alone_is_a_change():
    client = _client(_card())
    ack = _submit_edit(client, _keep("F1", "F2"))
    ack.assert_called_once_with()
    client.chat_update.assert_not_called()
    assert _thread_lines(client) == []
    client.files_upload_v2.assert_not_called()

    # Same form, one quote unticked and nothing else touched: that alone is an edit.
    _submit_edit(client, _keep("F1"))
    assert [a["name"] for a in _saved(client)] == ["old.xlsx", "a.pdf"]
    assert [t for t in _thread_lines(client) if "Edited by" in t][0].endswith("removed quote b.pdf")
    client.files_upload_v2.assert_not_called()


def test_file_change_alone_counts_as_a_change():
    client = _client(_card())
    _submit_edit(client, _keep("F1", "F2", ) | _files("block_quotes", "quotes", ("F3", "c.pdf")))
    assert [a["name"] for a in _saved(client) if a["role"] == "quote"] == ["a.pdf", "b.pdf", "c.pdf"]
    assert len([t for t in _thread_lines(client) if "Edited by" in t]) == 1


# 3. Edit items on an EPIF-born card

def _items_client(attachments):
    card = _sample_epif_card_payload()
    card["attachments"] = [dict(a) for a in attachments]
    client = MagicMock()
    client.conversations_replies.return_value = {"ok": True, "messages": [_make_thread_message(card)]}
    client.files_info.side_effect = lambda file: {"file": {"id": file}}
    return client


def test_edit_items_form_and_unticking_removes_quote():
    client = _items_client([Q1, Q2])
    body = {
        "user": {"id": "U_ISAAC"}, "channel": {"id": "C123"},
        "container": {"message_ts": "1000.1000", "thread_ts": "1000.1000"},
        "message": {"ts": "1000.1000", "thread_ts": "1000.1000"}, "trigger_id": "T",
    }
    with (
        patch("src.app.roster.is_buyer", return_value=False),
        patch("src.app.admin.is_admin_user", return_value=False),
        patch("src.app.slack_io.resolve_requester", return_value="Isaac"),
    ):
        app.handle_req_items_action(lambda: None, body, MagicMock(), client)
    view = client.views_open.call_args[1]["view"]
    keep = next(b for b in view["blocks"] if b["block_id"] == "block_keep_quotes")["element"]
    assert [o["value"] for o in keep["initial_options"]] == ["F1", "F2"]
    assert "a.pdf" not in view["private_metadata"]

    values = {
        "block_line_items": {"action_line_items": {"value": None}},
        **_keep("F2"),
    }
    ack = MagicMock()
    app.handle_items_modal_submit(
        ack, {"user": {"id": "U_ISAAC"}}, client,
        {"private_metadata": view["private_metadata"], "state": {"values": values}},
    )
    ack.assert_called_once_with()
    saved = client.chat_update.call_args[1]["metadata"]["event_payload"]["attachments"]
    assert [a["name"] for a in saved] == ["b.pdf"]
    texts = [c[1]["text"] for c in client.chat_postMessage.call_args_list]
    assert any("removed quote a.pdf" in t for t in texts)
    client.files_upload_v2.assert_not_called()


def test_edit_items_removing_every_quote_clears_attachments():
    client = _items_client([Q1])
    values = {"block_line_items": {"action_line_items": {"value": None}}, "block_keep_quotes": {"keep_quotes": {"selected_options": []}}}
    meta = {"channel": "C123", "thread_ts": "1000.1000", "card_ts": "1000.1000"}
    ack = MagicMock()
    app.handle_items_modal_submit(ack, {"user": {"id": "U_ISAAC"}}, client,
                                  {"private_metadata": json.dumps(meta), "state": {"values": values}})
    ack.assert_called_once_with()
    assert "attachments" not in client.chat_update.call_args[1]["metadata"]["event_payload"]


# 4. The pure helpers

def test_merge_attachments_cases():
    current = [BOM_OLD, Q1, Q2]
    new_bom = [{"role": "bom", "id": "FB1", "name": "new.xlsx"}]
    c = {"role": "quote", "id": "F3", "name": "c.pdf"}
    assert bom.merge_attachments(current, ["F1", "F2"], [], []) == current
    assert bom.merge_attachments(current, ["F2"], [], [c]) == [BOM_OLD, Q2, c]
    assert bom.merge_attachments(current, [], new_bom, []) == new_bom
    assert bom.merge_attachments([Q1], ["F1"], [], []) == [Q1]
    assert bom.merge_attachments([], [], [], []) == []


def test_describe_attachment_changes_cases():
    c = {"role": "quote", "id": "F3", "name": "c.pdf"}
    new_bom = {"role": "bom", "id": "FB1", "name": "new.xlsx"}
    assert bom.describe_attachment_changes([BOM_OLD, Q1], [BOM_OLD, Q1]) == []
    assert bom.describe_attachment_changes([BOM_OLD, Q1, Q2], [BOM_OLD, Q1, c]) == [
        "removed quote b.pdf", "added quote c.pdf",
    ]
    assert bom.describe_attachment_changes([BOM_OLD], [new_bom]) == ["replaced BOM with new.xlsx"]
    assert bom.describe_attachment_changes([], [new_bom]) == ["attached BOM new.xlsx"]
