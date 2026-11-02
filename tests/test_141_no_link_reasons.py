"""Tests for Ticket 141: The BOM check shows each link and asks why a row has none.

Acceptance criteria:
- [ ] test_check_view_shows_site_names_and_one_input_per_unlinked_row
- [ ] test_continue_refused_until_every_reason_is_picked
- [ ] test_picked_reasons_reach_the_draft_bom
- [ ] test_every_bom_route_reaches_the_reason_inputs
- [ ] test_old_template_and_one_row_boms_are_refused
"""
import io
import json
from unittest.mock import MagicMock

import openpyxl
import pytest

from src import app, blocks, bom, config, roster, slack_io
from tests.test_27_line_items_epif_path import _make_thread_message, _sample_epif_card_payload
from tests.test_32_edit_a_posted_card import (
    _make_client,
    _make_edit_view_submission,
    _sample_modal_card_payload,
)
from tests.test_81_quotes_on_new_purchase import (  # noqa: F401
    _make_stage2_view_submission,
    _sample_stage1_meta,
    isolate_roster,
)
from tests.test_82_bom_on_new_purchase import _with_bom
from tests.test_135_edit_and_add_items_bom import _items_view
from tests.test_137_replace_bom import _pointer_body

VIEW_ID = "V_MODAL"


def _text(view) -> str:
    return json.dumps(view, ensure_ascii=False)


def _make_3row_bom() -> bytes:
    items = [
        {
            "row": 6,
            "qty": 2,
            "quantity": 2,
            "name": "Screws",
            "description": "M3x10 screws",
            "part_number": "91251A540",
            "vendor": "McMaster-Carr",
            "unit_price": 5.0,
            "link": "https://www.mcmaster.com/91251A540",
            "no_link_reason": "",
        },
        {
            "row": 7,
            "qty": 1,
            "quantity": 1,
            "name": "Bracket",
            "description": "Angle bracket",
            "part_number": "AB-1",
            "vendor": "McMaster-Carr",
            "unit_price": 10.0,
            "link": "",
            "no_link_reason": "",
        },
        {
            "row": 8,
            "qty": 4,
            "quantity": 4,
            "name": "Washers",
            "description": "M3 washers",
            "part_number": "W-3",
            "vendor": "McMaster-Carr",
            "unit_price": 2.5,
            "link": "",
            "no_link_reason": "",
        },
    ]
    # Total = 2*5 + 1*10 + 4*2.5 = 30.00
    return bom.build_bom_workbook({"item_description": "Hardware", "requester": "Isaac"}, items)


def _make_1row_bom() -> bytes:
    items = [
        {
            "row": 6,
            "qty": 1,
            "quantity": 1,
            "name": "Only Item",
            "description": "Single item",
            "part_number": "P1",
            "vendor": "McMaster-Carr",
            "unit_price": 15.0,
            "link": "https://www.mcmaster.com/P1",
            "no_link_reason": "",
        },
    ]
    return bom.build_bom_workbook({"item_description": "Single", "requester": "Isaac"}, items)


def _make_old_template_bom() -> bytes:
    # 8-column layout matching BOM_OLD_TEMPLATE_HEADERS
    wb = openpyxl.Workbook()
    ws = wb.active
    ws["B2"] = "Order"
    ws["B3"] = "Isaac"
    ws["B4"] = 20.0
    ws.append([])  # 1
    ws.append([])  # 2
    ws.append([])  # 3
    ws.append([])  # 4
    # row 5: headers
    ws.append(list(config.BOM_OLD_TEMPLATE_HEADERS))
    # row 6: item
    ws.append(["Part A", "Description A", "PA-1", "Vendor A", 10.0, 2, "=F6*E6", ""])
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


