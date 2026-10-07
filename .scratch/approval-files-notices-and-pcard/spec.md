# Spec — Approval reads the right files, one rule for who is told, P-card under $5,000

**Status:** ready-for-agent
**Binding:** `docs/adr/0015-approval-reads-the-card-or-the-threads-files-by-role.md`,
`docs/adr/0016-one-rule-for-who-is-told.md`,
`docs/adr/0017-p-card-under-5000-req-po-at-5000-and-over.md`,
`docs/adr/0012-attached-boms-and-quotes-are-carried-not-read.md`,
`docs/adr/0010-linked-cards-and-direct-message-help.md` (decision 1: every approval leaves
a card; decision 5: the bot never guesses), `docs/adr/0003-decline-and-cancel.md`,
`docs/adr/0001-tests-first-and-no-muted-failures.md`
**Glossary:** `CONTEXT.md` — **Request**, **EPIF**, **Quote**, **Thread files at approval**
(new), **Batch**, **Decline**, **P-card** (new), **Req/PO** (new), **Superseded**,
**Bare-thread approval**

Three parts. Each can be built and landed on its own; within a part, the order below is
the order of dependency.

## Problem Statement

1. **A quote blocks approval.** A request submitted through `/new-purchase` with a quote
   attached cannot be approved: the bot re-posts the quote in the thread, and when the
   approver presses **Approve** the bot takes "the newest PDF in the thread" as the EPIF,
   tries to read the quote as a form, fails, and approves nothing. The same happens to
   `@Purchasing approved` in any thread where someone dropped a quote PDF.
2. **Errors reach the wrong person, or nobody.** That failure's DM went to the bot
   itself, because the bot "posted" the PDF. Each request-related DM picks its recipient
   its own way. A declined requester is told nothing at all.
3. **Requesters don't know P-card from Req/PO.** The form offers the choice with no
   explanation, and nothing stops a P-card order of $5,000 or more, which purchasing
   will not accept.

## Solution

**Part A — approval reads the right files (ADR 0015).** The Approve button approves the
card it is on and never searches the thread. Dropping an EPIF in a thread no longer posts
an Approve card; the bot replies "EPIF read: … Waiting for approval." and the card appears
at `@Purchasing approved`. At that keyword the bot takes the thread's files by type: EPIF
(a PDF with the EPIF form fields), BOM (`.xlsx`/`.csv`), quote (any other PDF), skipping
images and its own files. Several EPIFs are a batch.

**Part B — one rule for who is told (ADR 0016).** One `slack_io` function sends every
request-related error, refusal and decline DM: to the person who acted, plus the requester
when the fix is theirs, never to a bot, always with a thread link. Decline DMs the
requester.

**Part C — P-card under $5,000 (ADR 0017).** `validators.validate` refuses a P-card at
$5,000.00 or more on every form and on uploaded EPIFs. A hint under the Payment Method
dropdown explains the two, and the FAQ answers are replaced.

## User Stories

### Part A
1. As an approver, I want **Approve** on a `/new-purchase` card with quotes attached to approve that card, so that a quote never blocks an approval.
2. As an approver, I want **Approve** to use the card I clicked even when someone dropped another PDF in the thread, so that I approve exactly what I read.
3. As an approver, I want **Approve** on a card that was posted from a dropped EPIF before this change to still work, so that requests in flight at deploy are not stranded.
4. As a requester who drops an EPIF in a thread, I want a plain reply "📄 EPIF read: *{item}* — {vendor}, ${total}. Waiting for approval." and no buttons, so that I know the bot read it and that approval is next.
5. As a requester who drops a flattened or incomplete EPIF, I want the problem in that reply and in a DM, so that I fix it before anyone approves.
6. As an approver, I want `@Purchasing approved` in a thread with a dropped EPIF to post the card already approved, as today's bare-thread approval does, so that the card exists from approval on.
7. As an approver, I want `@Purchasing approved` in a thread that holds a posted `/new-purchase` card to approve that card, exactly as the button would, so that the keyword and the button do the same thing.
8. As a requester, I want the quote PDFs I dropped in the thread archived and sent to the buyer at approval, without typing `@Purchasing quote`, so that my quotes travel with the request.
9. As a requester, I want a `.xlsx` or `.csv` I dropped in the thread treated as my BOM at approval, so that I can give a BOM without the form.
10. As an approver, I want two BOM files in a thread refused with "One BOM per EPIF — delete the extra and approve again." naming both, so that the bot never picks one.
11. As a requester, I want screenshots and images in the thread ignored at approval, so that a Workday cart screenshot is not archived as a quote.
12. As a requester who uploaded a corrected EPIF, I want only the newest EPIF of mine for that vendor used, so that my earlier draft is not ordered too.
13. As an approver, I want EPIFs for different vendors in one thread approved as a batch — one row and one card each — so that a multi-vendor order works.
14. As an approver, I want a batch with a BOM file refused with the ADR 0015 decision 5 text, so that a BOM is never attached to the wrong EPIF.
15. As a buyer, I want a quote saved earlier with `@Purchasing quote` not archived a second time at approval, so that the Quotes folder has no duplicates.
16. As an admin, I want a dropped EPIF that is never approved to leave no request-log entry, so that the log holds only real requests.

