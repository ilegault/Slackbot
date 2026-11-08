"""Tests for Ticket 144: item links leave the card's Slack metadata (ADR 0020 decision 5).

Acceptance criteria:
- [ ] test_posted_card_metadata_has_no_links_but_the_draft_does
- [ ] test_add_items_and_edit_keep_links_out_of_metadata
- [ ] test_edit_with_only_new_links_reposts_the_draft
- [ ] test_approval_and_replace_bom_keep_links_out_of_metadata
- [ ] items_for_card (pure rule) drops `link` and `row`, keeps everything else
"""
import copy
import os
from datetime import date
from unittest.mock import MagicMock, patch

import openpyxl
import pytest

from src import app, bom, lifecycle, slack_io
from tests.test_27_line_items_epif_path import _make_thread_message, _sample_epif_card_payload
from tests.test_32_edit_a_posted_card import _sample_modal_card_payload
from tests.test_103_thread_files_at_approval import (  # noqa: F401  (fixtures are reused)
    clean_roster,
    dirs,
    sync_queue,
    temp_workbook,
)
from tests.test_134_screen2_bom_check import (
    _check_submission,
    _fixture_bytes,
    _submit_stage2,
)
from tests.test_134_screen2_bom_check import (
    world as screen2_world,  # noqa: F401
)
from tests.test_135_edit_and_add_items_bom import (
    _check_submit,
    _client,
    _edit_body,
    _items_view,
    _submit_edit,
)
from tests.test_137_replace_bom import CHANNEL, THREAD, ThreadClient

FIXTURE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "BOM_TEMPLATE_FILLED_EXAMPLE.xlsx")


def _fixture_items():
    items, problems = bom.read_bom_template(_fixture_bytes())
    assert problems == []
    assert all(i["link"] for i in items), "the filled example carries a link on every row"
    return items


def _with_new_links(items, suffix="v2"):
    out = copy.deepcopy(items)
    for i, item in enumerate(out):
        item["link"] = f"https://new-vendor.example.com/{suffix}/{i}"
    return out


def _stripped(items):
    return [{k: v for k, v in i.items() if k not in ("link", "row")} for i in items]


def _no_links_in(card_items):
    assert card_items, "the card must still carry its rows"
    for item in card_items:
        assert "link" not in item, item
        assert "row" not in item, item


def _links_of(xlsx_bytes):
    items, problems = bom.read_bom_template(xlsx_bytes)
    assert problems == []
    return [i["link"] for i in items]


def _uploaded_draft_links(files_upload_v2_mock):
    calls = [c.kwargs for c in files_upload_v2_mock.call_args_list if c.kwargs.get("filename", "").startswith("DRAFT_")]
    assert len(calls) == 1
    kw = calls[0]
    data = kw.get("file") or kw.get("content")
    if hasattr(data, "read"):
        data = data.read()
    return _links_of(data)


# --- the pure rule -----------------------------------------------------------------------------


def test_items_for_card_drops_link_and_row_and_keeps_the_rest():
    items = [{"name": "A", "qty": 2, "link": "https://x.test/a", "row": 6, "no_link_reason": "", "unit_price": 1.5}]
    out = bom.items_for_card(items)
    assert out == [{"name": "A", "qty": 2, "no_link_reason": "", "unit_price": 1.5}]
    assert "link" in items[0] and "row" in items[0], "the caller's items must not be mutated"
    assert bom.items_for_card(None) == []
    assert bom.items_for_card([]) == []


# --- Screen 2 --------------------------------------------------------------------------------


def test_posted_card_metadata_has_no_links_but_the_draft_does(screen2_world):  # noqa: F811
    world = screen2_world
    expected_links = _links_of(_fixture_bytes())
    assert all(expected_links)
    world.files["F_BOM"] = _fixture_bytes()
    _submit_stage2(world)
    ack = _check_submission(world)
    ack.assert_called_once_with()

    posted = [c.kwargs for c in world.chat_postMessage.call_args_list if c.kwargs.get("metadata")]
    assert len(posted) == 1
    _no_links_in(posted[0]["metadata"]["event_payload"]["items"])
    assert _uploaded_draft_links(world.files_upload_v2) == expected_links


# --- Add items and Edit ----------------------------------------------------------------------


@pytest.fixture(autouse=True)
def inline_background(monkeypatch):
    monkeypatch.setattr(app, "_run_in_background", lambda fn, *a: fn(*a))


@pytest.fixture
def new_links_file(monkeypatch):
    """The download helper serves a version of the fixture whose links differ from the original."""
    items = _with_new_links(_fixture_items())
    data = {"FB1": bom.build_bom_workbook({"item_description": "Copper gaskets", "requester": "Isaac"}, items)}
    monkeypatch.setattr(slack_io, "download_file", lambda f: data[f["id"]])
    return items


def test_add_items_and_edit_keep_links_out_of_metadata(new_links_file):
    expected = [i["link"] for i in new_links_file]

    # Edit with a new, linked BOM.
    client = _client(_sample_modal_card_payload())
    _submit_edit(client, _edit_body(bom_file=True))
    ack = _check_submit(client, "V_EDIT")
    ack.assert_called_once_with()
    _no_links_in(client.chat_update.call_args.kwargs["metadata"]["event_payload"]["items"])
    assert _uploaded_draft_links(client.files_upload_v2) == expected

    # Add items to an EPIF-born card.
    card = _sample_epif_card_payload(total_price=858.50)
    client2 = MagicMock()
    client2.conversations_replies.return_value = {"ok": True, "messages": [_make_thread_message(card)]}
    client2.files_info.side_effect = lambda file: {"file": {"id": file}}
    app.handle_items_modal_submit(
        MagicMock(), {"user": {"id": "U_ISAAC"}}, client2, _items_view([{"id": "FB1", "name": "new.xlsx"}])
    )
    ack2 = _check_submit(client2, "V_ITEMS")
    ack2.assert_called_once_with()
    _no_links_in(client2.chat_update.call_args.kwargs["metadata"]["event_payload"]["items"])
    assert _uploaded_draft_links(client2.files_upload_v2) == expected


