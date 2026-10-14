# Spec — BOMs come in through the lab template, the EPIF date is the buyer's, categories have minimums

**Status:** ready-for-agent
**Binding:** ADR 0019 (BOMs come in through the lab template and are read — supersedes parts
of ADR 0006, 0008 and 0012), ADR 0007 (the bot fills the EPIF), ADR 0010 (linked cards),
ADR 0015 (thread files at approval), ADR 0018 (one builder for a request's lines),
ADR 0001 (tests first, no muted failures)
**Glossary:** `CONTEXT.md` — new: **EPIF date**, **Request date**, **Category minimum**,
**BOM template**, **BOM check**, **Off-template BOM**, **Replace BOM**. Rewritten:
**Line item**, **BOM**, **Filled EPIF**, **Thread files at approval**, **Edit**.
**Starts after:** the `purpose-and-link` set (120–122) has merged. Both touch interview
Screen 2.

Five parts. A, B, C and D are independent of each other. E is the largest. Its later
pieces build on its first, and it shares Screen 2 with A.

- **A** — Category minimum
- **B** — The EPIF date
- **C** — Files reach the buyer's DM, or someone can resend them
- **D** — A card edit is never lost silently
- **E** — The BOM template

## Problem Statement

**A.** A $109 adapter went to purchasing on an EPIF with *Component(s) for an approved
fabrication* ticked. The form itself says that category must be at least $200. A buyer
caught it after approval. Nothing in the bot compares the amount with the category. The
only "> $200" is in the category's label, and `interview.needs_asset_details` asks for an
Asset ID and nothing more. *Standalone Equipment (4602)* ("more than $5k") has the same gap.

**B.** The EPIF's *Date of Purchase* is a date picker on interview Screen 2, defaulting to
the day the requester fills in the form. The Filled EPIF is made at approval with that
date, and nothing afterwards can change it. Approval can come days after the form, and the
buyer can send the EPIF to purchasing days after that. Purchasing cares about the date on
the EPIF when the buyer sends it. The same field also feeds workbook column M, so the
lab's record of when it asked for something and purchasing's paperwork date are one value
when they should be two.

**C.** On 2026-10-13 the Filled EPIF for a Swagelok order timed out uploading to the
assigned buyer's DM ("The read operation timed out"). The bot alerted the admin, but the
buyer got the BOM and the card without the EPIF. Nobody can send it again from Slack.

**D.** On 2026-10-13 a requester's **Edit** of a posted McMaster card failed at
`chat_update` with `invalid_blocks: must be less than 2001 characters` on the card's
button values. Only the log recorded it: the requester was not told, and the card kept the
old request. The same overflow stopped a card being posted on 2026-09-29.

**E.** Real orders have many items, and lab members already build BOMs in Excel. Today
there are two ways in, and neither works.
- **The paste box:** retype every row as `qty | item | part | price | link | description`.
  Nobody does this for a real order.
- **Attaching a spreadsheet:** under ADR 0012 the bot never opens it. On the 2026-10-13
  valve-assembly order, the Filled EPIF did not say "See attached BOM", nobody checked
  the total against the EPIF amount, and the buyer got the file in whatever layout the
  requester happened to use.

## Solution

**A.** On every way a request comes in, an EPIF amount below its category's minimum is
refused with one actionable sentence. The bot never changes the category itself.
- Fabrication Component (4670) must be at least $200.00.
- Standalone Equipment (4602) must be more than $5,000.00.

**B.** The **EPIF date** and the **Request date** become separate values.
- The Filled EPIF is dated the approval day.
- The assigned buyer has a **Change date** button on their DM card until the request is
  processed. It re-dates the archived EPIF and sends the new copy to their DM.
- Column M records the Request date, and changing the EPIF date never changes it.
- The interview no longer asks for a date.

**C.** An upload to the assigned buyer's DM is retried before the admin is alerted. The
DM card gains a **Resend EPIF** button that sends the request's files again.

**D.** Every button `value` fits Slack's limit for the largest request the forms allow.
If a card update still fails, the person who made the edit is told it was not saved.

**E.** The lab's BOM template (`templates/HIRST_LAB_BOM_TEMPLATE.xlsx`) is the one way a
multi-item order comes in.
- Every form that takes items has a BOM upload field and a "Send me the BOM template"
  button.
- After upload, the form shows a **BOM check**: the rows as read, the total, and every
  problem by row. It won't go on until the rows are clean and the BOM total equals the
  typed Total Price to the cent.
- The bot rebuilds the BOM in the template layout and names it
  `HIRST_LAB_BOM_<Description>_<MM.DD.YYYY>.xlsx`. The Filled EPIF says "See attached
  BOM — N items".
- On the thread path, an `.xlsx` that isn't the template is approved anyway. The bot then
  asks the requester to **Replace BOM** before the request is processed, and the buyer's
  DM card shows the warning until they do.
- The paste box is removed.

## User Stories

### A — Category minimum

1. As a requester, when I pick Fabrication Component on a request under $200, I want the
   form to refuse with "Fabrication Component (4670) needs a total of at least $200 — this
   is $109.00. Pick another category (usually Research/Lab Supplies or Repair &
   Maintenance).", so that I fix it before anyone approves it.
2. As a requester, when I pick Standalone Equipment for $5,000.00 or less, I want the same
   kind of refusal naming the $5,000 minimum, so that capital-equipment coding is only used
   when it applies.
3. As a requester, I want a request of exactly $200.00 under Fabrication Component to go
   through, so that the boundary matches the form's "at least $200".
4. As a requester, I want **Edit** to refuse a change that drops a fabrication request
   below $200, so that an edit cannot sneak past the rule.
5. As a requester switching a Workday request to the EPIF path, I want the switch form to
   apply the same minimum, so that every route checks it.
6. As a requester who drops a hand-filled EPIF in a thread with the fabrication box ticked
   under $200, I want validation to refuse it with the same sentence, so that a
   hand-filled EPIF is held to the same rule.
7. As the approver, I want never to see a request whose amount breaks its category
   minimum, so that I don't have to catch coding errors myself.
8. As a buyer, I want every EPIF I receive to already satisfy its category minimum, so that
   purchasing does not bounce it back.

### B — The EPIF date

9. As a buyer, I want the Filled EPIF dated the day it was approved, not the day the form
   was filled in, so that most EPIFs are right without anyone touching them.
10. As the assigned buyer, I want a **Change date** button on my DM card, so that I can
    set the EPIF date to the day I actually send it in.
11. As the assigned buyer, I want Change date to open a date picker defaulting to today,
    so that the common case is one click.
12. As the assigned buyer, after I change the date I want the re-dated EPIF in my DM, so
    that I send the right file.
13. As the assigned buyer, I want the archived EPIF in the EPIFs folder replaced by the
    re-dated one under the same name, so that the archive matches what purchasing got.
14. As anyone reading the thread, I want a history line "EPIF date changed to MM/DD/YYYY
    by <buyer>", so that the change is visible.
15. As the lab, I want workbook column M to keep the **Request date** when the EPIF date
    changes, so that the log still records when we asked.
16. As the assigned buyer, I want Change date to disappear once I mark the request
    processed, so that the paperwork date cannot drift after it is sent.
17. As a buyer who is not assigned, or a requester, I want Change date refused, so that
    only the person sending the EPIF sets its date.
18. As a requester, I want the interview no longer to ask me for a date, so that I am not
    asked for something purchasing overwrites anyway.
19. As a buyer on a request with an uploaded (hand-filled) EPIF, I want Change date to
    rewrite only that EPIF's Date of Purchase field and leave everything else as the
    requester wrote it, so that the same button works on both kinds of EPIF.
20. As a buyer on a Workday-path request, I want no Change date button, because there is
    no EPIF.

### C — Files reach the buyer's DM

21. As the assigned buyer, I want a timed-out file upload to my DM retried automatically,
    so that a slow Slack moment does not leave me without the EPIF.
22. As the admin, I want an alert only after the retries have failed, naming the file and
    the buyer, so that alerts mean something.
23. As the assigned buyer, I want a **Resend EPIF** button on my DM card, so that I can
    get the request's files again without asking the admin.
24. As the assigned buyer, I want Resend EPIF to send every file my DM is meant to carry
    for that request (EPIF, BOM, quotes) from the archive, so that one click restores the
    whole set.
25. As a buyer, I want Resend EPIF refused for anyone other than the assigned buyer or an
    admin, so that files go only where they belong.

### D — A card edit is never lost silently

26. As a requester, I want an edit of any request the forms allow — longest Purpose and
    description, ten quotes, a full BOM — to update the card, so that size never decides
    whether my edit lands.
27. As a requester, if the card update still fails, I want a message telling me my edit
    was not saved and why, so that I don't assume it went through.
28. As a requester, I want a new request card to post for the largest request the forms
    allow, so that the 2026-09-29 failure cannot recur.

### E — The BOM template

29. As a requester with two or more items, I want to upload the lab BOM template instead
    of typing rows, so that I can work in Excel.
30. As a requester, I want a "Send me the BOM template" button beside the BOM field that
    DMs me the template while my form stays open, so that I know the template exists and
    can get it at the moment I need it.
31. As a requester, I want the BOM field's hint to say "Two or more items? Fill in the lab
    BOM template.", so that the expectation is clear.
32. As a requester, after uploading I want a **BOM check** screen showing the rows the bot
    read and the BOM total, so that I can see it understood my spreadsheet before anything
    is posted.
33. As a requester, I want every problem listed by spreadsheet row, for example "Row 7:
    Unit Cost 'TBD' isn't a number.", so that I know exactly what to fix.
34. As a requester, I want the check screen to refuse while the BOM total differs from my
    typed Total Price by even a cent, with "The BOM totals $X but you typed $Y — they must
    match.", so that the EPIF and the BOM never disagree.
35. As a requester, I want to fix my spreadsheet and upload it again on the check screen
    without starting over, so that a typo costs one re-upload.
36. As a requester, I want the check screen shown even when nothing is wrong, so that I
    always confirm what the bot read.
37. As a requester, I want a file that isn't the template refused with "This isn't the lab
    BOM template — get it with the button above. Vendor carts and quotes go in the Quotes
    field.", so that I know what to do.
38. As a requester, I want a `.csv` refused the same way, so that there is one format.
39. As a requester, I want the template's header block (Order Description, BOM Creator,
    Total Cost) ignored when the bot reads it, so that filling it in or not makes no
    difference.
