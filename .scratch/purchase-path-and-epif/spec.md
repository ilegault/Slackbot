# Spec — the purchase path, bare-thread approval, and the filled EPIF

**Status:** `ready-for-agent`

Written 2026-09-23. Covers ticket set **34 onward**. Convert to tickets in the order
the Implementation Decisions section is written. Each numbered decision block is one
seam, and the dependencies between them are stated in the block.

Read before implementing anything here:

- `CONTEXT.md` — the glossary. **Workday path / EPIF path** is rewritten, and
  **Vendor list**, **Filled EPIF**, **Bare-thread approval** and **Waiting for
  details** are new. Every word below is used as it defines them.
- `docs/adr/0007-purchase-path-and-generated-epif.md` — **the decision record for this
  whole set. Binding.**
- `docs/adr/0001-tests-first-and-no-muted-failures.md` — binding on all test work.
- `docs/adr/0006-bom-line-items-and-editable-posted-cards.md` — the BOM, the
  assignee DM, and edits to posted cards, all of which this set touches.
- `docs/adr/0003-decline-and-cancel.md`, `0004`, `0005` — cancel and assignment,
  which gain a new state here.

---

## Problem Statement

Isaac orders a $17.10 breakout board from Winford using the App Home **New purchase**
button. Winford is not a Workday vendor, so he picks **Not listed / other**, expecting
the bot to turn his answers into an EPIF and hand it to whoever does the ordering.
Charlie approves. The bot logs row 20 and replies *"Assigned to Dylan to process in
Workday / ShopUW."* Dylan's DM says *"Attached is the filled out EPIF"*, but nothing is
attached. No EPIF exists anywhere. Dylan now has to fill in an EPIF by hand from the
card, which is what the interview was supposed to save him.

Choosing "not listed" changed almost nothing. It retitled one modal screen and asked
for a payment method. After approval, a Workday order and an EPIF order look
identical, and both are told to go to Workday.

Around that are three smaller problems:

- **Suggest a new vendor that was added to workday** sends the student down the EPIF
  path, even though the option says the vendor *is* on Workday.
- The most common Workday order is a thread with a screenshot and a link, and Charlie
  says "approved". The bot can't approve that. It answers *"I couldn't find a PDF or
  purchase request"*, so nothing is logged.
- EPIFs are archived under whatever name the student gave the file, so the `EPIFs/`
  folder can't be scanned by eye.

## Solution

A request is on exactly one of two paths, and each path does what its name says.

- **Workday path.** The vendor is on the vendor list. The buyer places the order in
  Workday. No EPIF is generated and no email is drafted. The buyer's DM is a short
  summary: item, vendor, price, link, row. The thread says "to place in Workday".
- **EPIF path.** The vendor is not on the list. At approval, the bot fills in the
  lab's blank EPIF from the request, archives it under a readable name, and DMs it to
  the assigned buyer with the email draft (and the BOM, if there is one). The buyer
  emails purchasing. The thread says "to email to purchasing".

In the interview, the vendor pick decides the path. The last option says plainly
*"None of these — this will be an EPIF order"*. If the typed name is really a vendor
already on the list, the bot warns once and points the student to it. The "suggest a
new vendor" option is removed. Admins add vendors with `@p-bot add-vendor <name>`,
and App Home says so.

In a thread, an uploaded EPIF works exactly as today. A thread with no EPIF and no
form card can now be approved as a **Workday order**. The bot says so in one reply
and asks the thread's starter to fill in the details. If it turns out the vendor
isn't on Workday, the requester or buyer presses **This needs an EPIF** and goes
through the EPIF interview. Charlie is never asked to approve twice. A Workday
request can switch to EPIF until it is processed.

## User Stories

