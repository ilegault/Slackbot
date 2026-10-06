"""Tests for Ticket 98: The buyer picker lists only buyers.

Covers ADR 0014 decisions 1–5:
1. The buyer picker is a static_select dropdown populated from buyers with a roster name.
2. The list is filled when the card is drawn.
3. The current buyer is pre-selected only if they are still in the options.
4. No named buyers -> no picker element on the card.
5. Cards already in Slack keep working (both selected_option and legacy selected_user payloads).
"""
import json
from unittest.mock import MagicMock

import pytest

from src import app, blocks, config, roster


@pytest.fixture
def clean_roster(tmp_path, monkeypatch):
    """Ensure a fresh isolated roster for each test matching ticket 98 specification."""
    roster_file = str(tmp_path / "roster.json")
    monkeypatch.setattr(roster, "ROSTER_PATH", roster_file)
    roster._DATA = None
    data = {
        "admins": ["U_ADMIN"],
        "approvers": ["U_CHARLIE"],
        "buyers": ["U_BUYER_C", "U_BUYER_A", "U_BUYER_B", "U_BUYER_NONAME"],
        "requesters": {
            "U_ADMIN": "Isaac",
            "U_CHARLIE": "Charlie H.",
            "U_BUYER_C": "carol",
            "U_BUYER_A": "Alice",
            "U_BUYER_B": "Bob",
            "U_REQ": "Alex",
        },
        "vendors": [],
    }
    with open(roster_file, "w", encoding="utf-8") as f:
        json.dump(data, f)
    yield


def _sample_request():
    return {
        "item_description": "Laser diode",
        "vendor": "Thorlabs",
        "total_price": 120.0,
        "requester": "Alex",
        "user_id": "U_REQ",
        "thread_ts": "1000.0",
    }


def _make_picker_body_option(user_id: str, selected_option_value: str, req_data: dict, history: list | None = None):
    """Build the body for a req_assign_select action click using static_select selected_option."""
    btn_val = json.dumps({
        "state": "approved",
        "request": req_data,
        "history": history or [],
    })
    return {
        "user": {"id": user_id},
        "channel": {"id": "C123"},
        "message": {
            "ts": "1000.1",
            "blocks": [
                {"type": "section", "text": {"type": "mrkdwn", "text": "Card"}},
                {
                    "type": "actions",
                    "elements": [
                        {
                            "type": "button",
                            "action_id": "req_processed",
                            "value": btn_val,
                        },
                        {
                            "type": "button",
                            "action_id": "req_cancel",
                            "value": btn_val,
                        },
                    ],
                },
            ],
        },
        "container": {"thread_ts": "1000.0"},
        "actions": [
            {
                "action_id": config.ACTION_REQ_ASSIGN_SELECT,
                "selected_option": {
                    "value": selected_option_value,
                    "text": {"type": "plain_text", "text": "carol"},
                },
            }
        ],
    }


# Criterion 1: Pure function
def test_pure_function_buyer_picker_options():
    """buyer_picker_options filters to non-empty string names, dedupes IDs, sorts by name.casefold()."""
    buyer_ids = ["U_C", "U_A", "U_A", "U_X", "U_BLANK"]
    names = {"U_C": "carol", "U_A": "Alice", "U_BLANK": "  ", "U_Q": "Quinn"}
    expected = [
        {"text": {"type": "plain_text", "text": "Alice"}, "value": "U_A"},
        {"text": {"type": "plain_text", "text": "carol"}, "value": "U_C"},
    ]
    assert blocks.buyer_picker_options(buyer_ids, names) == expected
    assert blocks.buyer_picker_options([], names) == []


