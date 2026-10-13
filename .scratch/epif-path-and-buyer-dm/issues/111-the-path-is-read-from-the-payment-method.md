# 111: The path is read from the payment method

**Status:** done

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

- [x] New `tests/test_111_path_from_payment_method.py`; its test `test_route_is_read_from_the_payment_method` tests `interview.get_request_route` directly with plain dicts, as **one test function over a table**, not parametrized:
  - `{"payment_method": "Workday"}` → `workday`;
  - `"P-card"`, `"Req/PO"` and `None` → `epif`;
  - the same values nested under `"parsed"` give the same answers;
  - `has_file=True` with `"Workday"` → `epif`;
  - `{"route": "epif", "payment_method": "Workday"}` → `workday` (a stale `route` key is ignored).
- [x] **End-to-end, from the real interview.** In the same file, test `test_epif_request_from_the_interview_gets_a_filled_epif_and_a_buyer_email`:
  - call `lifecycle._process_interview_completion` with Screen 1 meta whose `route` comes from `interview.route_vendor(config.VENDOR_OTHER_OPTION)`, and a Screen 2 dict with `payment_method="P-card"`;
  - take the posted card's **Approve** button `value` off the `chat_postMessage` blocks, and pass its `request` (with `assignee_id` / `assignee` set to a buyer on a temp roster) to `lifecycle.handle_epif_processing(posted_payload=…, card_ts=…)`.

  Assert all of:
  - exactly one PDF is in the temp `EPIFS_DIR`, and `epif_parser.parse_epif` on it returns the request's vendor and amount;
  - a thread reply contains `to email to purchasing`;
  - the DM to the buyer contains `Send this email to purchasing` and not `Submit via Workday`;
  - one `files_upload_v2` call names that PDF's file name.
- [x] In the **same test function** as the EPIF case (`test_epif_request_from_the_interview_gets_a_filled_epif_and_a_buyer_email`), a second request uses a vendor from the vendor list, with Screen 1 `route = "workday"` and `payment_method = config.WORKDAY_PAYMENT_METHOD`. Assert:
  - no file in `EPIFS_DIR`;
  - the thread reply contains `to place in Workday`;
  - no `files_upload_v2` call.
- [x] **Late assignment**, test `test_late_assigned_buyer_gets_the_epif_email`. Approve the EPIF case with no buyer, then call `lifecycle.handle_assign` on the approved card's payload, read back from the approval's `chat_update` / `chat_postMessage` `metadata`. The buyer's DM contains `Send this email to purchasing`, and the thread reply contains `to email to purchasing`.
- [x] These tests are rewritten in place, keeping the same test names and the same number of assertions, so that request dicts set the payment method instead of `route`. The rewritten tests are `test_epif_approval_generates_and_archives_filled_epif`, `test_epif_approval_fails_if_template_missing` and `test_workday_approval_adds_no_file` (`test_45`), `test_handle_assign_uploads_epif` (`test_46`), `test_approval_with_buyer_attaches_bom_to_dm`, `test_assign_after_unassigned_approval_attaches_bom` and `test_reassign_new_buyer_gets_bom_dm` (`test_30`), and `test_assign_card_b_uploads_quotes_in_buyer_dm` (`test_105`):
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

2026-10-13 — Landed. `interview.get_request_route` now reads only `has_file` and the payment method; the `route` / `source` branches, `parsed["route"]` in `_finalize_bare_thread_epif` and the `"route": "workday"` key in the Fill-in-details dict are gone; the Edit opener calls `get_request_route(card_payload)`; the EPIF draft says "Send this email to purchasing"; lifecycle docstring has the ADR 0018 paragraph.
Tests: `tests/test_111_path_from_payment_method.py` (table test, interview-to-approval end-to-end for EPIF and Workday, late assignment). Seen failing before the code change: all three.
Rewritten in place (same names, same assertion counts): test_45 (3), test_46 `test_handle_assign_uploads_epif`, test_30 (`_parsed` + card dicts), test_105 `test_assign_card_b_uploads_quotes_in_buyer_dm`.
Also rewritten, not named in the ticket, because they carried an implicit "no payment method means Workday" and broke on the new rule: test_08 `test_buyer_self_assigns_unassigned_request` (card gets `payment_method: Workday`), test_14 two tests (P-card -> Workday, they test resolution order, not the path), test_40 `test_fill_in_details_writes_row_and_updates_card` (asserts payment method, the `route` key is deleted by this ticket), test_83 `_parsed` helper, test_onboarding `test_finalize_purchase_request_without_pdf` (stage 1 is now a Workday-path vendor, since "save_epif skipped" is a Workday-path fact).
Local gate: ruff clean, check_tests_first OK, type_gate within ratchet, pytest 821 passed. The one local failure, `test_docs_adr_is_unmodified`, is the sandbox's stale local `master` ref (6582283, behind origin/master); it diffs against local `master` and sees ADR 0018 as new. CI has no stale ref.