def test_edit_with_only_new_links_reposts_the_draft(new_links_file):
    expected = [i["link"] for i in new_links_file]
    # The card already holds the same rows (as metadata stores them: without links).
    card = _sample_modal_card_payload(items=_stripped(_fixture_items()), total_price=858.50)
    client = _client(card)
    _submit_edit(client, _edit_body(bom_file=True))
    ack = _check_submit(client, "V_EDIT")
    ack.assert_called_once_with()

    lines = [c.kwargs["text"] for c in client.chat_postMessage.call_args_list if "Edited by" in c.kwargs.get("text", "")]
    assert len(lines) == 1 and "BOM re-uploaded" in lines[0]
    assert "items changed" not in lines[0]
    assert _uploaded_draft_links(client.files_upload_v2) == expected


def test_edit_without_a_bom_upload_is_not_a_bom_change():
    """Rows from metadata never carry links, so an Edit that only touches Purpose uploads nothing."""
    card = _sample_modal_card_payload(items=_stripped(_fixture_items()), total_price=858.50)
    client = _client(card)
    ack = _submit_edit(client, _edit_body(purpose="A different purpose"))
    ack.assert_called_once_with()
    lines = [c.kwargs["text"] for c in client.chat_postMessage.call_args_list if "Edited by" in c.kwargs.get("text", "")]
    assert len(lines) == 1 and "BOM re-uploaded" not in lines[0]
    client.files_upload_v2.assert_not_called()


# --- Approval, then Replace BOM --------------------------------------------------------------


def test_approval_and_replace_bom_keep_links_out_of_metadata(temp_workbook, dirs, sync_queue, monkeypatch):  # noqa: F811
    draft_items = _fixture_items()
    draft_links = [i["link"] for i in draft_items]
    parsed = {
        "item_description": "Copper gaskets",
        "purpose": "Chamber rebuild",
        "total_price": 858.50,
        "vendor": "VWR",
        "vendor_contact_name": "Sales",
        "vendor_contact_email": "sales@vwr.com",
        "date_of_purchase": date(2026, 9, 22),
        "project_id": "PG000025831",
        "fund": "133",
        "category": "Research/Lab Supplies (3105)",
        "delivery_room": "ERB 212",
        "payment_method": "Workday",
        "link": "",
        "name_of_system": "",
        "asset_id": "",
    }
    draft_bytes = bom.build_bom_workbook({**parsed, "requester": "Alex"}, draft_items)
    replacement_items = _with_new_links(draft_items, "replacement")
    replacement_bytes = bom.build_bom_workbook({**parsed, "requester": "Alex"}, replacement_items)
    files = {"F_DRAFT": draft_bytes, "F_NEW": replacement_bytes}
    monkeypatch.setattr(slack_io, "download_file", lambda f: files[f["id"]])
    monkeypatch.setattr(slack_io, "resolve_requester", lambda cl, uid: {"U_REQ": "Alex", "U_BUYER": "Dylan"}.get(uid, "Someone"))

    card_payload = {
        "parsed": parsed,
        "requester": "Alex",
        "user_id": "U_REQ",
        "items": _stripped(draft_items),
        "source": "modal",
        "thread_ts": THREAD,
    }
    client = ThreadClient(
        [{"user": "B_BOT", "ts": "50.0", "files": [{"id": "F_DRAFT", "name": "DRAFT_HIRST_LAB_BOM_Copper-gaskets_11.02.2026.xlsx"}]}]
    )
    client.messages[(CHANNEL, THREAD)] = {
        "ts": THREAD, "text": "card", "blocks": [], "channel": CHANNEL,
        "metadata": {"event_type": "purchase_request", "event_payload": card_payload},
    }
    say = MagicMock()

    lifecycle.finalize_purchase_request(
        client=client, say=say, channel=CHANNEL, thread_ts=THREAD, event_ts="100.1", parsed=parsed,
        requester="Alex", notify_target="U_REQ", card_ts=THREAD, items=_stripped(draft_items), approver="U_CHARLIE",
    )

    # Approval: the card stays link-free, the archived BOM got the draft's links back.
    approved = client.messages[(CHANNEL, THREAD)]["metadata"]["event_payload"]
    assert approved["state"] == "approved"
    _no_links_in(approved["items"])
    (archived_name,) = [n for n in os.listdir(dirs["BOMS_DIR"]) if n.endswith(".xlsx")]
    with open(os.path.join(dirs["BOMS_DIR"], archived_name), "rb") as f:
        assert _links_of(f.read()) == draft_links
    ws = openpyxl.load_workbook(os.path.join(dirs["BOMS_DIR"], archived_name)).active
    assert ws["D6"].hyperlink is not None and ws["D6"].hyperlink.target == draft_links[0]

    # Replace BOM: rows read from the new file carry links; the card must not.
    with patch("src.lifecycle.slack_io.resolve_requester", return_value="Alex"):
        replaced = lifecycle.handle_replace_bom(client, CHANNEL, THREAD, THREAD, "U_REQ", replacement_items)
    assert replaced is True
    after = client.messages[(CHANNEL, THREAD)]["metadata"]["event_payload"]
    _no_links_in(after["items"])
    with open(os.path.join(dirs["BOMS_DIR"], after["bom_file"]), "rb") as f:
        assert _links_of(f.read()) == [i["link"] for i in replacement_items]
