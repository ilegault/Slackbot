# 83: Approval archives attachments and hands them to the buyer

**Status:** done

**Runner:** any

**Auto-merge:** yes

**Blocked by:** 82

**Spec:** `.scratch/attached-boms-and-quotes/spec.md`
**Binding:** `docs/adr/0012-attached-boms-and-quotes-are-carried-not-read.md` decision 5; `docs/adr/0006-bom-line-items-and-editable-posted-cards.md` decisions 6–7; `docs/adr/0009-keywords-storage-settings-and-the-bot-name.md` (storage errors); ADR 0001

## What to build

When the approver approves a card that carries attachments, the bot files them next to the EPIF
and gives them to the assigned buyer, exactly as it already does for a made BOM. The attached BOM
is stored byte-for-byte; the bot never opens it.

1. `src/bom.py`: `bom_filename(row, vendor)` gains `ext: str = "xlsx"` (used for the suffix; the
   draft/row prefix logic is unchanged). New pure `quote_filename(row: int, vendor: str, k: int) -> str`
   → `NNNN_<Vendor>_Quote_<k>.pdf`, using the same zero-padding and vendor slugging as `bom_filename`.
2. `src/lifecycle.py` `handle_epif_processing`: read `attachments` from `card_payload` /
   `posted_payload` at the same three places it reads `items`, and pass it to
   `finalize_purchase_request` as a new keyword `attachments: list[dict] | None = None`.
3. `src/lifecycle.py` `finalize_purchase_request`, in the step that saves the made BOM today:
   - a `bom`-role attachment → fetch bytes (`client.files_info(file=id)["file"]` →
     `slack_io.download_file`), name `bom.bom_filename(row_num, vendor, ext=<attachment's extension, lower-case>)`,
     save with `log_writer.save_bom`, Notes text `BOM: <fname> (attached)`, set
     `req_payload["bom_file"]`, upload to the thread with `upload_archived_bom`. Never build a
     made BOM for the same request.
   - `quote`-role attachments → in order, `bom.quote_filename(row_num, vendor, k)` for k = 1…,
     saved with `log_writer.save_quote`; set `req_payload["quote_count"] = n` (a count, not names,
     because the button value is size-capped; names are derived from row + vendor + k).
   - a failed fetch for one file → `slack_io.alert_admins` naming the file and the row; the
     approval continues and that file is skipped (the money decision already happened, as for a
     failed BOM upload today). A missing `QUOTES_DIR` raises `StorageLocationError` exactly as a
     missing `BOMS_DIR` does today and goes through the same handling.
4. `src/lifecycle.py` `_send_assignee_dm` gains `quote_paths: list[str] | None = None` and uploads
   each to the DM the same way it uploads `bom_path`. `finalize_purchase_request` passes the
   saved quote paths. `handle_assign` (assignment after approval) rebuilds them from
   `req_data["quote_count"]`, the row, the vendor and `config.QUOTES_DIR`, the way it already
   finds the BOM from `req_data["bom_file"]`, and passes them too.

## Acceptance criteria

New test file `tests/test_83_approval_archives_attachments.py`. Approve through the same entry
point as `tests/test_29_approval_archives_bom.py` with temp `BOMS_DIR`, `QUOTES_DIR` and a temp
workbook copy as that test uses. Fake `files_info` + `slack_io.download_file` returning the bytes
of a real `.xlsx` that contains a `=SUM(...)` formula (build it with openpyxl in the test).

- [x] **Attached BOM archived as-is.** Approving a card with an attached `order.xlsx` writes `BOMS_DIR/<row>_<Vendor>_BOM.xlsx` whose bytes equal the fake download bytes exactly; the row's Notes cell is `BOM: <that name> (attached)`; `files_upload_v2` uploads it to the thread; `bom.build_bom_workbook` is not called (spy).
- [x] **CSV keeps its extension.** An attached `order.csv` is archived as `<row>_<Vendor>_BOM.csv`.
- [x] **Quotes numbered.** Three quote attachments → `QUOTES_DIR` contains `<row>_<Vendor>_Quote_1.pdf`, `_2.pdf`, `_3.pdf` with the right bytes in attachment order; the approved card's button value has `"quote_count": 3`. `bom.quote_filename(7, "Swagelok", 2)` equals the name `bom_filename` would give row 7 with `_Quote_2.pdf` in place of `_BOM.xlsx`.
- [x] **The buyer gets them.** With a buyer named at approval, the buyer's DM receives uploads of the archived BOM and all three quotes. Assigning a buyer later through the picker (`app.handle_req_assign_select_action`) → that buyer's DM also receives the three quotes.
- [x] **One failed fetch doesn't stop approval.** Download raising for quote 2 → the row is written, quotes 1 and 3 are saved, `slack_io.alert_admins` is called with text containing the file name, no `_Quote_2.pdf` exists.
- [x] **Decline archives nothing.** Declining the same card leaves `BOMS_DIR` and `QUOTES_DIR` empty.

**Tests may fake:** the Slack client, `slack_io.download_file`, the lock queue as `tests/test_29_approval_archives_bom.py` does. **Must be real:** `finalize_purchase_request`, `bom` naming, `log_writer.save_bom` / `save_quote` into the temp folders, the Notes write on the temp workbook.

## Gate

Run in this order, exactly as CI does (`.github/workflows/tests.yml`). Zero failures before
you push.

```
ruff check .
python scripts/check_tests_first.py
python tools/type_gate.py
pytest --tb=short -q -n auto --dist loadfile
```

## Comments

Done (2026-10-05). `bom.bom_filename(ext=)` and `bom.quote_filename`; `finalize_purchase_request` files an attached BOM byte-for-byte and numbered quotes (new `attachments` kwarg, read in `handle_epif_processing` from card metadata); approved card carries `quote_count`, not the list; `_send_assignee_dm(quote_paths=)` and `handle_assign` hand quotes to the buyer. Tests: `tests/test_83_approval_archives_attachments.py` (one per criterion plus a real `handle_epif_processing` entry-point test). Surprise: `log_writer.save_bom` forced a `.xlsx` suffix (an attached `.csv` became `.csv.xlsx`); it now only defaults the suffix when the name has none. Buyer DM uploads follow the existing rule that files go only on the EPIF route. Gate: ruff, tests-first, type_gate (95, ratchet 95), pytest 647 passed.
