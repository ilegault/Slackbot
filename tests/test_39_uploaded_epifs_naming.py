import os
import sys
from unittest.mock import MagicMock, patch

import pytest

_CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(_CURRENT_DIR) if os.path.basename(_CURRENT_DIR) == "tests" else _CURRENT_DIR
SRC_DIR = os.path.join(PROJECT_ROOT, "src")
for p in (PROJECT_ROOT, SRC_DIR):
    if p not in sys.path:
        sys.path.insert(0, p)

from src import config, lifecycle


@pytest.fixture
def mock_log_writer():
    with patch("src.lifecycle.log_writer", autospec=True) as mock:
        mock.build_row.return_value = ["row", "data"]
        from src.log_writer import epif_archive_name, save_epif
        mock.epif_archive_name.side_effect = epif_archive_name
        mock.save_epif.side_effect = save_epif
        mock.append_row.return_value = 17
        mock.get_row_info.return_value = {}
        yield mock

def test_uploaded_epif_uses_naming_rule_and_posts_correct_message(mock_log_writer, tmp_path):
    """
    AC 1: In lifecycle.finalize_purchase_request.write_action, the uploaded PDF is saved
    under log_writer.epif_archive_name(...) computed from the parsed vendor, total and
    project ID.
    AC 2: The 'Saved EPIF to ...' thread line names the archived file.
    """
    config.EPIFS_DIR = str(tmp_path / "EPIFs")
    os.makedirs(config.EPIFS_DIR, exist_ok=True)

    client = MagicMock()
    client.conversations_replies.return_value = {"messages": []}
    client.chat_postMessage.return_value = {"ts": "message_ts"}

    with patch("src.lifecycle.queue_worker.submit_write_task") as mock_submit:
        def submit_side_effect(action_fn, **kw):
            res = action_fn()
            kw["success_callback"](res)
        mock_submit.side_effect = submit_side_effect

        with patch("src.lifecycle.slack_io.find_card_in_thread", return_value=(None, None, None, None)):
            with patch("src.lifecycle.blocks.build_request_blocks", return_value=[]):
                say = MagicMock()
                parsed = {
                    "vendor": "Commonlands",
                    "total_price": 349.0,
                    "project_id": "PG000025831",
                    "item_description": "Lens",
                    "category": "Supplies",
                    "purpose": "Research",
                    "vendor_contact_name": "Sales",
                    "vendor_contact_email": "sales@ruland.com",
                    "date_of_purchase": "09/22/2026",
                    "fund": "133",
                    "delivery_room": "ERB 212",
                    "payment_method": "EPIF",
                    "name_of_system": "",
                    "asset_id": "",
                    "link": "https://commonlands.com"
                }

                with patch("src.validators.validate", return_value=[]):
                    lifecycle.finalize_purchase_request(
                        client=client,
                        say=say,
                        channel="C_CHANNEL",
                        thread_ts="1234.56",
                        event_ts="1234.60",
                        parsed=parsed,
                        requester="Charlie H.",
                        notify_target="U_NOTIFY",
                        pdf_bytes=b"fake-pdf-content",
                        file_name="my epif final v2.pdf",
                        assignee_id="U_ASSIGNEE",
                        assignee_name="AssigneeName"
                    )

    expected_archive_name = "Commonlands_EPIF_$349.00_PG000025831.pdf"
    assert os.path.exists(os.path.join(config.EPIFS_DIR, expected_archive_name))

    # AC 2: A test asserts the exact name in the thread line
    say_text = say.call_args[1]["text"]
    assert expected_archive_name in say_text, f"Expected {expected_archive_name} in message text but got {say_text}"
    assert f"Saved EPIF to `{expected_archive_name}`" in say_text