# Criterion 2: Only buyers on all three cards
def test_only_buyers_on_all_three_cards(clean_roster):
    """The picker on posted, approved, and DM approved cards is static_select listing only named buyers."""
    sample_req = _sample_request()

    cards = [
        ("posted", blocks.build_request_blocks("posted", sample_req), config.ACTION_REQ_ASSIGN_SELECT),
        ("approved", blocks.build_request_blocks("approved", sample_req), config.ACTION_REQ_ASSIGN_SELECT),
        (
            "dm_approved",
            blocks.build_dm_card_blocks(
                state="approved",
                request=sample_req,
                thread_channel="C123",
                thread_ts="1000.0",
                card_ts="1000.1",
            ),
            config.ACTION_DM_REQ_ASSIGN_SELECT,
        ),
    ]

    expected_values = ["U_BUYER_A", "U_BUYER_B", "U_BUYER_C"]

    for card_name, card_blocks, action_id in cards:
        # No users_select anywhere in the card
        all_elements = [el for b in card_blocks if b.get("type") == "actions" for el in b.get("elements", [])]
        assert not any(el.get("type") == "users_select" for el in all_elements), (
            f"Found unexpected users_select in {card_name}"
        )

        # Picker element found by action_id
        pickers = [el for el in all_elements if el.get("action_id") == action_id]
        assert len(pickers) == 1, f"Expected exactly 1 picker in {card_name}"
        picker = pickers[0]

        assert picker.get("type") == "static_select", f"Picker in {card_name} must be static_select"
        option_values = [opt["value"] for opt in picker.get("options", [])]
        assert option_values == expected_values, f"Options mismatch in {card_name}"
        assert "U_CHARLIE" not in option_values
        assert "U_REQ" not in option_values
        assert "U_BUYER_NONAME" not in option_values


# Criterion 3: Pre-selection
def test_pre_selection(clean_roster):
    """Pre-selection sets initial_option when assignee is in options, omitted otherwise."""
    req_b = {**_sample_request(), "assignee_id": "U_BUYER_B"}
    req_gone = {**_sample_request(), "assignee_id": "U_GONE"}
    req_none = {**_sample_request()}

    cards_to_test = [
        (
            "posted",
            lambda r: blocks.build_request_blocks("posted", r),
            config.ACTION_REQ_ASSIGN_SELECT,
            "Assign a buyer (optional)",
        ),
        (
            "approved",
            lambda r: blocks.build_request_blocks("approved", r),
            config.ACTION_REQ_ASSIGN_SELECT,
            "Assign a buyer",
        ),
        (
            "dm_approved",
            lambda r: blocks.build_dm_card_blocks("approved", r, thread_channel="C123", thread_ts="1000.0", card_ts="1000.1"),
            config.ACTION_DM_REQ_ASSIGN_SELECT,
            "Assign a buyer",
        ),
    ]

    for card_name, build_fn, action_id, placeholder_text in cards_to_test:
        # Pre-selected buyer
        card_b = build_fn(req_b)
        elements_b = [el for b in card_b if b.get("type") == "actions" for el in b.get("elements", [])]
        picker_b = next(el for el in elements_b if el.get("action_id") == action_id)
        assert picker_b.get("initial_option", {}).get("value") == "U_BUYER_B"
        matching_opt = next(opt for opt in picker_b["options"] if opt["value"] == "U_BUYER_B")
        assert picker_b["initial_option"] == matching_opt

        # Assignee not a buyer (U_GONE)
        card_gone = build_fn(req_gone)
        elements_gone = [el for b in card_gone if b.get("type") == "actions" for el in b.get("elements", [])]
        picker_gone = next(el for el in elements_gone if el.get("action_id") == action_id)
        assert "initial_option" not in picker_gone
        assert picker_gone.get("placeholder", {}).get("text") == placeholder_text

        # No assignee
        card_none = build_fn(req_none)
        elements_none = [el for b in card_none if b.get("type") == "actions" for el in b.get("elements", [])]
        picker_none = next(el for el in elements_none if el.get("action_id") == action_id)
        assert "initial_option" not in picker_none
        assert picker_none.get("placeholder", {}).get("text") == placeholder_text


