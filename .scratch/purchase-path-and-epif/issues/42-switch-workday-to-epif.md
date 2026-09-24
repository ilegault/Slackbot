# 42: Switch an approved Workday request to EPIF before it's processed

**Status:** ready-for-agent

**Runner:** any

**Auto-merge:** yes

**Blocked by:** 38, 45, 46

Spec: Implementation Decision 4 (switch). Binding: ADR 0007 decision 5, invariant 2.

**What to build:** An approved Workday request is logged at some row and assigned to a
buyer, who finds the vendor isn't on Workday. The card has **Switch to EPIF**. Pressing
it opens the EPIF-path interview pre-filled from the request. On submit **the same row**
is rewritten, the filled EPIF is archived in the same queued write, the thread gets
`🔁 Switched to EPIF by <name>`, and the buyer gets the EPIF DM. Once the request is
processed, the button is gone and a switch is refused.

- [ ] `blocks.build_request_blocks` shows a `req_switch_epif` button only when the card is `approved`, `interview.get_request_route(payload)` is `workday`, and the payload has no processed date. Tests build blocks for each of those three conditions failing and assert the button is absent.
- [ ] Permission is the same as Fill in details (ticket 40): requester, assignee, any buyer while unassigned, or admin. Others: denial via `respond`, no `views_open`, workbook unchanged.
- [ ] The rewrite goes through `queue_worker.submit_write_task` and `log_writer.update_row` on the **same** row: vendor, payment method and detail columns change; requester, date of request and stage dates do not. Proof: the row number is unchanged, the row count is unchanged, and the requester cell is byte-identical.
- [ ] Inside the queued task, the switch re-reads Date Processed with `log_writer.get_row_info` and refuses if it is set. Proof: a test marks the row processed after the button press but before the task runs; the row is byte-identical afterwards, no file is added to `EPIFS_DIR`, and the actor is told why.
- [ ] On success the card's payload `route` becomes `epif` (read back from the `chat_update` metadata), one `🔁 Switched to EPIF by …` line is posted, and the assignee's DM has a `files_upload_v2` call for the new PDF.
- [ ] Full gate green, in CI order: `ruff check .`, `python scripts/check_tests_first.py`, `pytest -q`.

**Tests may fake:** the Slack client (a `MagicMock` that records calls) and the network. **Tests must use real:** the handlers, `log_writer`, and a temporary copy of the workbook (copy the `temp_workbook` and `sync_queue` fixtures from `tests/test_29_approval_archives_bom.py`). A test that patches out the function this ticket changes does not count. Point `config.EPIFS_DIR` at `tmp_path` and `config.EPIF_TEMPLATE_PATH` at the fixture.

## Comments