@pytest.fixture
def world(monkeypatch):
    monkeypatch.setattr(config, "PURCHASING_CHANNEL", "C_PURCHASING")
    roster.add_requester("U_ISAAC", "Isaac")
    files: dict[str, bytes] = {}
    client = MagicMock()
    client.chat_postMessage.return_value = {"ok": True, "ts": "1234.5678"}
    client.files_info.side_effect = lambda file: {"ok": True, "file": {"id": file, "name": f"{file}.xlsx"}}
    monkeypatch.setattr(slack_io, "download_file", lambda f: files[f["id"]])
    monkeypatch.setattr(app, "_run_in_background", lambda fn, *a: fn(*a))
    client.files = files
    return client


def _submit_stage2(client, *, total="30.00", category="Research/Lab Supplies (3105)", file_id="F_BOM"):
    view = _with_bom(
        _make_stage2_view_submission(_sample_stage1_meta(), total_price=total, category=category),
        [{"id": file_id, "name": "order.xlsx"}], True,
    )
    view["id"] = VIEW_ID
    ack = MagicMock()
    app.handle_stage2_submit(ack, {"user": {"id": "U_ISAAC"}, "view": {"id": VIEW_ID}}, client, view)
    return ack


def _check_submission(client, picks=None, new_file_id=None):
    shown = client.views_update.call_args.kwargs["view"]
    files = [{"id": new_file_id, "name": "fixed.xlsx"}] if new_file_id else []
    values = {
        "block_bom_reupload": {"bom_reupload": {"type": "file_input", "files": files}}
    }
    if picks:
        for row, opt_val in picks.items():
            if opt_val is not None:
                values[f"block_no_link_{row}"] = {
                    "no_link_reason": {
                        "type": "radio_buttons",
                        "selected_option": {"value": opt_val},
                    }
                }
            else:
                values[f"block_no_link_{row}"] = {
                    "no_link_reason": {
                        "type": "radio_buttons",
                        "selected_option": None,
                    }
                }
    view = {
        "id": VIEW_ID,
        "private_metadata": shown["private_metadata"],
        "state": {"values": values},
    }
    ack = MagicMock()
    app.handle_bom_check_submit(ack, {"user": {"id": "U_ISAAC"}, "view": {"id": VIEW_ID}}, client, view)
    return ack


def test_check_view_shows_site_names_and_one_input_per_unlinked_row(world):
    world.files["F_BOM"] = _make_3row_bom()
    _submit_stage2(world, total="30.00")

    shown = world.views_update.call_args.kwargs["view"]
    text = _text(shown)

    assert "<https://www.mcmaster.com/91251A540|mcmaster.com>" in text
    assert text.count("no link") >= 2

    block_ids = [b.get("block_id") for b in shown["blocks"]]
    assert "block_no_link_7" in block_ids
    assert "block_no_link_8" in block_ids
    assert "block_no_link_6" not in block_ids

    b7 = next(b for b in shown["blocks"] if b.get("block_id") == "block_no_link_7")
    b8 = next(b for b in shown["blocks"] if b.get("block_id") == "block_no_link_8")
    for block in (b7, b8):
        el = block["element"]
        assert el["type"] == "radio_buttons"
        assert el["action_id"] == "no_link_reason"
        options = el["options"]
        assert len(options) == 2
        assert options[0]["value"] == "no_web_page"
        assert options[0]["text"]["text"] == config.NO_LINK_REASONS[0]
        assert options[1]["value"] == "covered_by_other_row"
        assert options[1]["text"]["text"] == config.NO_LINK_REASONS[1]

    for block in shown["blocks"]:
        if block.get("type") == "section" and "text" in block and "text" in block["text"]:
            assert len(block["text"]["text"]) <= 3000


def test_continue_refused_until_every_reason_is_picked(world):
    world.files["F_BOM"] = _make_3row_bom()
    _submit_stage2(world, total="30.00")

    # Only row 7 picked, row 8 not picked
    ack = _check_submission(world, picks={7: "no_web_page"})
    assert ack.call_args.kwargs["response_action"] == "errors"
    errors = ack.call_args.kwargs["errors"]
    assert errors.get("block_no_link_8") == "Pick why this row has no link."
    world.chat_postMessage.assert_not_called()

    # Picking both continues to posting
    ack = _check_submission(world, picks={7: "no_web_page", 8: "covered_by_other_row"})
    ack.assert_called_once_with()
    posted = [c.kwargs for c in world.chat_postMessage.call_args_list if c.kwargs.get("metadata")]
    assert len(posted) == 1


