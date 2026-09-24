# 41: "This needs an EPIF" turns a waiting request into an EPIF order

**Status:** ready-for-agent

**Runner:** any

**Auto-merge:** yes

**Blocked by:** 40, 45, 46

Spec: Implementation Decision 4 (This needs an EPIF). Binding: ADR 0007 decisions 4–6.

**What to build:** On a card waiting for details, the assigned buyer finds the vendor
isn't on Workday and presses **This needs an EPIF**. The EPIF-path interview opens at
Screen 2. On submit the row is written with `route = epif`, the filled EPIF is generated
and archived in the same queued write, the card becomes an ordinary approved card, and
the buyer gets the EPIF DM with the PDF attached. No new card is posted and the approver
is not asked again.

- [ ] `app.handle_req_needs_epif` keeps its permission check (ticket 40), and instead of the "coming in ticket 41" DM opens `blocks.build_stage2_view` with `route = epif` and the bare-thread context in private metadata: channel, thread, card ts, requester ID and name, approver, assignee.
- [ ] On completion, `lifecycle._process_interview_completion` sees that context and calls `finalize_purchase_request` against the existing card (`card_ts`) instead of posting a new posted card. Proof: after the scenario, `chat_postMessage` was called with no new card blocks, and no button with `action_id` `req_approve` exists in any posted blocks.
- [ ] Row, EPIF and card update happen in the one queued task that ticket 45 built. If it fails, the card stays `waiting_for_details`: a test makes `config.EPIF_TEMPLATE_PATH` point at a missing file and asserts no row, no `chat_update` to `approved`, and a failure line in the thread.
- [ ] **Scenario**, bare approval then This needs an EPIF submitted by the assignee: one row with `route = epif`, one PDF in `EPIFS_DIR` named by `log_writer.epif_archive_name`, the card updated to `approved`, and the assignee's DM has a `files_upload_v2` call for that PDF.
- [ ] Full gate green, in CI order: `ruff check .`, `python scripts/check_tests_first.py`, `pytest -q`.

**Tests may fake:** the Slack client (a `MagicMock` that records calls) and the network. **Tests must use real:** the handlers, `log_writer`, and a temporary copy of the workbook (copy the `temp_workbook` and `sync_queue` fixtures from `tests/test_29_approval_archives_bom.py`). A test that patches out the function this ticket changes does not count. Point `config.EPIFS_DIR` at `tmp_path` and `config.EPIF_TEMPLATE_PATH` at `tests/fixtures/EPIF_TEMPLATE_HIRST.pdf`.

## Comments