1. As a requester, I want picking a vendor from the list to mean a Workday order, so that I know no paperwork is coming.
2. As a requester, I want the last vendor option to say "None of these — this will be an EPIF order", so that I understand what choosing it does.
3. As a requester who picked "None of these", I want the bot to fill in the EPIF for me from my answers, so that I never open the PDF form.
4. As a requester who typed "fisher scientific" under "None of these", I want to be told "Did you mean Fisher Scientific? Pick it from the list", so that I don't create an EPIF for a Workday vendor by mistake.
5. As a requester whose vendor really is different from a similar-looking listed one, I want to submit again past the warning, so that the check never traps me.
6. As a requester, I want the "suggest a new vendor" option gone, so that I can't accidentally send a Workday vendor down the EPIF path.
7. As a requester whose vendor is on Workday but not in the bot's list, I want App Home to tell me to ask an admin to add it, so that I know the right route.
8. As an admin, I want `@p-bot add-vendor <name>`, so that I can add a Workday vendor from Slack the same way I remove one.
9. As an admin, I want `add-vendor` to refuse a name that's already listed (ignoring case), so that the list doesn't get duplicates.
10. As a non-admin, I want `add-vendor` to deny me privately, so that the vendor list stays admin-managed.
11. As Charlie, I want to type "approved" on a thread that only has a screenshot and a link, so that ordinary Workday orders need nothing more from me.
12. As Charlie, I want the bot to say plainly that it is treating a no-EPIF thread as a Workday order, so that nobody is surprised by the path it took.
13. As the person who started a bare thread, I want to be named as the requester and pinged to fill in the details, so that the row carries the right name.
14. As a requester after a bare-thread approval, I want a **Fill in details** button that opens a short Workday form, so that the order gets logged without Charlie approving again.
15. As a requester after a bare-thread approval, I want a **This needs an EPIF** button, so that a non-Workday order can still get its EPIF.
16. As a buyer, I want to be able to press those same buttons (the assignee, or any buyer while it's unassigned), so that I can sort out the details with the requester.
17. As an admin, I want to be able to press them too, so that I can unstick a request.
18. As anyone else, I want a private denial when I press them, so that a stranger can't write a row.
19. As anyone reading the channel, I want the card to say "Approved — waiting for details" and show no stage buttons, so that nobody marks unlogged work as processed.
20. As an approver or admin, I want Cancel on a card that's waiting for details to simply close the card, so that an abandoned bare-thread request goes away cleanly without touching the workbook.
21. As Charlie, I want my one approval to cover whichever path the request ends up on, so that I'm never asked twice for the same purchase.
22. As a buyer who opens Workday and finds the vendor isn't there, I want to switch an approved Workday request to EPIF before it's processed, so that I can still order it without cancelling.
23. As a buyer, I want the switch to rewrite the same row rather than add a new one, so that the log has one row per purchase.
24. As anyone, I want the switch refused once the request is processed, so that the path of an order already sent is never rewritten.
25. As an assigned buyer on an EPIF order, I want the filled EPIF attached to my DM along with the email draft, so that I can email purchasing straight away.
26. As an assigned buyer on an EPIF order with a BOM, I want the EPIF and BOM together in my DM, so that I send one complete email.
27. As an assigned buyer on a Workday order, I want a short DM with the item, vendor, price, link and row and no email draft, so that I'm not told to email anyone.
28. As an assigned buyer, I want the thread line to say "to place in Workday" or "to email to purchasing", so that the channel shows what's actually going to happen.
29. As the purchasing office, I want the filled EPIF to carry Charles Hirst as PI of Funding and end user, so that it matches every EPIF the lab already sends.
30. As the purchasing office, I want a multi-item EPIF to say "See attached BOM — N items" with the BOM total as the amount, so that the EPIF and the BOM agree.
31. As a lab member browsing `EPIFs/`, I want every archived EPIF named `<vendor>_EPIF_$<price>_<project id>.pdf`, so that I can find one by eye.
32. As a lab member, I want an uploaded EPIF archived under that same naming rule, so that the folder uses one convention whichever way the EPIF arrived.
33. As a lab member, I want a second EPIF with the same name saved as `…_2.pdf` rather than overwriting the first, so that no EPIF is ever lost.
34. As the admin running the server, I want a startup alert if the `EPIF_TEMPLATE_HIRST` blank is missing, so that I find out before the first EPIF approval fails.
35. As the admin, I want EPIF generation to fail loudly (thread + requester DM + alert channel) and leave nothing half-written, so that a missing template never produces a row with no EPIF.
36. As a requester who edited a posted card, I want the EPIF generated from the final version at approval, so that purchasing never receives a stale form.

## Implementation Decisions

The numbered blocks are seams, in dependency order.

### 1. The vendor list, the interview's first screen, and `add-vendor`

*No dependencies.*

- The config constant for the suggest option, and every branch that reads it (interview
  validation, the parsed-dict builder, the Screen 1 builder, the "suggested new vendor"
  note on the posted card), are deleted. The other-option constant keeps its role, with
  its label changed to **"None of these — this will be an EPIF order"**. Its stored
  value is the label. No path is ever decided by comparing labels. The path is always
  decided by `interview.route_vendor`, which returns `workday` exactly when the choice
  is on the vendor list.
- **Near-miss check**, a new pure function in `interview`:
  `find_similar_listed_vendor(typed: str, listed: Iterable[str]) -> str | None`.
  Both sides are normalised: lowercase; punctuation and whitespace removed; trailing
  corporate suffixes (`inc`, `llc`, `ltd`, `co`, `corp`, `corporation`, `company`)
  dropped. It returns the listed name when the normalised strings are equal, or when
  `difflib.SequenceMatcher` ratio ≥ 0.85. Otherwise it returns `None`. It is pure
  (no Slack, no roster read), so it can be tested on strings.
- **The warning is shown once.** Screen 1 validation calls the check. On a hit, and
  only if Screen 1's private metadata does not already record a warning for this exact
  typed name, the bot returns a field error on the custom-vendor block: *"Did you mean
  X? Pick it from the list — it's a Workday vendor. Submit again to keep this as an
  EPIF order."* It also records the typed name in the metadata. Submitting again with
  the same name proceeds on the EPIF path.
- **`@p-bot add-vendor <name>`** is a new admin keyword with its own keyword tuple
  (`add vendor`, `add-vendor`), mirroring `remove-vendor`. It is admin-only; others get
  the standard denial. It rejects an empty name with the same usage hint shape as
  remove. A name already on the list (ignoring case) is refused with *"already on the
  list"*. On success the name is added through the roster's existing add-vendor
  function, confirmed in-thread, and logged. The keyword is listed with the admin ops
  wherever those are documented.
- **App Home and `/purchasing-help`** gain one line: *"Vendor not in the list but you
  know it's on Workday? Ask an admin to add it (`@p-bot add-vendor`)."* Both surfaces
  read it from their single shared source (ticket 09 made them one source). Do not add
  a second copy.
- The alert-channel **Approve Vendor** flow now has no trigger. Its action handler and
  the ops function stay, because `add-vendor` reuses the ops function. Nothing new
  posts that alert.

### 2. The filled EPIF, and one naming rule for every archived EPIF

*No dependencies. Can be built in parallel with 1.*

- **`epif_filler`**, a new domain module (pure, no Slack, no filesystem):
  `fill_epif(template_bytes: bytes, parsed: dict) -> bytes`. It writes every field that
  `epif_parser.parse_epif` reads back into the matching AcroForm field of the template,
  using `pypdf`, which is already a dependency. It sets exactly one category checkbox
  and exactly one payment checkbox. It writes **PI of Funding** and **Name** as the
  constant `EPIF_PI_AND_END_USER = "Charles Hirst"` in `config`. Template fields with
  no source value are left blank. The field names come from the config maps the parser
  already uses, so the reader and the writer can never disagree about a name. It must
  be pure, because the only proof the PDF is right is a byte-level round trip in tests.
- **The fill runs on the request's final state:** at approval on an EPIF-path request,
  and at the Workday→EPIF switch (block 4). It never runs at submit, because a posted
  card can still be edited (ADR 0006 decision 8).
- **With two or more line items**, *What is being purchased* is
  `See attached BOM — N items`, and *Amount of Purchase* is the BOM total including
  shipping. That total already equals the request total, by ADR 0006 decision 4.
- **Template source:** `config.EPIF_TEMPLATE_PATH`. It defaults to `EPIF_TEMPLATE_HIRST.pdf`
  inside the existing template directory, and can be overridden by environment
  variable like the other paths. The startup storage check gains this entry as a
  **file**, reported the same way as the others.
- **Naming**, a new pure function in `log_writer`:
  `epif_archive_name(vendor: str, total_price: float, project_id: str, existing: Iterable[str]) -> str`.
  The result is `<vendor>_EPIF_$<price>_<project id>.pdf`. The price is formatted
  with two decimals and no thousands separator (`$1234.50`). The vendor has the
  characters Windows forbids (`<>:"/\|?*`) removed, and whitespace runs collapsed to
  single spaces. If the name is already in `existing`, `_2`, `_3`, … is inserted before
  `.pdf`. The saving function passes the names already in `EPIFS_DIR` and never
  overwrites.
- **The same name is used for an EPIF uploaded to a thread**, computed from its parsed
  vendor, amount and project ID. The copy in Slack is not renamed. This replaces the
  row-number prefix scheme the lifecycle spec described for EPIFs. The BOM keeps
  `NNNN_<Vendor>_BOM.xlsx`, and the row's Notes line for the BOM is unchanged.
- **Generation happens inside the same queued write task as the row append**
  (invariant 2, all-or-nothing). If the template is missing or unreadable, the task
  fails. No row is written, and the failure goes to thread, requester and alert
  channel, as for any write failure.

### 3. Path-aware approval messages and the assignee DM

*Blocked by 2 (the EPIF path's DM carries the file).*

- Every "to process in Workday / ShopUW" string goes, replaced by the request's path:
  - Workday: `👤 Assigned to @X (Name) to place in Workday.`
  - EPIF: `👤 Assigned to @X (Name) to email to purchasing.`
  - The unassigned line becomes `Needs a buyer to place in Workday.` or
    `Needs a buyer to email to purchasing.`
- **The path is read from the request payload's `route` field**, which the interview
  already records. A request with no `route` is on the EPIF path if it came from an
  uploaded EPIF, and on the Workday path otherwise. That covers old cards in flight.
  The rule is one function, used by every caller.
- **EPIF-path assignee DM:** the existing email draft plus the filled (or uploaded)
  EPIF uploaded to the DM with the same upload helper the BOM uses. The BOM follows
  if there is one. The draft's "Attached is the filled out EPIF" is now true.
- **Workday-path assignee DM:** `Place this in Workday:` followed by item, vendor,
  price, link and row. No email draft. It still points to the card's buttons for
  processed / confirmed / delivered.
- These DMs are sent wherever assignment happens today: at approval with an assignee,
  and on a later assign. There is one implementation (invariant 1).

### 4. Bare-thread approval, waiting for details, and the switch to EPIF

*Blocked by 2 and 3.*

- **Bare-thread approval.** When approval finds no EPIF PDF, no card payload and no
  interview metadata in the thread, it no longer answers "couldn't find a PDF". It:
  1. resolves the **requester** as the author of the thread's parent message (roster
     lookup, the same as for an uploaded EPIF);
  2. posts **one** thread reply:
     > ✅ Approved by {approver}. No EPIF in this thread, so I'm treating this as a
     > **Workday order**. <@requester>, please fill in the details so it can be
     > logged. If this vendor isn't on Workday, press **This needs an EPIF** instead.
  3. posts a card in state **`waiting_for_details`**, carrying the requester, the
     approver, any assignee named in the approval (same mention rules as ADR 0004,
     including "a refused assignment never refuses the approval"), and the history
     line `Approved by … on …`.
  4. writes **nothing** to the workbook.
- **The card in `waiting_for_details`** reads "Approved — waiting for details" and has
  exactly three buttons: **Fill in details**, **This needs an EPIF**, **Cancel**. It
  has no stage buttons and no buyer picker. Assignment by keyword still works on it.
  The state is serialised in the card like every other state (invariant 3). No new
  store.
- **Permission for Fill in details / This needs an EPIF:** the requester, the current
  assignee, any buyer while unassigned, or an admin. Anyone else gets an ephemeral
  denial and nothing else happens.
- **Fill in details** opens a single-screen **Workday details** modal. The vendor is a
  select limited to the vendor list, followed by item, purpose, link, total price,
  date, delivery room, project ID, fund, category, and the same optional line-items
  box. On submit, the same validator as the interview runs. The row is then written
  through the existing finalize path with `route = workday`, as if approval had just
  happened with this payload. The card becomes an ordinary `approved` card, and the
  Workday DM goes to the assignee if there is one. Approval is **not** asked for again.
- **This needs an EPIF** opens the interview at Screen 2 on the EPIF path. It keeps the
  bare-thread context in the private metadata (channel, thread, card ts, requester,
  approver, assignee). The vendor is typed on the first screen shown. On completion it
  does **not** post a new posted card. It writes the row with `route = epif` and
  generates the EPIF (block 2) in the same queued task, turns the card into an
  ordinary `approved` card, and sends the EPIF DM (block 3).
- **Cancel on `waiting_for_details`**: an approver or admin, as for any cancel. It
  writes nothing, because there is no row. The card becomes terminal with
  `🚫 Cancelled by …` and no buttons, and one thread line is posted.
- **Switch to EPIF on an approved Workday request.** An approved card with
  `route = workday` and no *Date Processed* gains a **Switch to EPIF** button. The same
  people as above may press it. It opens the EPIF-path interview pre-filled from the
  row's payload, with the vendor editable. On submit, **the same row** is rewritten
  (vendor, payment method, and every detail field; the requester and dates are
  untouched) through `log_writer` and the queue. The EPIF is generated in the same
  task, the card's `route` becomes `epif`, one thread line records
  `🔁 Switched to EPIF by …`, and the EPIF DM goes to the assignee. The switch is
  refused if *Date Processed* is set when the task runs. That is checked inside the
  queued task, not only at click time.

## Testing Decisions

Test behaviour, not shape (AGENTS.md §8). A good test here sets up a situation the lab
would actually hit, runs it through the real entry point, and asserts on what the bot
**sent** and what the **workbook** holds. It also asserts the *absence* of the thing
that must not happen: no row, no DM, no `chat_update`. A test must still fail if the
behaviour is wrong. A test that only proves a function was called is not a test here.

**Two seams, agreed with Isaac on 2026-09-23:**

1. **The handler level.** The existing fake Slack client, plus a temporary copy of the
   workbook and a temporary `EPIFs/` directory, driven through the real handlers.
   Scenarios:
   - An interview on the EPIF path, approved with an assignee. The row is written, one
     EPIF is archived under the naming rule, the assignee's DM has the email draft
     **and** a file upload of that EPIF, and the thread says "to email to purchasing".
   - An interview on the Workday path, approved. The row is written, **no** EPIF is
     archived, **no** file is uploaded, the DM has no email draft, and the thread says
     "to place in Workday".
   - A bare thread approved. One thread reply names the thread starter, a
     `waiting_for_details` card is posted, and **no row** is written. Then Fill in
     details is submitted by the requester: the row is written with that requester and
     the card is `approved`. The same flow is repeated with the details submitted by a
     non-member: denial, no row.
   - A bare thread → This needs an EPIF. The row is written with `route = epif`, the
     EPIF is archived, and the card is approved with **no second approval step**.
   - Cancel on `waiting_for_details`: the workbook is unchanged, and the card is
     terminal.
   - Switch to EPIF before processed: the **same row number** is rewritten and the row
     count is unchanged. Switch after processed: refused, and the row is unchanged.
   - The template missing at approval: no row, and failure messages in the thread, DM
     and alert channel.
   - A second EPIF with an identical name is archived as `…_2.pdf`, and the first file
     is byte-identical afterwards.
   - `add-vendor` by an admin: the vendor is listed and routes to Workday. By a
     non-admin: denial, list unchanged. With a duplicate name: refused, list unchanged.
   - Screen 1 near-miss: the first submit returns the field error. A second submit with
     the same name proceeds on the EPIF path.
2. **The EPIF fill round trip.** A copy of the real blank `EPIF_TEMPLATE_HIRST.pdf` is
   committed as a test fixture. For a representative request in **each** category, and
   for both payment methods, `epif_parser.parse_epif(fill_epif(template, parsed))`
   returns the same item, purpose, amount, vendor, contact, date, room, project, fund,
   asset ID, name of system, category and payment method that went in, and
   *Charles Hirst* for PI of Funding and end user. The BOM case reads back
   `See attached BOM — N items` with the BOM total. This is the only test that proves
   the PDF is correct. A test that checks field names without reading the filled PDF
   back does not count.

Small pure helpers (`find_similar_listed_vendor`, `epif_archive_name`) are covered
through the handler scenarios above, not by separate unit tests.

**Prior art:** `test_26`–`test_33` (BOM set: temp workbook, temp directories,
synchronous queue fixture, fake client with DM capture and file-upload capture),
`test_05_decline_cancel.py` (cancel and terminal cards), `test_08_assignment.py`
(assignment rules), `test_12_denials.py` (ephemeral denials with absence
assertions), `test_24_startup_storage_check.py` (startup path entries),
`test_interview.py` (routing).

**Existing tests that assert the old wording** ("process in Workday / ShopUW", the
suggest option) must change. The ADR changed that behaviour on purpose. Each such edit
names ADR 0007 in the commit message. This is the only kind of test edit allowed here
(ADR 0001).

## Out of Scope

- The bot sending email. The buyer emails purchasing; the bot only drafts and attaches.
- Teaching the bot which vendors are on Workday beyond the admin-managed list. No
  lookups against Workday or ShopUW.
- Multi-EPIF threads (more than one vendor in one request). One EPIF per vendor per
  request is unchanged, and the existing multi-EPIF limitation stands (ADR 0006,
  Consequences).
- Switching an EPIF request to Workday. Only Workday→EPIF exists.
- Any switch after *Date Processed* is set.
- Renaming EPIFs already archived before this ships.
- Signatures on the EPIF. Slack approval is the approval.
- Changing the BOM file name, layout or Notes line.
- Deploying. Placing `EPIF_TEMPLATE_HIRST.pdf` in the server's `_TEMPLATE` folder, and
  setting any environment override, is a `human-task` ticket at the end of the set.

## Further Notes

- The parser reads 25 of the template's 28 fields. The implementer of block 2 lists all
  28 from the committed fixture and records the three unused names, and what they
  appear to be, in `epif_filler`'s module docstring. They are left blank. If one of
  them looks like a required approval or signature field, stop and escalate rather
  than guess (ADR 0001 escalation path).
- The fixture is a blank university form with no personal data. It is safe to commit.
- `@p-bot add-vendor` replaces the only route that ever added vendors (the suggest
  option → alert → Approve Vendor). Until it ships, the vendor list can't grow, so
  block 1 should land early.
- The Approve Vendor alert confirmation says a restart is needed to refresh
  dropdowns. The roster re-reads from disk on every call, so that line is probably
  stale. Correct it in block 1 if the code confirms it.
