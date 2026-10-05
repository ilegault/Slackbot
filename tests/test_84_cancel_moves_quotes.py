"""Tests for Ticket 84: Cancel moves archived quotes out of the live folder.

Acceptance criteria (ADR 0012 decision 5, ADR 0006 decision 7):
- Cancelling an approved card with quote_count: 3 and all three files present leaves
  QUOTES_DIR with no _Quote_ files and QUOTES_DIR/Cancelled/ holding all three.
- A missing quote does not block the cancel: the others move, the row is blanked.
- A card without quote_count cancels as before; QUOTES_DIR/Cancelled/ is not created.
- An attached CSV BOM (bom_file <row>_<Vendor>_BOM.csv) ends up in BOMS_DIR/Cancelled/.
"""
import os
from unittest.mock import MagicMock, patch

from src import bom, config, lifecycle, log_writer

ROW = 17
VENDOR = "Acme"


def _client() -> MagicMock:
    client = MagicMock()
    client.conversations_replies.return_value = {
        "messages": [{"text": f"Logged to row {ROW}: item — $10.00"}]
    }
    return client


def _touch(folder: str, name: str) -> str:
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, name)
    with open(path, "wb") as fh:
        fh.write(b"attached file bytes")
    return path


def _cancel(req_data: dict, blanked: list | None = None):
    blanked = blanked if blanked is not None else []
    with patch("src.queue_worker.submit_write_task", side_effect=lambda action_fn, **kw: action_fn()), \
         patch.object(log_writer, "blank_row", side_effect=lambda r, **kw: blanked.append(r)):
        return lifecycle.handle_cancel(
            client=_client(),
            say=lambda text, **kw: None,
            channel="C_PURCHASE",
            thread_ts="100.0",
            msg_ts="100.10",
            user_id="U_CHARLIE",
            req_data=req_data,
            state="approved",
            history=[],
        )


def _card(**extra) -> dict:
    return {"parsed": {"vendor": VENDOR}, **extra}


def _quotes_dir(tmp_path, monkeypatch) -> str:
    qdir = str(tmp_path / "Quotes")
    os.makedirs(qdir)
    monkeypatch.setattr(config, "QUOTES_DIR", qdir)
    return qdir


def test_cancel_moves_all_quotes_to_cancelled(tmp_path, monkeypatch):
    qdir = _quotes_dir(tmp_path, monkeypatch)
    names = [bom.quote_filename(ROW, VENDOR, k) for k in (1, 2, 3)]
    for n in names:
        _touch(qdir, n)

    blanked: list = []
    assert _cancel(_card(quote_count=3), blanked) is True

    assert blanked == [ROW]
    live = [f for f in os.listdir(qdir) if "_Quote_" in f]
    assert live == [], f"live QUOTES_DIR must hold no quotes, found {live}"
    assert sorted(os.listdir(os.path.join(qdir, "Cancelled"))) == sorted(names)


def test_cancel_with_a_missing_quote_still_moves_the_rest_and_blanks_row(tmp_path, monkeypatch, caplog):
    qdir = _quotes_dir(tmp_path, monkeypatch)
    names = [bom.quote_filename(ROW, VENDOR, k) for k in (1, 2, 3)]
    for n in (names[0], names[2]):
        _touch(qdir, n)

    blanked: list = []
    with caplog.at_level("WARNING"):
        assert _cancel(_card(quote_count=3), blanked) is True

    assert blanked == [ROW]
    assert sorted(os.listdir(os.path.join(qdir, "Cancelled"))) == sorted([names[0], names[2]])
    assert [f for f in os.listdir(qdir) if "_Quote_" in f] == []
    assert any(names[1] in r.getMessage() for r in caplog.records)


def test_cancel_without_quote_count_leaves_quotes_folder_alone(tmp_path, monkeypatch):
    qdir = _quotes_dir(tmp_path, monkeypatch)
    other = _touch(qdir, bom.quote_filename(ROW, VENDOR, 1))

    blanked: list = []
    assert _cancel(_card(), blanked) is True

    assert blanked == [ROW]
    assert not os.path.exists(os.path.join(qdir, "Cancelled"))
    assert os.path.exists(other)


def test_cancel_moves_attached_csv_bom(tmp_path, monkeypatch):
    boms_dir = str(tmp_path / "BOMs")
    monkeypatch.setattr(config, "BOMS_DIR", boms_dir)
    qdir = _quotes_dir(tmp_path, monkeypatch)
    fname = f"{ROW:04d}_{VENDOR}_BOM.csv"
    live = _touch(boms_dir, fname)
    quote = bom.quote_filename(ROW, VENDOR, 1)
    _touch(qdir, quote)

    # An attached BOM travels with its quotes: both leave the live folders together.
    assert _cancel(_card(bom_file=fname, quote_count=1)) is True

    assert os.path.exists(os.path.join(boms_dir, "Cancelled", fname))
    assert not os.path.exists(live)
    assert os.path.exists(os.path.join(qdir, "Cancelled", quote))
