# 46: EPIF-path buyer gets the filled EPIF in the DM, and the thread says to email purchasing

**Status:** ready-for-agent

**Runner:** any

**Auto-merge:** yes

**Blocked by:** 45

Spec: Implementation Decision 3 (the EPIF half). Binding: ADR 0007 decision 8, invariant 1.

**What to build:** On the EPIF path, the assigned buyer's DM carries the email draft with
the archived EPIF attached (and the BOM, if there is one), and the thread tells them to
email purchasing.

- [ ] EPIF path: the thread line is `👤 Assigned to <@ID> (Name) to email to purchasing.` and the unassigned line is `Needs a buyer to email to purchasing.` Both are chosen with `interview.get_request_route`. A test asserts each exact string.
- [ ] `lifecycle._send_assignee_dm` gains an `epif_path` argument and uploads that file with the same `conversations_open` + `files_upload_v2` code it already uses for the BOM. It is the only DM implementation: `finalize_purchase_request` and `handle_assign` both pass the archived EPIF path.
- [ ] **Scenario**, EPIF-path approval with an assignee: the DM text contains the email draft, and `files_upload_v2` was called with the archived EPIF's filename. With three line items, a second `files_upload_v2` call carries the BOM. A Workday-path approval makes no `files_upload_v2` call (absence asserted).
- [ ] **Later assign.** Assigning a buyer with `handle_assign` after approval sends the same DM with the same attachment. Proof: the test reads the EPIF path back from the card, not from a value it passed in.
- [ ] Full gate green, in CI order: `ruff check .`, `python scripts/check_tests_first.py`, `pytest -q`.

**Tests may fake:** the Slack client (a `MagicMock` that records calls) and the network. **Tests must use real:** the handlers, `log_writer`, and a temporary copy of the workbook (copy the `temp_workbook` and `sync_queue` fixtures from `tests/test_29_approval_archives_bom.py`). A test that patches out the function this ticket changes does not count.

## Comments