def test_second_identical_upload_uses_incremented_name_and_keeps_bytes(mock_log_writer, tmp_path):
    """
    AC 3: A second identical upload is archived as `..._2.pdf`, and the first file's bytes
    are unchanged.
    """
    config.EPIFS_DIR = str(tmp_path / "EPIFs")
    os.makedirs(config.EPIFS_DIR, exist_ok=True)

    client = MagicMock()
    client.conversations_replies.return_value = {"messages": []}

    parsed = {
        "vendor": "Commonlands",
        "total_price": 349.0,
        "project_id": "PG000025831",
        "item_description": "Lens",
        "category": "Supplies",
        "purpose": "Research",
        "vendor_contact_name": "Sales",
        "vendor_contact_email": "sales@ruland.com",
        "date_of_purchase": "09/22/2026",
        "fund": "133",
        "delivery_room": "ERB 212",
        "payment_method": "EPIF",
        "name_of_system": "",
        "asset_id": "",
        "link": "https://commonlands.com"
    }

    say1 = MagicMock()
    with patch("src.lifecycle.queue_worker.submit_write_task") as mock_submit:
        def submit_side_effect(action_fn, **kw):
            res = action_fn()
            kw["success_callback"](res)
        mock_submit.side_effect = submit_side_effect
        with patch("src.lifecycle.slack_io.find_card_in_thread", return_value=(None, None, None, None)):
            with patch("src.lifecycle.blocks.build_request_blocks", return_value=[]):
                with patch("src.validators.validate", return_value=[]):
                    lifecycle.finalize_purchase_request(
                        client=client,
                        say=say1,
                        channel="C_CHANNEL",
                        thread_ts="111.11",
                        event_ts="111.12",
                        parsed=parsed,
                        requester="Charlie H.",
                        notify_target="U_NOTIFY",
                        pdf_bytes=b"first-upload",
                        file_name="my epif final v2.pdf",
                        assignee_id="U_ASSIGNEE",
                        assignee_name="AssigneeName"
                    )

    expected_file_1 = os.path.join(config.EPIFS_DIR, "Commonlands_EPIF_$349.00_PG000025831.pdf")
    assert os.path.exists(expected_file_1)
    with open(expected_file_1, "rb") as f:
        assert f.read() == b"first-upload"

    say2 = MagicMock()
    with patch("src.lifecycle.queue_worker.submit_write_task") as mock_submit:
        mock_submit.side_effect = submit_side_effect
        with patch("src.lifecycle.slack_io.find_card_in_thread", return_value=(None, None, None, None)):
            with patch("src.lifecycle.blocks.build_request_blocks", return_value=[]):
                with patch("src.validators.validate", return_value=[]):
                    lifecycle.finalize_purchase_request(
                        client=client,
                        say=say2,
                        channel="C_CHANNEL",
                        thread_ts="222.22",
                        event_ts="222.23",
                        parsed=parsed,
                        requester="Charlie H.",
                        notify_target="U_NOTIFY",
                        pdf_bytes=b"second-upload",
                        file_name="my epif final v2.pdf",
                        assignee_id="U_ASSIGNEE",
                        assignee_name="AssigneeName"
                    )

    expected_file_2 = os.path.join(config.EPIFS_DIR, "Commonlands_EPIF_$349.00_PG000025831_2.pdf")
    assert os.path.exists(expected_file_2)

    with open(expected_file_2, "rb") as f:
        assert f.read() == b"second-upload"

    with open(expected_file_1, "rb") as f:
        assert f.read() == b"first-upload", "First file bytes were unchanged"


def test_cancel_moves_epif_to_cancelled_directory(tmp_path):
    """
    AC 4: Cancel still moves the archived EPIF to EPIFs/Cancelled/ under its archived name;
    a test cancels after approval and asserts the file is there and gone from EPIFs/.
    """
    config.EPIFS_DIR = str(tmp_path / "EPIFs")
    os.makedirs(config.EPIFS_DIR, exist_ok=True)

    epif_filename = "Commonlands_EPIF_$349.00_PRJ123.pdf"
    original_path = os.path.join(config.EPIFS_DIR, epif_filename)

    with open(original_path, "wb") as f:
        f.write(b"fake-pdf-content")

    req_data = {
        "epif_file": epif_filename,
        "vendor": "Commonlands",
        "total_price": 349.0
    }

    client = MagicMock()
    # Mock row found
    with patch("src.lifecycle.slack_io.find_all_rows_in_thread", return_value=[1]):
        with patch("src.lifecycle.queue_worker.submit_write_task") as mock_submit:
            def side_effect(action_fn, **kw):
                res = action_fn()
                kw["success_callback"](res)
            mock_submit.side_effect = side_effect
            with patch("src.lifecycle.log_writer.blank_row"):
                with patch("src.lifecycle.slack_io.find_card_in_thread", return_value=(None, None, None, None)):
                    with patch("src.lifecycle.blocks.build_request_blocks", return_value=[]):
                        with patch("src.slack_io.resolve_requester", return_value="Charlie"):
                             say = MagicMock()
                             lifecycle.handle_cancel(
                                 client=client,
                                 say=say,
                                 channel="C_CHANNEL",
                                 thread_ts="1234.56",
                                 msg_ts="1234.60",
                                 user_id="U_USER",
                                 req_data=req_data,
                                 state="approved",
                                 history=[]
                             )

    # Check original is gone
    assert not os.path.exists(original_path), "File should be moved out of live EPIFs/ folder"

    # Check it is in Cancelled/
    cancelled_path = os.path.join(config.EPIFS_DIR, "Cancelled", epif_filename)
    assert os.path.exists(cancelled_path), "File should be moved into Cancelled/ subfolder"
