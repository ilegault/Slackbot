"""Tests for Ticket 31: Cancel moves the BOM out of the live folder.

Acceptance criteria:
- Cancelling an approved itemised request blanks its rows and moves its spreadsheet
  into Cancelled/ inside the BOMs folder, keeping the file name.
- The live BOMs folder no longer holds that file.
- Cancelling a request with no spreadsheet behaves exactly as it does today.
- A spreadsheet that is already missing leaves the cancellation successful, the rows
  blanked, and a logged warning.
- Cancel is still refused after a request is processed, with no file moved — asserted
  on the absence.
- The existing decline/cancel tests still pass untouched.
"""
import logging
import os
from unittest.mock import MagicMock, patch

from src import config, lifecycle, log_writer

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_bom_file(boms_dir: str, filename: str) -> str:
    """Create a dummy BOM file in boms_dir; return its full path."""
    path = os.path.join(boms_dir, filename)
    with open(path, "wb") as fh:
        fh.write(b"dummy bom content")
    return path


def _make_client_with_no_rows() -> MagicMock:
    client = MagicMock()
    client.conversations_replies.return_value = {"messages": []}
    return client


def _make_client_with_row(row: int) -> MagicMock:
    client = MagicMock()
    client.conversations_replies.return_value = {
        "messages": [{"text": f"Logged to row {row}: item — $10.00"}]
    }
    return client


def _run_cancel(
    client,
    req_data: dict,
    state: str = "approved",
    thread_ts: str = "100.0",
    msg_ts: str = "100.10",
    user_id: str = "U_CHARLIE",
):
    """Run handle_cancel with queue_worker executing synchronously."""
    with patch("src.queue_worker.submit_write_task", side_effect=lambda action_fn, **kw: action_fn()):
        return lifecycle.handle_cancel(
            client=client,
            say=lambda text, **kw: None,
            channel="C_PURCHASE",
            thread_ts=thread_ts,
            msg_ts=msg_ts,
            user_id=user_id,
            req_data=req_data,
            state=state,
            history=[],
        )


# ---------------------------------------------------------------------------
# BOM is present — happy path
# ---------------------------------------------------------------------------

def test_cancel_moves_bom_to_cancelled_subfolder(tmp_path, monkeypatch):
    """Cancelling an approved request with a BOM moves the file to Cancelled/."""
    boms_dir = str(tmp_path / "BOMs")
    os.makedirs(boms_dir)
    monkeypatch.setattr(config, "BOMS_DIR", boms_dir)

    bom_fname = "0017_Acme_BOM.xlsx"
    bom_path = _make_bom_file(boms_dir, bom_fname)

    client = _make_client_with_row(17)
    req_data = {"bom_file": bom_fname}

    with patch.object(log_writer, "blank_row"):
        result = _run_cancel(client, req_data)

    assert result is True

    # File must have moved into Cancelled/
    cancelled_path = os.path.join(boms_dir, "Cancelled", bom_fname)
    assert os.path.exists(cancelled_path), "BOM must exist in Cancelled/ after cancel"

    # The live folder must no longer hold the file
    assert not os.path.exists(bom_path), "BOM must be gone from the live BOMs folder"


def test_cancel_live_folder_no_longer_holds_file(tmp_path, monkeypatch):
    """After cancel the live BOMs folder contains no file with the BOM's name."""
    boms_dir = str(tmp_path / "BOMs")
    os.makedirs(boms_dir)
    monkeypatch.setattr(config, "BOMS_DIR", boms_dir)

    bom_fname = "0018_LabSupplies_BOM.xlsx"
    _make_bom_file(boms_dir, bom_fname)

    client = _make_client_with_row(18)
    req_data = {"bom_file": bom_fname}

    with patch.object(log_writer, "blank_row"):
        _run_cancel(client, req_data)

    live_files = os.listdir(boms_dir)
    assert bom_fname not in live_files, (
        f"Live BOMs folder must not contain {bom_fname} after cancel; found: {live_files}"
    )


def test_cancel_preserves_bom_filename_in_cancelled_dir(tmp_path, monkeypatch):
    """The file name is kept when moved into Cancelled/."""
    boms_dir = str(tmp_path / "BOMs")
    os.makedirs(boms_dir)
    monkeypatch.setattr(config, "BOMS_DIR", boms_dir)

    bom_fname = "0019_Thermo_BOM.xlsx"
    _make_bom_file(boms_dir, bom_fname)

    client = _make_client_with_row(19)
    req_data = {"bom_file": bom_fname}

    with patch.object(log_writer, "blank_row"):
        _run_cancel(client, req_data)

    cancelled_dir = os.path.join(boms_dir, "Cancelled")
    assert bom_fname in os.listdir(cancelled_dir), (
        "File must keep its original name inside Cancelled/"
    )


# ---------------------------------------------------------------------------
# No BOM on the request — unchanged behaviour
# ---------------------------------------------------------------------------

