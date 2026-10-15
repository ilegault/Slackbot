"""Tests for Ticket 135: Edit and Add items take a BOM through the same check; the paste box is gone everywhere.

Acceptance criteria:
- [ ] test_edit_with_a_new_bom_replaces_the_rows
- [ ] test_add_items_uses_the_check
- [ ] test_no_paste_box_anywhere
- [ ] test_workday_details_uses_the_check (the Workday details form shares the flow)
"""
import json
import os
import pathlib
from unittest.mock import MagicMock, patch

import pytest

from src import app, blocks, bom, lifecycle, slack_io
from tests.test_27_line_items_epif_path import _make_thread_message, _sample_epif_card_payload
from tests.test_32_edit_a_posted_card import (
    _make_client,
    _make_edit_view_submission,
    _sample_modal_card_payload,
)

FIXTURE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "BOM_TEMPLATE_FILLED_EXAMPLE.xlsx")
META = {
    "is_edit": True, "channel": "C_CHAN", "thread_ts": "1000.000", "card_ts": "1000.100",
    "vendor_choice": "VWR-AVANTOR", "vendor_custom": "", "route": "workday",
}


@pytest.fixture(autouse=True)
def world(monkeypatch):
    with open(FIXTURE, "rb") as f:
        data = {"FB1": f.read()}
    monkeypatch.setattr(slack_io, "download_file", lambda f: data[f["id"]])
    monkeypatch.setattr(app, "_run_in_background", lambda fn, *a: fn(*a))


def _client(card):
    client = _make_client(card)
    client.files_info.side_effect = lambda file: {"file": {"id": file}}
    return client


def _edit_body(purpose=None, bom_file=False, total="858.50"):
    overrides = {"total_price": total}
    if purpose:
        overrides["purpose"] = purpose
    body = _make_edit_view_submission(META, stage2_overrides=overrides)
    body["view"]["id"] = "V_EDIT"
    if bom_file:
        body["view"]["state"]["values"]["block_bom"] = {"bom": {"files": [{"id": "FB1", "name": "order.xlsx"}]}}
        body["view"]["state"]["values"]["block_bom_one_vendor"] = {
            "bom_one_vendor": {"selected_options": [{"value": "one_vendor"}]}}
    return body


def _submit_edit(client, body):
    ack = MagicMock()
    with (
        patch("src.app.roster.get_valid_requesters", return_value={"U_ISAAC": "Isaac"}),
        patch("src.lifecycle.slack_io.resolve_requester", return_value="Isaac"),
    ):
        app.handle_edit_submit(ack, body, client, body["view"])
    return ack


def _check_submit(client, view_id, new_file=None):
    shown = client.views_update.call_args.kwargs["view"]
    files = [{"id": new_file, "name": "x.xlsx"}] if new_file else []
    check = {"id": view_id, "private_metadata": shown["private_metadata"],
             "state": {"values": {"block_bom_reupload": {"bom_reupload": {"files": files}}}}}
    ack = MagicMock()
    with patch("src.lifecycle.slack_io.resolve_requester", return_value="Isaac"):
        app.handle_bom_check_submit(ack, {"user": {"id": "U_ISAAC"}, "view": {"id": view_id}}, client, check)
    return ack


def test_edit_with_a_new_bom_replaces_the_rows():
    client = _client(_sample_modal_card_payload())
    first = _submit_edit(client, _edit_body(bom_file=True))
    assert first.call_args.kwargs["response_action"] == "update"
    ack = _check_submit(client, "V_EDIT")
    ack.assert_called_once_with()

    payload = client.chat_update.call_args[1]["metadata"]["event_payload"]
    fixture_items, problems = bom.read_bom_template(open(FIXTURE, "rb").read())
    assert problems == [] and payload["items"] == fixture_items
    lines = [c[1]["text"] for c in client.chat_postMessage.call_args_list if "Edited by" in c[1].get("text", "")]
    assert len(lines) == 1 and "items 0 → 4" in lines[0]
    drafts = [c[1]["filename"] for c in client.files_upload_v2.call_args_list]
    assert len(drafts) == 1 and drafts[0].startswith("DRAFT_HIRST_LAB_BOM_")

    # A second Edit that only changes Purpose keeps the rows and uploads no BOM.
    again = _sample_modal_card_payload(items=payload["items"], total_price=858.50)
    client2 = _client(again)
    ack2 = _submit_edit(client2, _edit_body(purpose="A different purpose"))
    ack2.assert_called_once_with()
    saved = client2.chat_update.call_args[1]["metadata"]["event_payload"]
    assert saved["items"] == payload["items"]
    client2.files_upload_v2.assert_not_called()


