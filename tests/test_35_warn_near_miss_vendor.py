import json
from unittest.mock import MagicMock

from src import app, config, interview


def test_check_near_miss_vendor_exact_match():
    listed = {"Fisher Scientific", "Dell", "Apple"}
    assert interview.check_near_miss_vendor("Dell", listed) == "Dell"

def test_check_near_miss_vendor_case_and_punctuation():
    listed = {"Fisher Scientific", "Dell", "Apple"}
    assert interview.check_near_miss_vendor("fisher scientific", listed) == "Fisher Scientific"
    assert interview.check_near_miss_vendor("Fisher-Scientific!", listed) == "Fisher Scientific"

def test_check_near_miss_vendor_suffixes():
    listed = {"Fisher Scientific", "Dell", "Apple"}
    assert interview.check_near_miss_vendor("Fisher Scientific, Inc.", listed) == "Fisher Scientific"
    assert interview.check_near_miss_vendor("Dell LLC", listed) == "Dell"
    assert interview.check_near_miss_vendor("Apple Ltd", listed) == "Apple"

def test_check_near_miss_vendor_typo_ratio():
    listed = {"Fisher Scientific", "Dell", "Apple"}
    # 0.96 ratio
    assert interview.check_near_miss_vendor("Fisher Scientfic", listed) == "Fisher Scientific"

def test_check_near_miss_vendor_no_match():
    listed = {"Fisher Scientific", "Dell", "Apple"}
    assert interview.check_near_miss_vendor("Winford", listed) is None
    assert interview.check_near_miss_vendor("Amazon", listed) is None
    assert interview.check_near_miss_vendor("Fisher", listed) is None  # Too short, ratio too low


def test_handle_stage1_submit_near_miss_warns_once(monkeypatch):
    """
    Scenario tests through the real Screen 1 view handler:
    'fisher scientific', 'Fisher Scientific, Inc.' and 'Fisher Scientfic' are each warned once, then pass on resubmit.
    'Winford' is never warned.
    """
    monkeypatch.setattr(config, "WORKDAY_VENDORS", {"Fisher Scientific"})
    monkeypatch.setattr(interview, "get_available_vendors", lambda: {"Fisher Scientific"})

    cases = ["fisher scientific", "Fisher Scientific, Inc.", "Fisher Scientfic"]

    for typed_name in cases:
        ack = MagicMock()
        client = MagicMock()
        body = {"user": {"id": "U123"}}

        # Initial submission
        view = {
            "id": "V123",
            "hash": "hash123",
            "state": {
                "values": {
                    "block_vendor": {"vendor_select": {"selected_option": {"value": config.VENDOR_OTHER_OPTION}}},
                    "block_vendor_custom": {"vendor_custom": {"value": typed_name}}
                }
            },
            "private_metadata": json.dumps({"user_id": "U123"})
        }

        app.handle_stage1_submit(ack, body, client, view)

        # We expect a view update to change private metadata and add the error
        client.views_update.assert_not_called()
        ack.assert_called_once()
        ack_kwargs = ack.call_args[1]
        assert ack_kwargs["response_action"] == "update"
        updated_view = ack_kwargs["view"]

        # Metadata should contain warned_vendor
        new_meta = json.loads(updated_view["private_metadata"])
        assert new_meta["warned_vendor"] == typed_name

        # Warning block should be present
        blocks = updated_view["blocks"]
        assert blocks[0]["block_id"] == "block_near_miss_warning"
        assert "Did you mean *Fisher Scientific*?" in blocks[0]["elements"][0]["text"]

        # Second submission (resubmit)
        ack.reset_mock()
        client.reset_mock()

        view_resubmit = {
            "id": "V123",
            "hash": "hash123",
            "state": {
                "values": {
                    "block_vendor": {"vendor_select": {"selected_option": {"value": config.VENDOR_OTHER_OPTION}}},
                    "block_vendor_custom": {"vendor_custom": {"value": typed_name}}
                }
            },
            # Simulator: provide the updated metadata from previous call
            "private_metadata": json.dumps({"user_id": "U123", "warned_vendor": typed_name})
        }

        app.handle_stage1_submit(ack, body, client, view_resubmit)

        # Should not warn again, should proceed to stage 2
        client.views_update.assert_not_called()
        ack.assert_called_once()
        ack_kwargs = ack.call_args[1]
        assert ack_kwargs["response_action"] == "update"
        # stage 2 view should be present, not the warning again
        assert "view" in ack_kwargs
        assert ack_kwargs["view"]["callback_id"] == config.STAGE2_CALLBACK_ID

def test_handle_stage1_submit_no_near_miss_passes(monkeypatch):
    monkeypatch.setattr(config, "WORKDAY_VENDORS", {"Fisher Scientific"})
    monkeypatch.setattr(interview, "get_available_vendors", lambda: {"Fisher Scientific"})

    ack = MagicMock()
    client = MagicMock()
    body = {"user": {"id": "U123"}}

    view = {
        "id": "V123",
        "hash": "hash123",
        "state": {
            "values": {
                "block_vendor": {"vendor_select": {"selected_option": {"value": config.VENDOR_OTHER_OPTION}}},
                "block_vendor_custom": {"vendor_custom": {"value": "Winford"}}
            }
        },
        "private_metadata": json.dumps({"user_id": "U123"})
    }

    app.handle_stage1_submit(ack, body, client, view)

    client.views_update.assert_not_called()
    ack.assert_called_once()
    ack_kwargs = ack.call_args[1]
    assert ack_kwargs["response_action"] == "update"
    assert ack_kwargs["view"]["callback_id"] == config.STAGE2_CALLBACK_ID

