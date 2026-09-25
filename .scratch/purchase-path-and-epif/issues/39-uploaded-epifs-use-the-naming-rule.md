# 39: Uploaded EPIFs are archived under the naming rule

**Status:** done

**Runner:** any

**Auto-merge:** yes

**Blocked by:** 44

Spec: Implementation Decision 2 (naming). Binding: ADR 0007 decision 7.

**What to build:** A requester drops `my epif final v2.pdf` for a $349 lens from
Commonlands in a thread, and the approver approves it. The archived copy in
`config.EPIFS_DIR` is `Commonlands_EPIF_$349.00_<project id>.pdf`. The file in Slack
keeps its original name.

- [x] In `lifecycle.finalize_purchase_request.write_action`, the uploaded PDF is saved under `log_writer.epif_archive_name(...)` (ticket 44) computed from the parsed vendor, total and project ID, passing the names already in `config.EPIFS_DIR`. There is no second naming implementation.
- [x] The "Saved EPIF to …" thread line names the archived file. A test asserts the exact name in that line.
- [x] A second identical upload is archived as `…_2.pdf`, and the first file's bytes are unchanged (compare the bytes, not just the name).
- [x] Cancel still moves the archived EPIF to `EPIFs/Cancelled/` under its archived name; a test cancels after approval and asserts the file is there and gone from `EPIFs/`.
- [x] BOM naming (`NNNN_<Vendor>_BOM.xlsx`) and its Notes line are unchanged; the existing `tests/test_29_approval_archives_bom.py` still passes untouched.
- [x] Full gate green, in CI order: `ruff check .`, `python scripts/check_tests_first.py`, `pytest -q`.

**Tests may fake:** the Slack client (a `MagicMock` that records calls) and the network. **Tests must use real:** the handlers, `log_writer`, and a temporary copy of the workbook (copy the `temp_workbook` and `sync_queue` fixtures from `tests/test_29_approval_archives_bom.py`). A test that patches out the function this ticket changes does not count. Point `config.EPIFS_DIR` at a `tmp_path` folder.

## Comments

2026-09-25 - Work completed:
- `finalize_purchase_request` saves EPIF with `log_writer.epif_archive_name` passing existing files.
- Thread line "Saved EPIF to ..." uses the archived file.
- Cancel successfully moves the archived EPIF to `EPIFs/Cancelled/`.
- Tests added in `tests/test_39_uploaded_epifs_naming.py` validating the file naming and cancel directory moves.