40. As a requester, I want rows with both Unit Cost and Quantity blank skipped, so that
    stray marks and spare template rows are not reported as broken items.
41. As a requester, I want reading to stop at the row with "Total" in the Quantity column,
    so that the Total row is never read as an item.
42. As a requester, I want the bot to compute each line as quantity × unit cost itself, so
    that a file saved by something other than Excel (no stored formula results) still
    totals correctly.
43. As a requester, I want Item, a whole-number Quantity of 1 or more, and a numeric Unit
    Cost required on every read row, and Description, Product #, Vendor and Notes
    optional, so that only what purchasing needs is enforced.
44. As a requester, I want a hyperlink on an Item cell kept in the rebuilt BOM, and no
    link ever required, so that links I added are not lost and a big BOM does not need
    one per row.
45. As a requester, I want the one-vendor checkbox required whenever a BOM is attached, so
    that one EPIF stays one vendor.
46. As a requester, I want a one-item order to use the ordinary Screen 2 fields with no
    BOM, so that small orders stay simple.
47. As a requester, I want the paste box gone from Screen 2, Add items and Edit, so that
    there is one way to enter items.
48. As a requester editing a posted card, I want Edit to take a new BOM through the same
    check screen, and an empty BOM field to keep the current rows, so that editing a BOM
    works like creating one.