### Part B
17. As an approver whose approval fails, I want the DM to reach me and not the bot, so that I know it failed.
18. As a requester whose EPIF is flattened, incomplete, or a P-card at $5,000+, I want a DM telling me what to fix, so that I don't wait on an approval that can't happen.
19. As a requester, I want no DM about failures I can't fix, so that I'm not alarmed by the approver's or the bot's problems.
20. As anyone receiving an error DM, I want a link to the thread in it, so that I can go straight to the request.
21. As a requester whose request is declined, I want a DM "Your request for *{item}* ({vendor}, ${total}) was declined by {name}. Any discussion is in the thread: {link}", so that I'm not left waiting.
22. As an approver who declines my own request, I want one DM, not two, so that the bot doesn't repeat itself.

### Part C
23. As a requester, I want a hint under Payment Method explaining P-card vs Req/PO, the $5,000 line and the three quotes, so that I pick correctly.
24. As a requester who picks P-card for $5,000.00 or more, I want the form refused with "P-card is for orders under $5,000. Pick Req/PO.", so that purchasing doesn't bounce it later.
25. As a requester who uploads an EPIF with P-card ticked at $5,000+, I want the same message in the "EPIF read" reply and a refusal at approval, so that both paths follow one rule.
26. As a requester ordering under $5,000 from a vendor that needs a PO, I want Req/PO accepted with no warning.
27. As a requester asking the bot "what is a p-card" / "req/po", I want the same explanation as the hint.

## Implementation Decisions

### Part A
- **Button path.** In `lifecycle.handle_epif_processing`, when `card_ts` or
  `posted_payload` is given, the thread search (`slack_io.find_epif_in_thread`) is not
  called, with one exception: a payload with `source == "epif"` (a card from before this
  change) uses the new thread search below. `direct_file` still
  comes first. The docstring's resolution order is rewritten to match.
- **What is an EPIF.** A pure function in `epif_parser`, `is_epif_form(fields: dict) ->
  bool`: true when `Amount of Purchase` and `Vendor` are both field names. It is pure so
  it can be tested without Slack or a real PDF.
- **Thread classifier.** A pure function in `slack_io` (it handles Slack message dicts,
  no client): `classify_thread_files(messages, bot_user_id, read_fields) ->
  ThreadFiles` with `epifs`, `bom_files`, `quotes`, `flattened_epif_named` lists. It
  skips messages whose `user` is `bot_user_id` or that carry `bot_id`; `read_fields` is
  injected (the downloaded-PDF → field-dict reader) so tests pass a fake. It is pure
  because the approval handler and the drop handler both need it and it is the piece most
  worth testing in isolation. `find_epif_in_thread` is replaced by a thin wrapper that
  fetches replies and calls it.
- **Drop.** `lifecycle.handle_epif_drop` keeps parsing and validating but posts the plain
  "EPIF read" reply (story 4 text) instead of a card, creates no request-log entry, and
  runs no superseding. Problems go out through Part B's notice function (or, if Part B has
  not landed, the existing reply + `tell`).