# Criterion 4: No named buyers -> no picker
def test_no_named_buyers_no_picker(clean_roster):
    """When roster has no buyers, no picker is rendered, but action buttons remain."""
    roster_data = roster.load_roster()
    roster_data["buyers"] = []
    roster.save_roster(roster_data)

    sample_req = _sample_request()

    posted_blks = blocks.build_request_blocks("posted", sample_req)
    approved_blks = blocks.build_request_blocks("approved", sample_req)
    dm_blks = blocks.build_dm_card_blocks("approved", sample_req, thread_channel="C123", thread_ts="1000.0", card_ts="1000.1")

    for card_name, card_blocks, picker_id, expected_btn_id in [
        ("posted", posted_blks, config.ACTION_REQ_ASSIGN_SELECT, "req_approve"),
        ("approved", approved_blks, config.ACTION_REQ_ASSIGN_SELECT, "req_processed"),
        ("dm_approved", dm_blks, config.ACTION_DM_REQ_ASSIGN_SELECT, config.ACTION_DM_REQ_PROCESSED),
    ]:
        all_elements = [el for b in card_blocks if b.get("type") == "actions" for el in b.get("elements", [])]
        assert not any(el.get("action_id") == picker_id for el in all_elements), (
            f"Picker {picker_id} should not be present in {card_name} when no buyers exist"
        )
        assert any(el.get("action_id") == expected_btn_id for el in all_elements), (
            f"Expected button {expected_btn_id} missing in {card_name}"
        )


# Criterion 5: Both payload shapes assign
def test_both_payload_shapes_assign(clean_roster):
    """app._picked_buyer_id handles selected_option and selected_user; handle_req_assign_select_action updates card."""
    # Test _picked_buyer_id helper
    assert app._picked_buyer_id({"selected_user": "U_X"}) == "U_X"
    assert app._picked_buyer_id({}) is None
    assert app._picked_buyer_id({"selected_option": {"value": "U_BUYER_C"}}) == "U_BUYER_C"
    # selected_option takes precedence when present
    assert app._picked_buyer_id({"selected_option": {"value": "U_BUYER_C"}, "selected_user": "U_X"}) == "U_BUYER_C"

    # Test handle_req_assign_select_action with static_select selected_option payload
    ack = MagicMock()
    respond = MagicMock()
    client = MagicMock()
    client.conversations_replies.return_value = {"messages": []}

    req_data = _sample_request()
    body_option = _make_picker_body_option("U_BUYER_A", "U_BUYER_C", req_data)

    app.handle_req_assign_select_action(ack, body_option, respond, client)

    ack.assert_called_once()
    assert client.chat_update.call_count >= 1
    found_assignee_opt = False
    for c in client.chat_update.call_args_list:
        for blk in c[1].get("blocks", []):
            for el in blk.get("elements", []):
                if el.get("type") == "button" and el.get("value"):
                    val = json.loads(el["value"])
                    if val.get("request", {}).get("assignee_id") == "U_BUYER_C":
                        found_assignee_opt = True
    assert found_assignee_opt, "chat_update does not carry assignee_id=U_BUYER_C for selected_option"

    # Verify legacy selected_user payload works identically
    client.reset_mock()
    body_user = _make_picker_body_option("U_BUYER_A", "U_BUYER_B", req_data)
    body_user["actions"] = [{"action_id": config.ACTION_REQ_ASSIGN_SELECT, "selected_user": "U_BUYER_B"}]
    app.handle_req_assign_select_action(ack, body_user, respond, client)
    found_assignee_user = False
    for c in client.chat_update.call_args_list:
        for blk in c[1].get("blocks", []):
            for el in blk.get("elements", []):
                if el.get("type") == "button" and el.get("value"):
                    val = json.loads(el["value"])
                    if val.get("request", {}).get("assignee_id") == "U_BUYER_B":
                        found_assignee_user = True
    assert found_assignee_user, "chat_update does not carry assignee_id=U_BUYER_B for legacy selected_user"