49. As a requester adding items to a posted card, I want Add items to use the same upload
    and check screen, so that every items form behaves the same.
50. As the approver, I want the draft BOM in the thread named
    `DRAFT_HIRST_LAB_BOM_<Description>_<MM.DD.YYYY>.xlsx`, so that I can open what I am
    approving.
51. As a buyer, I want the archived BOM named `HIRST_LAB_BOM_<Description>_<MM.DD.YYYY>.xlsx`
    (approval date), matching the lab's existing naming, so that files are recognisable
    outside Slack.
52. As a buyer, I want two BOMs that would get the same name to get `_2`, `_3`, so that
    nothing is overwritten.
53. As a buyer, I want the rebuilt BOM in exactly the template layout, with Order
    Description = the request's "What is being purchased", BOM Creator = the requester's
    roster name, live formulas, and each row's Notes kept, so that every BOM I send looks
    the same.
54. As the lab, I want the workbook row's Notes column to name the BOM file, so that a
    row and its BOM stay linked now that the row number is not in the file name.
55. As a buyer, I want the Filled EPIF's "What is being purchased" to say "See attached
    BOM — N items" whenever the request has a BOM, so that purchasing knows to open it.
56. As the approver approving a thread with an EPIF and an `.xlsx` that is a clean
    template adding up to the EPIF amount, I want it read like a form BOM, so that the
    thread path gets the same result.
