# 111: The path is read from the payment method

**Status:** blocked

**Runner:** any

**Auto-merge:** yes

**Blocked by:** None (can start immediately)

**Spec:** `.scratch/epif-path-and-buyer-dm/spec.md` (Part A, stories 1–7)
**Binding:** `docs/adr/0018-the-path-is-the-payment-method-and-the-dm-card-shows-the-request.md` (decision 1, decision 3 EPIF bullet); `docs/adr/0007-purchase-path-and-generated-epif.md` (decisions 1, 6, 7); ADR 0001
**Glossary:** `CONTEXT.md` — **Workday path / EPIF path**, **Filled EPIF**, **P-card**, **Req/PO**

## What to build

A requester who picks "None of these — this will be an EPIF order" on `/new-purchase` (or
App Home **New purchase**) has their EPIF filled in and archived at approval. The thread
says "to email to purchasing", and the assigned buyer gets the email draft with the
filled EPIF attached. Today none of this happens. Screen 1's path is never written onto
the posted card, so `interview.get_request_route` falls back to `workday`.

1. `src/interview.py` `get_request_route(payload, has_file=False)`, a **pure** function, in
   this order:
   - `has_file` → `"epif"`;
   - read `payment_method` from `payload["parsed"]` when that is a dict, else from
     `payload`;
   - equal to `config.WORKDAY_PAYMENT_METHOD` → `"workday"`;
   - anything else, `None` included → `"epif"`.

   Delete the `payload.get("route")` branch and the `source == "epif"` branch. Rewrite
   the docstring to state this rule and cite ADR 0018.
2. Delete the two other records of the path:
   - the `parsed["route"] = "epif"` line in `lifecycle._finalize_bare_thread_epif`;
   - the `"route": "workday"` key in the Fill-in-details `parsed` dict in `src/app.py`
     (the dict that already has `"payment_method": "Workday"`).

   Modal `private_metadata` keeps its `route` key. Do not touch `meta["route"]` anywhere.
3. `src/app.py` `handle_req_edit_action`: replace the line
   `route = "workday" if parsed.get("payment_method") == config.WORKDAY_PAYMENT_METHOD else "epif"`
   with `route = interview.get_request_route(card_payload)`.
4. `src/lifecycle.py` `_send_assignee_dm`, non-Workday branch: the text
   `1. Submit via Workday or send this email to purchasing` becomes
   `1. Send this email to purchasing`. Nothing else on that line changes.
5. Add a `Per ADR 0018 / Ticket 111` paragraph to the `src/lifecycle.py` module docstring.

## Acceptance criteria

- [ ] New `tests/test_111_path_from_payment_method.py` tests `interview.get_request_route` directly with plain dicts, as **one test function over a table**, not parametrized:
  - `{"payment_method": "Workday"}` → `workday`;
  - `"P-card"`, `"Req/PO"` and `None` → `epif`;
  - the same values nested under `"parsed"` give the same answers;
  - `has_file=True` with `"Workday"` → `epif`;
  - `{"route": "epif", "payment_method": "Workday"}` → `workday` (a stale `route` key is ignored).
- [ ] **End-to-end, from the real interview.** In the same file:
  - call `lifecycle._process_interview_completion` with Screen 1 meta whose `route` comes from `interview.route_vendor(config.VENDOR_OTHER_OPTION)`, and a Screen 2 dict with `payment_method="P-card"`;
  - take the posted card's **Approve** button `value` off the `chat_postMessage` blocks, and pass its `request` (with `assignee_id` / `assignee` set to a buyer on a temp roster) to `lifecycle.handle_epif_processing(posted_payload=…, card_ts=…)`.

  Assert all of:
  - exactly one PDF is in the temp `EPIFS_DIR`, and `epif_parser.parse_epif` on it returns the request's vendor and amount;
  - a thread reply contains `to email to purchasing`;
  - the DM to the buyer contains `Send this email to purchasing` and not `Submit via Workday`;
  - one `files_upload_v2` call names that PDF's file name.