def test_cancel_with_no_bom_completes_normally(tmp_path, monkeypatch):
    """A request with no bom_file cancels without error and blanks its row."""
    boms_dir = str(tmp_path / "BOMs")
    os.makedirs(boms_dir)
    monkeypatch.setattr(config, "BOMS_DIR", boms_dir)

    client = _make_client_with_row(20)
    req_data = {}  # no bom_file key

    blanked = []
    with patch.object(log_writer, "blank_row", side_effect=lambda r, **kw: blanked.append(r)):
        result = _run_cancel(client, req_data)

    assert result is True
    assert blanked, "Row must still be blanked when no BOM is present"

    # No Cancelled/ directory created, no files moved
    cancelled_dir = os.path.join(boms_dir, "Cancelled")
    assert not os.path.exists(cancelled_dir), (
        "Cancelled/ directory must not be created when request has no BOM"
    )


# ---------------------------------------------------------------------------
# BOM file already missing — warning logged, cancel still completes
# ---------------------------------------------------------------------------

def test_cancel_missing_bom_logs_warning_and_still_blanks_row(tmp_path, monkeypatch, caplog):
    """A missing BOM file logs a warning but does not abort the cancellation."""
    boms_dir = str(tmp_path / "BOMs")
    os.makedirs(boms_dir)
    monkeypatch.setattr(config, "BOMS_DIR", boms_dir)

    bom_fname = "0021_Missing_BOM.xlsx"
    # Deliberately do NOT create the file

    client = _make_client_with_row(21)
    req_data = {"bom_file": bom_fname}

    blanked = []
    with caplog.at_level(logging.WARNING), \
         patch.object(log_writer, "blank_row", side_effect=lambda r, **kw: blanked.append(r)):
        result = _run_cancel(client, req_data)

    assert result is True, "Cancel must succeed even when BOM file is missing"
    assert blanked, "Row must be blanked even when BOM file is missing"

    warning_text = " ".join(caplog.messages)
    assert bom_fname in warning_text, (
        "A warning mentioning the BOM filename must be logged when the file is missing"
    )


def test_cancel_missing_bom_does_not_create_cancelled_dir(tmp_path, monkeypatch):
    """No Cancelled/ directory is created when the source file does not exist."""
    boms_dir = str(tmp_path / "BOMs")
    os.makedirs(boms_dir)
    monkeypatch.setattr(config, "BOMS_DIR", boms_dir)

    bom_fname = "0022_NeverSaved_BOM.xlsx"
    client = _make_client_with_row(22)
    req_data = {"bom_file": bom_fname}

    with patch.object(log_writer, "blank_row"):
        _run_cancel(client, req_data)

    cancelled_dir = os.path.join(boms_dir, "Cancelled")
    assert not os.path.exists(cancelled_dir), (
        "Cancelled/ must not be created when source BOM does not exist"
    )


# ---------------------------------------------------------------------------
# Cancel refused after processed — no file moved
# ---------------------------------------------------------------------------

def test_cancel_refused_after_processed_does_not_move_bom(tmp_path, monkeypatch):
    """When cancel is refused (state=processed), the BOM file must not move."""
    boms_dir = str(tmp_path / "BOMs")
    os.makedirs(boms_dir)
    monkeypatch.setattr(config, "BOMS_DIR", boms_dir)

    bom_fname = "0023_Processed_BOM.xlsx"
    bom_path = _make_bom_file(boms_dir, bom_fname)

    client = MagicMock()
    req_data = {"bom_file": bom_fname}

    posted = []
    result = lifecycle.handle_cancel(
        client=client,
        say=lambda text, **kw: posted.append(text),
        channel="C_PURCHASE",
        thread_ts="100.0",
        msg_ts="100.10",
        user_id="U_CHARLIE",
        req_data=req_data,
        state="processed",
        history=[],
    )

    assert result is False, "Cancel must be refused for processed state"
    assert posted, "Refusal message must be posted"

    # BOM must still be in the live folder — not moved
    assert os.path.exists(bom_path), "BOM must not be moved when cancel is refused"
    cancelled_dir = os.path.join(boms_dir, "Cancelled")
    assert not os.path.exists(cancelled_dir), "Cancelled/ must not be created on refusal"


def test_cancel_refused_for_confirmed_and_delivered_does_not_move_bom(tmp_path, monkeypatch):
    """Cancel is also refused for confirmed and delivered; BOM stays in live folder."""
    boms_dir = str(tmp_path / "BOMs")
    os.makedirs(boms_dir)
    monkeypatch.setattr(config, "BOMS_DIR", boms_dir)

    for state in ("confirmed", "delivered"):
        bom_fname = f"0024_State_{state}_BOM.xlsx"
        bom_path = _make_bom_file(boms_dir, bom_fname)

        client = MagicMock()
        req_data = {"bom_file": bom_fname}

        result = lifecycle.handle_cancel(
            client=client,
            say=lambda text, **kw: None,
            channel="C_PURCHASE",
            thread_ts="100.0",
            msg_ts="100.10",
            user_id="U_CHARLIE",
            req_data=req_data,
            state=state,
            history=[],
        )

        assert result is False, f"Cancel must be refused for state={state}"
        assert os.path.exists(bom_path), f"BOM must not be moved when cancel refused (state={state})"