57. As the approver approving a thread whose `.xlsx` isn't the template, has row
    problems, or doesn't add up to the EPIF amount, I want approval to go through anyway,
    so that a spreadsheet layout never blocks a purchase.
58. As a requester in that case, I want a thread message naming the problem and asking me
    to use **Replace BOM** before the request is processed, so that I know what to fix.
59. As the assigned buyer in that case, I want my DM card to say "⚠️ BOM not in the lab
    template — requester asked to update" until it is replaced, so that I can decide
    whether to wait.
60. As a requester or buyer, I want a **Replace BOM** button from approval until the
    request is processed, opening the same upload and check screen, so that the BOM can
    be fixed without cancelling.
61. As the assigned buyer, I want a replaced BOM re-archived and sent to my DM, and the
    warning removed from my DM card, so that I have the right file.
62. As a buyer, I want Replace BOM never to block Mark Processed, so that formatting never
    stops a purchase.
63. As a requester, I want Replace BOM gone once the request is processed, so that the BOM
    is frozen once it has been sent.
64. As the developer, I want `/blank-template` to hand out the BOM template alongside the
    EPIF, so that there is one way to get both.

## Implementation Decisions

### A — Category minimum

- One pure rule in `validators`, next to `pcard_problem`. It is
  `category_minimum_problem(category, total_price) -> str | None`, returning the sentence
  or `None`. The minimums live in `config` as a mapping from category value to
  `(amount, inclusive)`: Fabrication Component (4670) = `(200.00, True)` and Standalone
  Equipment (4602) = `(5000.00, False)`.
- Called from:
  - the Screen 2 submit (category and Total Price are both on Screen 2), as an error on
    `block_total_price`;
  - the Edit submit;
  - the switch-to-EPIF submit;
  - `validators.validate` for dropped and thread EPIFs.
- These are the same call sites as the P-card rule; copy how `pcard_problem` is wired.
- The bot never changes a category.

### B — The EPIF date

- The request carries two values: `request_date` (column M) and `epif_date` (the EPIF's
  Date of Purchase field).
- Interview and Edit no longer render `block_date_of_purchase`. `request_date` is the day
  the request is posted.
- For an uploaded EPIF, both values come from the PDF's Date of Purchase, which is
  today's behaviour.
- `epif_filler.fill_epif` writes `epif_date`. When the Filled EPIF is made (at approval or
  at a switch to the EPIF path), `epif_date` is that day.
- **Change date** is a handler in the handlers layer. It is called by the DM-card button's
  view submission and is the only implementation.
  - It rewrites the Date of Purchase field of each archived EPIF of the request: a Filled
    EPIF is re-filled, an uploaded EPIF has only that field rewritten.
  - It overwrites the archive under the same name, uploads the new copy to the assigned
    buyer's DM, and appends the history line.
  - It does not write to the workbook.
  - It is allowed only for the assigned buyer, on the EPIF path, and only before
    **processed**.
- Re-dating an uploaded EPIF is a pure function in `epif_filler` (bytes in, bytes out) so
  that it is testable without Slack. It must round-trip through `epif_parser.parse_epif`.

### C — Files reach the buyer's DM

- Each DM upload in `lifecycle._send_assignee_dm` is attempted up to 3 times, with short
  waits between attempts, before the existing admin alert. The retry count and waits are
  constants in `config`.
- A timed-out upload may already have landed, so a duplicate file in the DM is accepted.
- **Resend EPIF** is a handler that re-uploads, from the archive, the files
  `_send_assignee_dm` would attach for that request. It shares the upload-with-retry code
  with `_send_assignee_dm`; there is no second implementation. It is allowed for the
  assigned buyer or an admin, on the EPIF path, in any state.

### D — Card edits

- The button-`value` overflow is diagnosed and fixed at the builder in `blocks`:
  `build_request_blocks` and the DM card builder.
