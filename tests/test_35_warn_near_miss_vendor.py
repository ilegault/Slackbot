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
        # stage 2 view should be present
        assert "view" in ack_kwargs

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
