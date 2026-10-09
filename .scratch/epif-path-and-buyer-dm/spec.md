# Spec — EPIF-path requests get their EPIF, and the buyer's DM shows the request

**Status:** ready-for-agent
**Binding:** `docs/adr/0018-the-path-is-the-payment-method-and-the-dm-card-shows-the-request.md`
(new), `docs/adr/0007-purchase-path-and-generated-epif.md` (decisions 1, 5, 6, 7; decision 8
replaced by 0018), `docs/adr/0010-linked-cards-and-direct-message-help.md` (decision 2
amended by 0018), `docs/adr/0004-assignment-replaces-claim.md`,
`docs/adr/0001-tests-first-and-no-muted-failures.md`
**Glossary:** `CONTEXT.md` — **Workday path / EPIF path** (updated: the payment method
records the path), **DM card** (updated: the thread card's fields), **Filled EPIF**,
**P-card**, **Req/PO**

Five parts, shipped in two deploys. **Deploy 1 = Parts A, B, C.** They are independent of
each other and fix everything that is broken today. **Deploy 2 = Parts D, E.** Both need
Part A.

## Problem Statement

1. **No `/new-purchase` request on the EPIF path has ever produced an EPIF.** A requester
   picks "None of these — this will be an EPIF order", the card shows `(P-card)` or
   `(Req/PO)`, and at approval the bot treats it as Workday. It fills no EPIF, the thread
   says "Assigned to … to place in Workday", and the buyer gets the "Place this in
   Workday:" DM with no email draft and no file. Seen in production: rows 22–27 were all
   approved with `saved PDF: None`, and a P-card order on 2026-10-06 was assigned "to place
   in Workday". Cause: Screen 1's path is never written onto the posted card, and
   `interview.get_request_route` falls back to `workday`.
2. **Files sent to the buyer's DM will fail after the next deploy.** `files_upload_v2` is
   called with both `file=` and `content=` in `lifecycle._send_assignee_dm` (since ticket
   105, merged and not yet deployed) and in `lifecycle.upload_archived_bom` (already live;
   production log 2026-10-05: "Could not upload archived BOM 0022_Fisher-Scientific_BOM.xlsx:
   You cannot specify both the file and the content argument."). `slack_sdk` raises before
   sending anything. The tests miss it because their fake client accepts any arguments.
3. **A successful buyer DM leaves no trace in the log.** Only failures are logged, so
   nobody can tell from the log whether a buyer was told.
4. **The buyer's DM card shows only "item — vendor, price".** To act, the buyer has to open
   the thread.
5. **"Switch to EPIF" does not exist.** Ticket 42 was marked done by a PR that changed only
   the ticket file. A Workday request whose vendor turns out not to be on Workday has no way
   onto the EPIF path, although ADR 0007 decision 5 and the glossary say it does.

## Solution

**Part A — the path is read from the payment method (ADR 0018 decision 1).**
`get_request_route` returns `epif` for an uploaded file. Otherwise it returns `workday`
when the payment method is `Workday`, and `epif` for anything else. Nothing writes or reads
a `route` key on a request. The EPIF draft stops offering Workday.

**Part B — files go to Slack with one argument.** Both call sites pass `file=<path>` only.
Upload tests run Slack's real argument checks.

**Part C — the buyer DM logs its success.**

**Part D — the DM card shows the whole request (ADR 0018 decisions 2–3).** One function
builds the request lines for both cards. On the Workday path the DM card is the whole DM.

**Part E — Switch to EPIF, rebuilt** on Part A's rule.

## User Stories

### Part A
1. As a requester who picks "None of these — this will be an EPIF order", I want approval to fill in and archive the EPIF, so that the purchase can actually be emailed.
2. As a buyer assigned an EPIF-path request, I want the email-draft DM with the filled EPIF attached and the thread saying "to email to purchasing", so that I know to email it and not look for it on Workday.
3. As a buyer assigned a Workday-path request, I want exactly what I get today, so that nothing changes for Workday orders.
4. As an approver, I want a card posted before this deploy (Workday or EPIF) to be read correctly when I approve it, so that requests waiting at deploy time are not mis-routed.
5. As a buyer assigned an EPIF-path request after approval (picker or `@Purchasing assign`), I want the same EPIF DM, so that late assignment works the same as assignment at approval.
6. As a buyer, I want the EPIF draft to say "Send this email to purchasing", not "Submit via Workday or send this email", so that the instruction matches the path.
7. As a requester editing a posted card, I want the edit form to show the same path the approval will use, so that the two never disagree.

### Part B
8. As a buyer, I want the filled EPIF, the BOM and the quotes to actually arrive in my DM, so that I have everything to forward.
9. As a requester, I want the archived BOM posted to the thread at approval, so that the itemised order sits beside the conversation.

### Part C
10. As the developer, I want one INFO log line every time a buyer's DM is sent, naming the buyer, the row and the path, so that "the buyer got nothing" can be checked from the log.

### Part D
11. As a buyer on a Workday-path request, I want one DM, a card headed "Place this in Workday" with every field the thread card shows and the next-step button, so that I can place the order without opening the thread.
12. As a buyer on an EPIF-path request, I want the email draft with its attachments, then a card with every field the thread card shows, so that I can both email and track it from my DM.
13. As a buyer, I want the DM card to keep showing every field after each stage, reassignment, cancel or delivery, so that it stays readable.
14. As a buyer, I want the DM card's History to match the thread card's, so that I can see who did what.

### Part E
15. As a buyer who finds a Workday-path vendor is not on Workday, I want **Switch to EPIF** on the approved card, so that I can move it to the EPIF path without a second approval.
16. As that buyer, I want the switch to open the EPIF form pre-filled from the request, so that I only change what differs (payment method, vendor contact).
17. As the lab, I want the switch to rewrite the same workbook row and archive the filled EPIF in one write, so that there is one row per purchase.
18. As the assigned buyer, I want the EPIF DM after the switch, so that I have the file to email.
19. As anyone, I want the switch refused once the request is processed, so that a placed order's path never changes.

## Implementation Decisions

### Part A
- **`interview.get_request_route(payload, has_file=False) -> str`** becomes, in this order:
  `has_file` → `"epif"`. If `payload["parsed"]` is a dict, read `payment_method` from it;
  otherwise read it from `payload`. If it equals `config.WORKDAY_PAYMENT_METHOD` →
  `"workday"`. Anything else, `None` included → `"epif"`. It stays a pure function, so it
  can be tested with plain dicts. The `payload.get("route")` and `source == "epif"`
  branches are deleted.
- `get_request_route` is called with a request dict or a card payload; both shapes work
  (the `parsed` check above). Every existing call site stays as it is: `lifecycle.py`
  `write_action`, `on_success` (×2), the assignee-DM block in `finalize_purchase_request`,
  and `handle_assign`.
- **Delete the second records:** `lifecycle._finalize_bare_thread_epif`'s
  `parsed["route"] = "epif"` line, and the `"route": "workday"` key in the Fill-in-details
  `parsed` dict in `src/app.py` (that dict already sets `"payment_method": "Workday"`).
  Modal `private_metadata` keeps its `route` (Screen 1 → 2 → 3, and the Edit form's meta),
  because no payment method exists before Screen 2 is submitted.
- **Edit opener** (`src/app.py`, the handler that builds the Edit form's `meta` and today
  computes `route = "workday" if parsed.get("payment_method") == config.WORKDAY_PAYMENT_METHOD else "epif"`):
  replace that line with `route = interview.get_request_route(card_payload)`.
- **EPIF draft text**, `lifecycle._send_assignee_dm`, the non-Workday branch: the line
  beginning `1. Submit via Workday or send this email to purchasing` becomes
  `1. Send this email to purchasing`. The rest of the line is unchanged.
- Docstrings: `get_request_route` states the rule and cites ADR 0018. The
  `lifecycle.py` module docstring gains a `Per ADR 0018` paragraph.

### Part B
- `lifecycle._send_assignee_dm` (the `files_upload_v2` call in the DM-upload loop) and
  `lifecycle.upload_archived_bom` (its `kwargs`) pass `file=<path>` and **no** `content`.
  Delete the `open(...).read()` that only fed `content`. The legacy `files_upload`
  branches are unchanged.
- **Upload tests must run `slack_sdk`'s real argument checks.** Use a real
  `slack_sdk.WebClient(token="xoxb-test")` and patch only its three network methods
  (`files_getUploadURLExternal`, `_upload_file`, `files_completeUploadExternal`) to return
  canned results. This is a requirement because the bug is an argument combination that a
  `MagicMock` accepts and `slack_sdk` rejects. A `MagicMock` client does not count as
  proof for this part.

### Part C
- In `lifecycle._send_assignee_dm`, after the DM is posted successfully, log at INFO:
  `"📨 Buyer DM sent to %s for row %s (%s path)"` with `assignee_id`, `row`, `route`.
  After `slack_io.post_dm_card` returns a result, log at INFO
  `"📨 DM card posted to %s (card %s)"` with `assignee_id`, `card_ts`.
- Part D must keep both lines. On the Workday path, the first line is logged after the
  card is posted.

### Part D
- **One builder for the request lines.** Extract from `blocks.build_request_blocks` its
  `summary_lines` construction into a pure function
  `blocks.request_summary_lines(request: dict, state: str, requester: str | None = None, items: list | None = None, attachments: list | None = None) -> list[str]`.
  It returns the same lines `build_request_blocks` renders today, header included.
  `build_request_blocks` calls it. Its output for every existing state must be
  byte-identical to today's; the existing card tests prove that.
- **`blocks.build_dm_card_blocks`** gains `history: list | None = None` and
  `route: str = "workday"`. The section is:
  - line 1, on the Workday path: `🛒 *Place this in Workday*`;
  - line 1, on the EPIF path: `📧 *Email the EPIF to purchasing*`;
  - then `request_summary_lines(...)` minus their own header line;
  - then `• *Row:* {row}` when there is a row, `Stage: *{state}*`, the thread link, the
    expected-delivery line and the retired-state line exactly as today.

  The History renders as the same `context` block `build_request_blocks` uses. Buttons,
  picker and `block_id` are unchanged.
- **`lifecycle._send_assignee_dm`** gains `history: list | None = None` and passes
  `history` and `route` to `build_dm_card_blocks`.
  - Workday path: no `slack_io.tell`; the DM card is the only message. If `card_ts` is
    missing, fall back to `slack_io.tell` with the joined summary lines and log a WARNING
    "No card_ts; sent the Workday DM as text".
  - EPIF path: the draft `tell` and the uploads are unchanged, then the card.
- Callers pass history: `finalize_purchase_request` passes `hist`, and `handle_assign`
  passes `history`. `lifecycle.sync_dm_card` passes its `history` and
  `route = interview.get_request_route(request)` through to `build_dm_card_blocks`, so
  retired and stage-updated DM cards keep every field. `nudge._repost_dm_card` passes the
  same.

### Part E
- **Button.** `blocks.build_request_blocks("approved", …)` adds a `req_switch_epif` button,
  "Switch to EPIF", carrying the same `btn_value` as the other buttons. It appears only
  when `interview.get_request_route(request) == "workday"` and the payload has no
  `processed` date. The thread card only; the DM card does not get it.
- **Permission:** the same four-way check `handle_req_fill_details` in `src/app.py` uses
  (requester, assignee, any buyer while unassigned, admin). Extract it to
  `admin.can_fill_or_switch(user_id, req_data, requester_name, resolved_name) -> bool` and
  call it from both handlers. A refusal goes through `slack_io.deny(respond, …)`, and no
  `views_open` happens.
- **Form.** Open the interview's Screen 2 on the EPIF path (`blocks.build_stage2_view`
  with `meta["route"] = "epif"`), pre-filled from the card's `parsed` like the Edit
  opener does. `meta` carries a `switch` context
  `{channel, thread_ts, card_ts, row, approver?, assignee_id, assignee_name}`.
  `_process_interview_completion` hands a `switch` context to a new
  `lifecycle._finalize_switch_to_epif`, the way it hands `bare_thread` to
  `_finalize_bare_thread_epif`. No new card is posted.
- **Write.** One `queue_worker.submit_write_task`. Inside it:
  1. Re-read the row with `log_writer.get_row_info`. If Date Processed (column U) is set,
     raise a refusal; the actor is DM'd through `slack_io.notify` "Already processed —
     the path can't change now." and nothing is written.
  2. `log_writer.update_row(row, values)`, where `values` is `log_writer.build_row(new_parsed, requester)`
     minus columns B (requester), M (date of request), U, V, W, X and Y.
  3. Fill and archive the EPIF exactly as `finalize_purchase_request.write_action` does
     for the EPIF path (`epif_filler.fill_epif`, `log_writer.epif_archive_name`,
     `log_writer.save_epif`). If that raises, write the old values back with `update_row`
     and re-raise.
- **On success:** update the thread card with `parsed` replaced by the new request
  (payment method is now P-card or Req/PO, so the path reads `epif`) and
  `epif_file` set. Post `🔁 Switched to EPIF by {name}` in the thread and append it to
  History. If assigned, call `_send_assignee_dm` on the EPIF path (draft + EPIF + card)
  after retiring the old DM card with `sync_dm_card(state="replaced", note="Switched to EPIF")`.
- **Ticket 42's file** stays as history. The new ticket supersedes it, and its comment
  records that PR #61 shipped no code.

## Testing Decisions

- Tests check what a person sees: thread replies and their text, DMs and who received
  them, files uploaded and their names, rows on a temporary workbook copy, files in
  temporary `EPIFS_DIR` / `BOMS_DIR` / `QUOTES_DIR`. ADR 0001: tests first; every new test
  must fail on today's code.
- **The Part A regression test starts from the real interview, not a hand-built dict.**
  It calls `lifecycle._process_interview_completion` with Screen 1 meta built by
  `interview.route_vendor(config.VENDOR_OTHER_OPTION)` and a Screen 2 dict with
  `payment_method="P-card"`. It takes the **Approve button's `value`** off the posted
  card's blocks and passes its `request` to `lifecycle.handle_epif_processing(posted_payload=…, card_ts=…)`
  with a buyer set. It asserts:
  - exactly one PDF in `EPIFS_DIR`, and `epif_parser.parse_epif` on it returns the
    request's vendor and amount;
  - the thread line contains "to email to purchasing";
  - the buyer's DM contains "Send this email to purchasing";
  - an upload to the buyer names that PDF.

  A second case uses a listed vendor and asserts no PDF, "to place in Workday" and no
  upload. This is required because the bug lived exactly between posting and approval,
  which every earlier test skipped.
- The same test drives `handle_assign` on the approved card for a late assignment
  (story 5).
- `get_request_route` is tested directly: `Workday`, `P-card`, `Req/PO`, `None`, a payload
  with and without `parsed`, `has_file=True`, and a payload carrying a stale `route` key
  that must be ignored.
- **Rewritten in place, same test names. Deletes tests: none.**
  - `tests/test_45_epif_approval_archives.py`: `_valid_request` sets `payment_method`
    (`"P-card"` for the EPIF case, `"Workday"` for the Workday case) instead of `route`.
  - `tests/test_46_epif_path_dm_attaches_epif.py::test_handle_assign_uploads_epif`: drop
    the `monkeypatch.setattr(interview, "get_request_route", …)` line and give the
    request `payment_method="P-card"`.
  - Every other test whose request dict carries `"route":` sets the matching payment
    method: `tests/test_30_buyers_dm_carries_bom.py`, `tests/test_105_batch_files.py`.
    Modal `meta` dicts keep `route` (for example `tests/test_109_pcard_limit.py`'s
    `_sample_stage1_meta`).
- Part B: a test per call site with the real `WebClient` described above, asserting one
  upload with the right filename and no exception. On today's code it fails with
  `SlackRequestError`.
- Part C: `caplog` at INFO asserts the line names the buyer's id, the row and the path,
  for one Workday and one EPIF approval.
- Part D: build both cards from one request and assert every line of
  `request_summary_lines` appears in the DM card's section text. Assert the History
  context block matches. Assert the Workday header, the EPIF header, and that the Workday
  path sends exactly one DM message (the card, with `blocks`) and no plain-text `tell`.
  Existing tests that assert the old "Place this in Workday:" text DM
  (`tests/test_38_workday_path_approval.py`) are rewritten in place to assert the card.
- Part E: the button is absent for each of: not approved, path `epif`, processed. Permission
  denial leaves no `views_open` and the workbook unchanged. A processed-between-click-and-write
  test leaves the row byte-identical and `EPIFS_DIR` empty. Success: same row number, same
  row count, requester cell unchanged, payment-method cell now P-card, one EPIF archived,
  thread line posted, the buyer's DM has the upload.
- May fake: the Slack client (except Part B), file downloads, the lock queue (run
  synchronously, as `tests/test_45_epif_approval_archives.py`'s `sync_queue` does). Must be
  real: `interview`, `epif_filler` on `tests/fixtures/EPIF_TEMPLATE_HIRST.pdf`,
  `epif_parser`, `validators`, `log_writer` on a temp workbook copy.
- Prior art: `tests/test_45_epif_approval_archives.py` (fixtures), `tests/test_41_this_needs_an_epif.py`
  (interview with a context that finalizes against an existing card),
  `tests/test_67_dm_card.py`, `tests/test_29_approval_archives_bom.py`.

## Human tasks

- **Before deploy 1:** run `@Purchasing health` on the server and confirm
  `EPIF_TEMPLATE_PATH` points at the PDF itself, not the `_TEMPLATE` folder (the log
  flagged the folder on 2026-09-28).
- **Deploy 1** once A, B and C are merged (`@Purchasing update`). This also ships tickets
  99–110, which are merged but not yet live.
- Requests already approved on the EPIF path with no EPIF (check rows 25 and 27's payment
  method) are filled and sent to the buyer by hand.
- Approve the waiting P-card requests posted before deploy 1 only after it.
- **Deploy 2** once D and E are merged.

## Out of Scope

- Changing how Approve reads the buyer picker. The production screenshots show assignment
  at approval works.
- A keyword or tool to repair requests already approved without an EPIF (done by hand).
- The legacy `files_upload` fallback branches.
- The ticket-engine change that should have refused ticket 42's empty PR (taken to
  ticket-engine separately).
- Counting quotes, decline reasons, anything in the nudge schedule beyond passing history
  and path to `_repost_dm_card`.