- The requirement: for the largest request the forms allow (every text field at its
  maximum length, 10 quotes, a BOM at the row cap, a long history), every button `value`
  is at most 2,000 characters.
- Anything that can grow without bound (quotes, line items, history beyond what the next
  click needs) is kept out of the value, as items already are (AGENTS.md trap 9).
- When `chat_update` for an edit or a stage change fails, the person who acted is told
  through the existing reply path (`respond`, or the one permitted ephemeral path) that
  the change was not saved, quoting Slack's error.

### E — The BOM template

- **Template:** `templates/HIRST_LAB_BOM_TEMPLATE.xlsx` is committed: the lab's file with
  its example rows cleared. A filled real example is committed as a test fixture,
  `BOM_TEMPLATE_FILLED_EXAMPLE.xlsx` (4 rows, total $858.50, Item hyperlinks on every
  row, a stray mark in A10).
- **Reading — a pure function in `bom`:**
  `read_bom_template(xlsx_bytes) -> (line_items, problems)`, with no Slack and no I/O
  beyond the bytes.
  - It finds the header row `Item | Description | Product # | Vendor | Unit Cost |
    Quantity | Total Cost | Notes` (case and surrounding spaces ignored) in the first 10
    rows of the first sheet.
  - Not finding it returns the single "isn't the lab BOM template" problem.
  - It reads to the row with "Total" in the Quantity column and skips rows with both Unit
    Cost and Quantity blank.
  - It never reads formula cells. Problems carry spreadsheet row numbers.
  - A line item's link is the Item cell's hyperlink target, if any.
  - There is a row cap, stored in `config`, sized so the line items fit the card
    message's Slack metadata. Over the cap is a problem naming the cap.
- **Total check:** a pure function in `bom`. The BOM total (sum of quantity × unit cost,
  rounded to the cent) must equal the typed Total Price exactly. It replaces the old
  items-plus-shipping check. Shipping is gone.
- **Writing:** `bom.build_bom_workbook` is rewritten to produce the template layout.
  - Header block: title, Order Description, BOM Creator, Total Cost.
  - Columns: Item, Description, Product #, Vendor, Unit Cost, Quantity, Total Cost, Notes.
  - Live formulas: `=F*E` per line and `=SUM` on the Total row, with the header's Total
    Cost pointing at it.
  - The Item hyperlink is kept where present.
  - The fastest way to match the layout exactly is to load the committed template and
    fill it.
- **Naming:** `bom.bom_filename` becomes `(description, approval_date, draft) ->
  HIRST_LAB_BOM_<Description>_<MM.DD.YYYY>.xlsx`, with `DRAFT_` in front for the draft.
  - Description: words with internal spaces removed, joined by `-`, characters invalid in
    a Windows file name dropped, at most 60 characters.
  - Clash suffixes `_2`, `_3` are resolved in `log_writer.save_bom` against the folder.
  - The Notes-column reference uses the final name.
  - Quote names are unchanged.
- **Forms:**
  - Screen 2, Add items and Edit lose the paste box: `blocks.line_items_input` is deleted
    and its tests are rewritten per ADR 0019.
  - These forms keep the BOM file field (`.xlsx` only) and the one-vendor checkbox
    (required when a BOM is attached).
  - A "Send me the BOM template" button sits beside the BOM field. Its action handler
    DMs the template using the same code as `/blank-template` and does not close the form.