- **Keyword path.** `@Purchasing approved` (the `handle_epif_processing` call in
  `src/app.py`'s mention handler): if `slack_io.find_card_in_thread` finds a card in the
  `posted` state, approve it as the button does. Otherwise classify the thread: one EPIF →
  today's EPIF finalize path; several → batch; none → today's bare-thread approval. BOM
  and quotes from the classifier become the request's `attachments` with roles `bom` /
  `quote` and go through the existing ADR 0012 archive/DM code.
- **Collapse.** EPIFs with the same `(uploader user id, vendor.strip().lower())` collapse
  to the newest by message `ts`.
- **Request log** for a dropped EPIF is created inside the approval finalize, after the
  card is posted.

### Part B
- New `slack_io.notify(client, *, actor_id, requester_id=None, requester_fix=False,
  text, channel, link_ts)`. Recipients: `actor_id`; plus `requester_id` when
  `requester_fix`; minus the bot's own user id; de-duplicated; if empty, `actor_id`.
  Appends `\n<{permalink}|Open the thread>` from `chat_getPermalink(channel=channel,
  message_ts=link_ts)`; a permalink failure sends the DM without the link and logs a
  warning.
- The bot's own user id: `slack_io.bot_user_id(client)` with the cached `auth_test`
  lookup moved from `app.get_bot_user_id`, which now calls it.
- Moved to `notify`: the `tell` calls in `lifecycle.py` at the validation-failure path
  of `finalize_purchase_request`, the parse-failure paths of `handle_epif_processing`
  and `handle_epif_drop`, the attachment-failure path of `post_attachments_to_thread`,
  and the already-approved refusal in the line-items edit path. `requester_fix=True` for
  parse failures, validation failures and attachment failures; `False` otherwise.
  The assignee's email-draft DM and the submission confirmation are not error notices and
  are unchanged.
- Decline: `handle_decline` calls `notify` with `actor_id` = the decliner,
  `requester_id` from the card payload's `user_id`, `requester_fix=True` (so the
  requester always gets it), and the story 21 text.

### Part C
- `config.PCARD_LIMIT = 5000.00`. In `validators.validate`, after the payment-method
  check: `payment_method` equal to `"P-card"` (case-insensitive; the EPIF parser's value
  for the PCard box included) and `total_price >= config.PCARD_LIMIT` → append
  "P-card is for orders under $5,000. Pick Req/PO."
- `config.PAYMENT_METHOD_HINT` holds the ADR 0017 decision 4 text verbatim. `blocks.py`'s
  Payment Method input block gets `"hint": {"type": "plain_text", "text":
  config.PAYMENT_METHOD_HINT}`. `interview.FAQ_ANSWERS["p-card"]`, `["req/po"]` and
  `["req po"]` all equal it.

## Testing Decisions

- Tests check what a person sees: thread replies and their text, DMs and who received
  them, the card posted (or not), rows written (or not) on a temporary workbook copy,
  files archived into temporary `EPIFS_DIR` / `QUOTES_DIR` / `BOMS_DIR`. Asserting a mock
  was called is not enough. ADR 0001: tests first.
- **The regression test for the bug** drives `handle_req_approve_action` with a fake
  client whose thread holds a `/new-purchase` card and a bot-posted PDF with **no form
  fields** named `Quote 27732 University of Wisconsin.pdf`. It asserts a row is written
  from the card's values, no "Error processing" reply is posted, and no DM goes to the
  bot's user id. Use a real field-less PDF fixture, not a mocked parser.
- `classify_thread_files` and `is_epif_form` are tested directly with message dicts and a
  fake `read_fields`, covering every row of the ADR 0015 decision 4 table, bot-posted
  skipping, flattened-but-named-epif, collapse, two BOMs.
- `test_14_approve_payload.py` case 2 ("PDF in thread beats posted_payload") is rewritten
  in place under the same test name to assert the card wins.
- `notify` is tested with a fake client: actor only; actor + requester; requester ==
  actor (one DM); actor == bot id (falls back correctly); permalink failure.
- May fake: the Slack client, file downloads (return fixture bytes), the lock queue. Must
  be real: the classifier, the EPIF parser on fixture PDFs, `validators.validate`, the
  workbook write on a temp copy, archive naming.
- Prior art: `tests/test_14_approve_payload.py`, `tests/test_40_bare_thread_approval.py`,
  `tests/test_29_approval_archives_bom.py`, and the ADR 0012 tests in
  `.scratch/attached-boms-and-quotes/`.

## Out of Scope

- Removing the PDF-born **Add items** / **Edit** handlers and the superseding code (kept
  for cards posted before this change).
- Counting quotes for Req/PO orders.
- DMs that are not about a request (roster, admin, nudge settings).
- Reading inside quotes or BOMs.
- Approving or cancelling the 2026-10-05 tungsten request — handled by hand.
- Adding a decline reason.
