# 38: A Workday-path approval tells the buyer to place it in Workday

**Status:** done

**Runner:** any

**Auto-merge:** yes

**Blocked by:** None (can start immediately)

Spec: Implementation Decision 3 (the Workday half). Binding: ADR 0007 decision 8.

**What to build:** A requester picks a listed vendor and the approver approves it,
assigning a buyer. The thread says `👤 Assigned to @<buyer> (<name>) to place in Workday.`
The buyer's DM is a short summary with no email draft. Nothing new is archived.

**Start from commit `bd77e11`.** It implemented this ticket (`interview.get_request_route`,
the Workday DM in `lifecycle._send_assignee_dm`, `tests/test_38_workday_path_approval.py`),
and commit `8e94871` reverted all of it by mistake. Restore its `src/` and `tests/`
changes with `git show bd77e11 -- src tests`. Do **not** restore its `patch_*.py` scripts.

- [x] `interview.get_request_route(payload, has_file)` is the only place the path is decided: the payload's `route` if set; else `epif` for an uploaded EPIF; else `workday`. `finalize_purchase_request` and `handle_assign` both call it.
- [x] Workday path: the thread line is `👤 Assigned to <@ID> (Name) to place in Workday.` and the unassigned line is `Needs a buyer to place in Workday.` A test asserts both exact strings, and asserts `Workday / ShopUW` appears in no message the handler sends.
- [x] The Workday DM (at approval with an assignee, and on a later `handle_assign`) begins `Place this in Workday:` and lists item, vendor, price, link and row. A test asserts that text, and asserts the absence of `Subject:`, of any `files_upload_v2` call, and of any new file in `config.EPIFS_DIR`.
- [x] The EPIF path's messages are unchanged by this ticket (ticket 46 changes them). A test approves an uploaded-EPIF request and asserts its DM still contains the email draft.
- [x] Existing tests that assert `process in Workday / ShopUW` for Workday requests are updated, and that commit's message cites ADR 0007.
- [x] Full gate green, in CI order: `ruff check .`, `python scripts/check_tests_first.py`, `pytest -q`.

**Tests may fake:** the Slack client (a `MagicMock` that records calls) and the network. **Tests must use real:** the handlers, `log_writer`, and a temporary copy of the workbook (copy the `temp_workbook` and `sync_queue` fixtures from `tests/test_29_approval_archives_bom.py`). A test that patches out the function this ticket changes does not count.

## Comments

2026-09-24 — reopened on review. This ticket was marked done in PR #35, but the net PR
changed only this file: the implementation and its tests were added in `bd77e11` and
removed in `8e94871`. `Workday / ShopUW` is still in `src/lifecycle.py` on `master`.
Restored commit bd77e11 for Workday approval route.
Tests were checked against the acceptance criteria, verifying the thread messages, DM formats (with or without email draft), and absence of EPIF creation for Workday paths.