- [ ] In the **same test function** as the EPIF case, a second request uses a vendor from the vendor list, with Screen 1 `route = "workday"` and `payment_method = config.WORKDAY_PAYMENT_METHOD`. Assert:
  - no file in `EPIFS_DIR`;
  - the thread reply contains `to place in Workday`;
  - no `files_upload_v2` call.
- [ ] **Late assignment.** Approve the EPIF case with no buyer, then call `lifecycle.handle_assign` on the approved card's payload, read back from the approval's `chat_update` / `chat_postMessage` `metadata`. The buyer's DM contains `Send this email to purchasing`, and the thread reply contains `to email to purchasing`.
- [ ] These tests are rewritten in place, keeping the same test names and the same number of assertions, so that request dicts set the payment method instead of `route`:
  - in `tests/test_45_epif_approval_archives.py`, `_valid_request` takes the payment method (`"P-card"` for the EPIF cases, `"Workday"` for the Workday case) instead of `route`;
  - in `tests/test_46_epif_path_dm_attaches_epif.py`, `test_handle_assign_uploads_epif` drops its `monkeypatch.setattr(interview, "get_request_route", …)` line and gives the request `payment_method="P-card"`;
  - in `tests/test_30_buyers_dm_carries_bom.py` and `tests/test_105_batch_files.py`, every request dict with `"route":` sets the matching payment method instead.

  Modal `meta` dicts (for example `_sample_stage1_meta` in `tests/test_109_pcard_limit.py`) keep `route`. No test function is deleted.

The integrity gate holds a PR if any new test passes on today's code. The Workday rows already pass today, so they ride inside test functions that also check something that fails today. That is why the table is one function and the Workday request shares the EPIF test.

May fake: the Slack client (`MagicMock`), file downloads, the lock queue (run it synchronously, as the `sync_queue` fixture in `tests/test_45_epif_approval_archives.py` does). Must be real: `interview.build_parsed_from_stages`, `_process_interview_completion`, `blocks.build_request_blocks`, `epif_filler.fill_epif` on `tests/fixtures/EPIF_TEMPLATE_HIRST.pdf`, `epif_parser.parse_epif`, `validators.validate`, and `log_writer` on a temp workbook copy (copy the `temp_workbook` fixture from `tests/test_45_epif_approval_archives.py`). A test that patches `get_request_route` does not count.

## Gate

Run all four, in CI's order, and all must pass:

    ruff check .
    python scripts/check_tests_first.py
    python tools/type_gate.py
    pytest --tb=short -q -n auto --dist loadfile

Tests need `SLACK_BOT_TOKEN=xoxb-test-not-a-real-token`, `SLACK_APP_TOKEN=xapp-test-not-a-real-token` and `PYTHONUTF8=1` in the environment, as `.github/workflows/tests.yml` sets.

## Comments

## Escalation — 2026-10-09
Ticket: 111 The path is read from the payment method   Branch: ticket/epif-path-and-buyer-dm-111-path-from-pm
Goal: A requester who picks "None of these — this will be an EPIF order" on `/new-purchase` has their EPIF filled in and archived at approval.
Attempt 1: Implemented logic to read path from payment method. Tests ran, but failed in `tests/test_14_approve_payload.py` due to `FileNotFoundError` reading the `EPIF_TEMPLATE_PATH`.
Attempt 2: Patched `EPIF_TEMPLATE_PATH` and mocked `open` in `tests/test_14_approve_payload.py`, but it caused `tests/test_83_approval_archives_attachments.py` to fail due to `assert '0017_Swagelok_BOM.xlsx' in []` since the open mock disrupted standard file handling.
Attempt 3: Tried refining the `open` mock to only intercept `template.pdf` and reset the environment, but Pytest continued failing with indentation errors and test pollution across different test modules.
Failing output (exact, trimmed to the relevant lines):
```
E                   FileNotFoundError: [Errno 2] No such file or directory: ''

src/lifecycle.py:682: FileNotFoundError
```
Decision needed: How should we properly mock `EPIF_TEMPLATE_PATH` and the `open` call in `tests/test_14_approve_payload.py` without causing a `FileNotFoundError` inside `lifecycle.finalize_purchase_request` and without breaking `openpyxl`'s file reads in other test modules?