def _items_view(bom_files, one_vendor=True):
    values = {
        "block_bom": {"bom": {"files": bom_files}},
        "block_bom_one_vendor": {"bom_one_vendor": {"selected_options": [{"value": "one_vendor"}] if one_vendor else []}},
    }
    return {
        "id": "V_ITEMS",
        "private_metadata": json.dumps({"channel": "C123", "thread_ts": "1000.1000", "card_ts": "1000.1000"}),
        "state": {"values": values},
    }


def test_add_items_uses_the_check(world):
    card = _sample_epif_card_payload(total_price=900.00)
    client = MagicMock()
    client.conversations_replies.return_value = {"ok": True, "messages": [_make_thread_message(card)]}
    client.files_info.side_effect = lambda file: {"file": {"id": file}}
    first = MagicMock()
    app.handle_items_modal_submit(first, {"user": {"id": "U_ISAAC"}}, client, _items_view([{"id": "FB1", "name": "new.xlsx"}]))
    assert first.call_args.kwargs["view"]["callback_id"] == "bom_check_submit"
    shown = client.views_update.call_args.kwargs["view"]
    assert "they must match" in json.dumps(shown, ensure_ascii=False)
    ack = _check_submit(client, "V_ITEMS")
    assert ack.call_args.kwargs["response_action"] == "errors"
    assert "block_bom_reupload" in ack.call_args.kwargs["errors"]
    client.chat_update.assert_not_called()


def test_no_paste_box_anywhere():
    assert '"block_line_items"' not in pathlib.Path(blocks.__file__).read_text(encoding="utf-8")
    assert not hasattr(blocks, "line_items_input")
    views = [
        blocks.build_stage2_view({"route": "workday", "vendor_choice": "DigiKey"}),
        blocks.build_stage2_view({"route": "workday", "is_edit": True}),
        blocks.build_items_view("C1", "T1", "CT1"),
        blocks.build_workday_details_view("C1", "T1", "CT1", ["Grainger"]),
    ]
    for view in views:
        assert "block_line_items" not in [b.get("block_id") for b in view["blocks"]]
    assert not hasattr(bom, "parse_line_items")


def test_workday_details_uses_the_check(monkeypatch):
    card = {"state": "waiting_for_details", "assignee_id": "U_A", "assignee": "A", "approver": "U_C",
            "requester": "Alex", "user_id": "U_REQ"}
    monkeypatch.setattr(slack_io, "get_card_payload", lambda *a, **k: card)
    monkeypatch.setattr(slack_io, "resolve_requester", lambda *a, **k: "Alex")
    monkeypatch.setattr(app.validators, "validate", lambda *a, **k: [])
    finalize = MagicMock()
    monkeypatch.setattr(lifecycle, "finalize_purchase_request", finalize)
    client = MagicMock()
    client.files_info.side_effect = lambda file: {"file": {"id": file}}
    view = {
        "id": "V_WD",
        "private_metadata": json.dumps({"channel_id": "C123", "thread_ts": "T1", "card_ts": "T1"}),
        "state": {"values": {
            "block_vendor": {"vendor": {"selected_option": {"value": "Grainger"}}},
            "block_item_description": {"item_description": {"value": "Gaskets"}},
            "block_total_price": {"total_price": {"value": "900.00"}},
            "block_category": {"category": {"selected_option": {"value": "Lab Consumable"}}},
            "block_bom": {"bom": {"files": [{"id": "FB1", "name": "order.xlsx"}]}},
            "block_bom_one_vendor": {"bom_one_vendor": {"selected_options": [{"value": "one_vendor"}]}},
        }},
    }
    ack = MagicMock()
    app.handle_workday_details_submit(ack, {"user": {"id": "U_REQ"}}, client, view)
    assert ack.call_args.kwargs["response_action"] == "update"
    finalize.assert_not_called()
    # $858.50 against a typed $900.00: refused on the check screen.
    refused = _check_submit(client, "V_WD")
    assert refused.call_args.kwargs["response_action"] == "errors"
    finalize.assert_not_called()