- **BOM check flow:**
  - A form submitted with a BOM answers Slack at once with `response_action: update` to a
    "Reading your BOM…" view. Downloading and reading happen off the listener, then
    `views.update` (by the view's id) shows the check view. This keeps inside Slack's
    3-second limit.
  - The check view lists the rows, the BOM total and the typed Total Price, every problem,
    a file field to upload a corrected BOM, and a submit button.
  - Submitting with a new file re-reads it. Submitting with no problems continues where
    the original form would have gone next: Screen 3 for asset categories, otherwise
    posting, or applying the edit.
  - Submitting while problems remain returns the problems as field errors.
  - The flow's state rides in the view's `private_metadata`. Line items never go in a
    button value.
- **EPIF filler:** "See attached BOM — N items" whenever the request has two or more line
  items. The logic is unchanged; there are now simply always line items when there is a BOM.
- **Thread path (amends ADR 0015):**
  - At approval an `.xlsx` in the thread is read with `read_bom_template` and
    total-checked against the EPIF amount.
  - Clean: it becomes line items and the bot rebuilds the BOM.
  - Otherwise, an **Off-template BOM**: approval proceeds, the file is archived as given
    under the new name, a flag is stored in the card's metadata, the thread gets the
    problem message mentioning the requester, and the DM card shows the warning line
    while the flag is set.
  - A `.csv` in a thread is treated as an Off-template BOM.
- **Replace BOM** is a handler. It is shown on the thread card and the DM card from
  approval until processed, for the requester, a buyer or an admin. It opens the upload
  and check flow. Success re-archives the BOM under the request's existing BOM name
  (overwrite), clears the off-template flag, re-renders both linked cards, uploads the
  BOM to the assigned buyer's DM, and posts a thread history line. It does not touch the
  workbook row except the Notes BOM name if the name changed. It never gates Mark
  Processed.
- **`/blank-template`** also posts the BOM template.

## Testing Decisions

- **Good tests here** assert what a person would see or what lands on disk:
  - the field error text on a view submission;
  - the view a `views.update` was called with;
  - the files uploaded to a DM;
  - the bytes of an archived file read back with the real reader;
  - the absence of an upload or a workbook write where that is the point.

  They never assert on private helpers or call order.
- **Seams, highest first:**
  1. Listener/handler entry points driven with a fake Slack client, as in
     `tests/test_32_edit_a_posted_card.py`, `tests/test_116_switch_to_epif_button.py`,
     `tests/test_117_switch_to_epif_submit.py` and `tests/test_46_epif_path_dm_attaches_epif.py`:
     view submissions, block actions and approval.
  2. Pure domain functions on real files:
     - `read_bom_template` on the committed filled fixture and on files built in the test
       (wrong headers, a CSV, a 'TBD' unit cost, a stray mark, blank rows);
     - `build_bom_workbook` read back with `read_bom_template`, a round trip;
     - `fill_epif` and the re-date function read back with the real `epif_parser.parse_epif`
       on `tests/fixtures/EPIF_TEMPLATE_HIRST.pdf`, as `tests/test_37_fill_epif.py` does;
     - `category_minimum_problem` and `bom_filename`, table-driven.
- **What tests may fake:** the Slack client and the network. **What must be real:**
  openpyxl reading and writing, pypdf filling and parsing, and `log_writer`'s file saves
  against a temporary directory. Nothing touches the real workbook or OneDrive.
- The 2,000-character requirement (D) is proved by building the largest allowed request
  through the real `blocks` builders and measuring every button value. It must fail on
  today's code.
- The retry (C) is proved with a fake client whose `files_upload_v2` raises twice and then
  succeeds: one upload lands and no admin alert is posted. A second fake raises three
  times: the alert is posted.
- **Tests replaced, not muted, as ADR 0019 authorises:** `tests/test_26_line_items_and_bom.py`,
  `tests/test_49_bom_lab_layout.py`, `tests/test_50_one_items_box.py`,
  `tests/test_28_line_items_modal_path.py` and the attached-BOM tests. Each removed test
  function is named in its ticket's `Deletes tests:` line.

## Out of Scope

- Reading any spreadsheet layout other than the template. Header guessing is never done.
- Reading quotes. They stay carried, never read.
- Shipping or tax tracking anywhere.
- Changing the EPIF date on the Workday path (there is no EPIF) or after processed.
- Changing column M from Slack.
- Retroactively re-dating, renaming or rebuilding EPIFs and BOMs approved before this
  ships.
- Enforcing category minimums on requests already approved.
- A per-row Slack table editor. Excel is the editor.
- Batch requests (multiple EPIFs in one thread) carrying a BOM; ADR 0015 already forbids
  it.

## Further Notes

- `AGENTS.md` trap 11 ("One items box", `blocks.line_items_input`) and trap 10 ("no
  shipping row") go stale when E lands. `AGENTS.md` is the developer's. Tickets must not
  edit it; the developer updates it.
- The row cap in E depends on Slack's message-metadata size limit. The reading ticket
  must measure the metadata a capped BOM produces and set the cap below the documented
  limit, with a test that builds a capped BOM's metadata and checks its size.
- `templates/` is new. Confirm `p_bot.spec` (the PyInstaller build) bundles it, or the
  executable build loses `/blank-template`'s BOM.