def test_picked_reasons_reach_the_draft_bom(world):
    world.files["F_BOM"] = _make_3row_bom()
    _submit_stage2(world, total="30.00")

    ack = _check_submission(world, picks={7: "no_web_page", 8: "covered_by_other_row"})
    ack.assert_called_once_with()

    # Find the files_upload_v2 call
    assert world.files_upload_v2.call_count == 1
    draft_bytes = world.files_upload_v2.call_args.kwargs["content"]
    items, problems = bom.read_bom_template(draft_bytes)
    assert problems == []
    assert len(items) == 3

    r6 = next(i for i in items if i["row"] == 6)
    r7 = next(i for i in items if i["row"] == 7)
    r8 = next(i for i in items if i["row"] == 8)

    assert r6["link"] == "https://www.mcmaster.com/91251A540"
    assert r7["no_link_reason"] == "No web page"
    assert r8["no_link_reason"] == "Covered by another row's link"


def test_every_bom_route_reaches_the_reason_inputs(monkeypatch):
    bom_data = _make_3row_bom()
    monkeypatch.setattr(slack_io, "download_file", lambda f: bom_data)
    monkeypatch.setattr(app, "_run_in_background", lambda fn, *a: fn(*a))

    # 1. Edit
    meta_edit = {
        "is_edit": True, "channel": "C_CHAN", "thread_ts": "1000.000", "card_ts": "1000.100",
        "vendor_choice": "McMaster-Carr", "vendor_custom": "", "route": "workday",
    }
    client_edit = _make_client(_sample_modal_card_payload())
    client_edit.files_info.side_effect = lambda file: {"file": {"id": file}}
    body_edit = _make_edit_view_submission(meta_edit, stage2_overrides={"total_price": "30.00"})
    body_edit["view"]["id"] = "V_EDIT"
    body_edit["view"]["state"]["values"]["block_bom"] = {
        "bom": {"type": "file_input", "files": [{"id": "F_EDIT", "name": "edit.xlsx"}]}
    }
    body_edit["view"]["state"]["values"]["block_bom_one_vendor"] = {
        "bom_one_vendor": {"selected_options": [{"value": "one_vendor"}]}
    }
    ack_edit = MagicMock()
    app.handle_edit_submit(ack_edit, body_edit, client_edit, body_edit["view"])
    shown_edit = client_edit.views_update.call_args.kwargs["view"]
    assert "block_no_link_7" in [b.get("block_id") for b in shown_edit["blocks"]]

    # 2. Add items
    card = _sample_epif_card_payload(total_price=30.00)
    client_items = MagicMock()
    client_items.conversations_replies.return_value = {"ok": True, "messages": [_make_thread_message(card)]}
    client_items.files_info.side_effect = lambda file: {"file": {"id": file}}
    ack_items = MagicMock()
    app.handle_items_modal_submit(ack_items, {"user": {"id": "U_ISAAC"}}, client_items, _items_view([{"id": "F_ITEMS", "name": "items.xlsx"}]))
    shown_items = client_items.views_update.call_args.kwargs["view"]
    assert "block_no_link_7" in [b.get("block_id") for b in shown_items["blocks"]]

    # 3. Replace BOM
    card_approved = {
        "state": "approved", "assignee_id": "U_BUYER", "assignee": "Buyer",
        "requester": "Isaac", "user_id": "U_ISAAC", "channel": "C_PURCHASING",
        "thread_ts": "100.0", "card_ts": "100.2", "bom_file": "BOM.xlsx",
        "parsed": {"total_price": 30.00, "item_description": "Stuff"},
    }
    card_msg = {
        "ts": "100.2",
        "thread_ts": "100.0",
        "blocks": blocks.build_request_blocks("approved", card_approved),
        "metadata": {"event_type": "purchase_request", "event_payload": card_approved},
    }
    client_replace = MagicMock()
    client_replace.conversations_replies.return_value = {"messages": [card_msg]}
    client_replace.files_info.side_effect = lambda file: {"file": {"id": file}}
    ack_replace = MagicMock()
    app.handle_replace_bom_action(MagicMock(), _pointer_body(client_replace, "100.2", "U_ISAAC"), MagicMock(), client_replace)
    replace_modal = client_replace.views_open.call_args.kwargs["view"]
    replace_view_id = "V_REPLACE"
    replace_modal["id"] = replace_view_id
    replace_modal["state"] = {"values": {"block_bom": {"bom": {"files": [{"id": "F_REP", "name": "rep.xlsx"}]}}}}
    app.handle_replace_bom_submit(ack_replace, {"user": {"id": "U_ISAAC"}, "view": {"id": replace_view_id}}, client_replace, replace_modal)
    shown_replace = client_replace.views_update.call_args.kwargs["view"]
    assert "block_no_link_7" in [b.get("block_id") for b in shown_replace["blocks"]]

    # 4. Workday details
    card_wd = {
        "state": "waiting_for_details", "assignee_id": "U_A", "assignee": "A",
        "approver": "U_C", "requester": "Isaac", "user_id": "U_ISAAC",
    }
    monkeypatch.setattr(slack_io, "get_card_payload", lambda *a, **k: card_wd)
    monkeypatch.setattr(slack_io, "resolve_requester", lambda *a, **k: "Isaac")
    monkeypatch.setattr(app.validators, "validate", lambda *a, **k: [])
    client_wd = MagicMock()
    client_wd.files_info.side_effect = lambda file: {"file": {"id": file}}
    view_wd = {
        "id": "V_WD",
        "private_metadata": json.dumps({"channel_id": "C123", "thread_ts": "T1", "card_ts": "T1"}),
        "state": {"values": {
            "block_vendor": {"vendor": {"selected_option": {"value": "McMaster-Carr"}}},
            "block_item_description": {"item_description": {"value": "Hardware"}},
            "block_total_price": {"total_price": {"value": "30.00"}},
            "block_purpose": {"purpose": {"value": "Research"}},
            "block_bom": {"bom": {"files": [{"id": "F_WD", "name": "wd.xlsx"}]}},
            "block_bom_one_vendor": {"bom_one_vendor": {"selected_options": [{"value": "one_vendor"}]}},
        }},
    }
    ack_wd = MagicMock()
    app.handle_workday_details_submit(ack_wd, {"user": {"id": "U_ISAAC"}, "view": {"id": "V_WD"}}, client_wd, view_wd)
    shown_wd = client_wd.views_update.call_args.kwargs["view"]
    assert "block_no_link_7" in [b.get("block_id") for b in shown_wd["blocks"]]


def test_old_template_and_one_row_boms_are_refused(world):
    # Old template upload
    world.files["F_OLD"] = _make_old_template_bom()
    _submit_stage2(world, total="20.00", file_id="F_OLD")
    shown_old = world.views_update.call_args.kwargs["view"]
    text_old = _text(shown_old)
    assert "This is the old BOM template, which has no Link column" in text_old
    assert any(b.get("block_id") == "block_bom_template" for b in shown_old["blocks"])

    # Clean one-row BOM upload
    world.files["F_ONE"] = _make_1row_bom()
    _submit_stage2(world, total="15.00", file_id="F_ONE")
    shown_one = world.views_update.call_args.kwargs["view"]
    text_one = _text(shown_one)
    assert "This BOM has one item. Leave the BOM field empty and give that item's link on the form instead." in text_one

    # Continue is refused
    ack = _check_submission(world)
    assert ack.call_args.kwargs["response_action"] == "errors"
    assert "This BOM has one item." in ack.call_args.kwargs["errors"]["block_bom_reupload"]
    world.chat_postMessage.assert_not_called()