def test_handle_stage1_submit_different_near_miss_warns_anew(monkeypatch):
    """If they were warned about A, but then type B which is also a near miss, warn again."""
    monkeypatch.setattr(config, "WORKDAY_VENDORS", {"Fisher Scientific", "Dell"})
    monkeypatch.setattr(interview, "get_available_vendors", lambda: {"Fisher Scientific", "Dell"})

    ack = MagicMock()
    client = MagicMock()
    body = {"user": {"id": "U123"}}

    view = {
        "id": "V123",
        "hash": "hash123",
        "state": {
            "values": {
                "block_vendor": {"vendor_select": {"selected_option": {"value": config.VENDOR_OTHER_OPTION}}},
                "block_vendor_custom": {"vendor_custom": {"value": "dell inc"}}
            }
        },
        "private_metadata": json.dumps({"user_id": "U123", "warned_vendor": "fisher scientific"})
    }

    app.handle_stage1_submit(ack, body, client, view)

    # Should warn again because warned_vendor is different
    client.views_update.assert_not_called()
    ack.assert_called_once()
    ack_kwargs = ack.call_args[1]
    assert ack_kwargs["response_action"] == "update"
    updated_view = ack_kwargs["view"]

    blocks = updated_view["blocks"]
    assert blocks[0]["block_id"] == "block_near_miss_warning"
    assert "Did you mean *Dell*?" in blocks[0]["elements"][0]["text"]


# --- Round-trip scenarios through the real Screen 1 view --------------------
# These start from the view the bot actually builds, submit it through the real
# handler, and feed the view the bot sends back into the next submit, the way
# Slack does. "Proceeds" is asserted as what the requester would see next: the
# Screen 2 view on the EPIF path, with no warning on it.

from src import blocks  # noqa: E402

LISTED = {"Fisher Scientific", "Dell"}


def _submit(view: dict, typed_name: str) -> dict:
    """Submit `view` with None of these — this will be an EPIF order + `typed_name`; return the ack kwargs."""
    submitted = dict(view)
    submitted["id"] = "V123"
    submitted["hash"] = "hash123"
    submitted["state"] = {
        "values": {
            "block_vendor": {"vendor_select": {"selected_option": {"value": config.VENDOR_OTHER_OPTION}}},
            "block_vendor_custom": {"vendor_custom": {"value": typed_name}},
        }
    }
    ack = MagicMock()
    app.handle_stage1_submit(ack, {"user": {"id": "U123"}}, MagicMock(), submitted)
    ack.assert_called_once()
    return ack.call_args[1]


def _warnings(view: dict) -> list[dict]:
    return [b for b in view.get("blocks", []) if b.get("block_id") == "block_near_miss_warning"]


def _assert_proceeded_on_epif_path(ack_kwargs: dict, typed_name: str) -> None:
    view = ack_kwargs["view"]
    assert ack_kwargs["response_action"] == "update"
    assert view["callback_id"] == config.STAGE2_CALLBACK_ID
    meta = json.loads(view["private_metadata"])
    assert meta["route"] == "epif"
    assert meta["vendor_custom"] == typed_name
    assert _warnings(view) == []


def _fresh_stage1_view() -> dict:
    return blocks.build_stage1_view(resolved_name="Requester", user_id="U123")


def test_round_trip_warns_once_then_proceeds_on_epif_path(monkeypatch):
    monkeypatch.setattr(interview, "get_available_vendors", lambda: LISTED)

    for typed_name in ["fisher scientific", "Fisher Scientific, Inc.", "Fisher Scientfic"]:
        first = _submit(_fresh_stage1_view(), typed_name)
        warned_view = first["view"]
        assert warned_view["callback_id"] == config.STAGE1_CALLBACK_ID  # still on Screen 1
        assert len(_warnings(warned_view)) == 1

        second = _submit(warned_view, typed_name)
        _assert_proceeded_on_epif_path(second, typed_name)


def test_unlisted_vendor_proceeds_immediately_without_a_warning(monkeypatch):
    monkeypatch.setattr(interview, "get_available_vendors", lambda: LISTED)

    _assert_proceeded_on_epif_path(_submit(_fresh_stage1_view(), "Winford"), "Winford")


def test_warning_sits_directly_under_the_vendor_name_field(monkeypatch):
    monkeypatch.setattr(interview, "get_available_vendors", lambda: LISTED)

    view = _submit(_fresh_stage1_view(), "fisher scientific")["view"]
    ids = [b.get("block_id") for b in view["blocks"]]
    assert ids.index("block_near_miss_warning") == ids.index("block_vendor_custom") + 1
    text = _warnings(view)[0]["elements"][0]["text"]
    assert "Did you mean *Fisher Scientific*?" in text
    assert "Submit again to keep this as an EPIF order." in text


def test_changing_to_another_near_miss_replaces_the_warning(monkeypatch):
    monkeypatch.setattr(interview, "get_available_vendors", lambda: LISTED)

    warned_about_fisher = _submit(_fresh_stage1_view(), "fisher scientific")["view"]
    warned_about_dell = _submit(warned_about_fisher, "dell inc")["view"]

    warnings = _warnings(warned_about_dell)
    assert len(warnings) == 1
    text = warnings[0]["elements"][0]["text"]
    assert "Did you mean *Dell*?" in text
    assert "Fisher" not in text
    assert json.loads(warned_about_dell["private_metadata"])["warned_vendor"] == "dell inc"

    # ...and resubmitting the new name now goes through.
    _assert_proceeded_on_epif_path(_submit(warned_about_dell, "dell inc"), "dell inc")
