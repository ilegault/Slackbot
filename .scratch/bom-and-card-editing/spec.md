# Spec — the BOM spreadsheet, line items, and editable posted cards

**Status:** `ready-for-agent`

Written 2026-09-21. Covers ticket set **26 onward**. Convert to tickets in the
order the Implementation Decisions section is written. Each numbered decision
block is one seam, and that order is the dependency order.

Read before implementing anything here:

- `CONTEXT.md`: the glossary. **Line item**, **BOM**, **Edit** and
  **Superseded** are new, and every word below is used as it defines them.
- `docs/adr/0006-bom-line-items-and-editable-posted-cards.md`: **the decision
  record for this whole set. Binding.**
- `docs/adr/0001-tests-first-and-no-muted-failures.md`: binding on all test work.
- `docs/adr/0003-decline-and-cancel.md`: cancel semantics, extended here by
  decision 5.
- `docs/adr/0004-assignment-replaces-claim.md` and `0005`: the assignee
  email-draft DM, which gains an attachment here.

---

## Problem Statement

A lab member orders five different couplings from Ruland. It is still one vendor,
so it is still **one EPIF**. But the EPIF has one "What is being purchased" line
and one amount, so the five parts end up as five bare links pasted into an email
to Tina. The buyer has to assemble that email by hand. Tina gets a pile of links
with no quantities or unit prices beside them. Charlie approves a total without
ever seeing what it is made of. Smeet has been making a spreadsheet by hand to fix
this, and Dylan asked for the bot to make it instead.

Separately, once a request card is posted, the requester cannot fix a typo on it.
The only moves are Decline-and-restart, or dropping a corrected EPIF. The second
one leaves the old card live with its own Approve button, so there are two
approvable cards for one purchase.

## Solution

A requester can attach **line items** to a request, on both paths:

- **`/new-purchase`**: an optional **Line items** box on interview Screen 2.
- **EPIF dropped in a thread**: an **Add items** button on the posted card.

Both use the same paste box: one line per item. Rows copied straight out of Excel
or Google Sheets work.

When a request has **two or more line items**, the bot makes a **BOM**, an `.xlsx`
listing every item with its quantity, unit cost and line total. The line totals
plus an optional shipping line must add up to the EPIF amount, or the items are
refused.

- **Before approval**, a draft BOM is posted in the thread so Charlie sees the
  itemised list.
- **At approval**, the BOM is regenerated with the Purchasing Log row number in it
  and archived to a new **BOMs** folder as `NNNN_<Vendor>_BOM.xlsx`. The row's
  Notes column names it. It is uploaded to the thread and attached to the
  assignee's email-draft DM, so the buyer forwards one EPIF and one spreadsheet
  instead of a pile of links.

A posted card gets an **Edit** button for the requester, any buyer, or an admin:

- **Modal-born card**: Edit reopens the Screen 2 details, pre-filled, including
  the items box.
- **PDF-born card**: Edit changes line items only, because the PDF is the source
  for everything else.

Every edit posts one thread line saying what changed. Dropping a corrected EPIF
**supersedes** the older posted card, which loses its buttons.

## User Stories

1. As a lab member ordering several parts from one vendor, I want to list every
   part on one request, so that I don't have to paste a pile of links into an
   email.
2. As a lab member, I want to paste rows straight from Excel or Google Sheets
   into the items box, so that I don't have to retype an order I already put
   together.
3. As a lab member, I want to write items as `qty | name | part # | unit price | link | description`,
   so that I can type a short list by hand without a spreadsheet.
4. As a lab member, I want part number, link and description to be optional, so
   that a quick order doesn't need every column filled.
5. As a lab member, I want to add a `shipping | 24.50` line, so that shipping
   and tax don't make my items disagree with my EPIF total.
6. As a lab member, I want each bad line reported by its line number with the
   reason, so that I can fix line 3 without guessing which line is wrong.
7. As a lab member, I want blank lines in my paste ignored, so that a stray empty
   row from a spreadsheet doesn't cause an error.
8. As a lab member, I want to be told clearly when my items don't add up to my
   EPIF amount, with both numbers shown, so that I can see whether I mistyped a
   price or forgot shipping.
9. As a lab member ordering ten of one part, I want a single line with quantity
   10 to be enough, so that I'm not made to produce a spreadsheet for one thing.
10. As a lab member using `/new-purchase`, I want the Line items box on the same
    screen as the rest of the details, so that it's part of the request and not a
    separate step.
11. As a lab member using `/new-purchase`, I want the Line items box to be
    optional, so that single-item requests work exactly as they do today.
12. As a lab member who dropped an EPIF PDF in a thread, I want an **Add items**
    button on the posted card, so that I can itemise an EPIF that only carries
    one description.
13. As Charlie, I want a draft BOM posted in the thread before I approve, so that
    I can see what the total is made of before I say yes.
14. As Charlie, I want a request whose items don't add up to be impossible to
    approve until they do, so that the log never disagrees with the EPIF Tina
    receives.
15. As a buyer, I want the BOM attached to my email-draft DM when I'm assigned,
    so that I can forward the EPIF and the spreadsheet to Tina in one go.
16. As a buyer assigned after approval with `@Purchasing assign`, I want the BOM
    attached to that DM too, so that late assignment isn't a worse experience.
17. As a buyer, I want the email draft to mention the attached BOM by file name,
    so that Tina knows to open it.
18. As anyone in the purchasing channel, I want the approved BOM uploaded to the
    thread, so that the itemised order sits beside the conversation that approved
    it.
19. As a lab member reading the Purchasing Log, I want the row's Notes column to
    say `BOM: 0018_Ruland_BOM.xlsx (5 items)`, so that I know an itemised sheet
    exists and which one it is.
20. As a lab member browsing the BOMs folder, I want each file to start with its
    log row number, so that I can go from a file straight to its row.
21. As a lab member opening a BOM, I want its header to show the vendor,
    requester, project ID / fund, log row and date, so that the sheet makes sense
    on its own when forwarded.
22. As Tina, I want every line to show item, part #, description, link, qty, unit
    cost and line total, with shipping and a grand total at the bottom, so that I
    can place the order from the sheet alone.
23. As an admin, I want the BOMs folder configured and startup-checked like
    EPIFs and Quotes, so that a missing folder is named in the startup alert
    rather than failing silently at the first approval.
24. As an approver or admin cancelling an approved request, I want its archived
    BOM moved to `Cancelled/`, so that the BOMs folder only holds live purchases,
    matching the log.
25. As an approver, I want the BOM frozen once I approve, so that what I approved
    is what gets ordered.
26. As a requester whose approved request needs different items, I want to be
    told that the path is cancel-and-resubmit, so that I'm not hunting for an
    edit button that doesn't exist.
27. As a requester, I want an **Edit** button on my posted card, so that I can fix
    a typo without declining and starting over.
28. As a requester whose card came from `/new-purchase`, I want Edit to reopen the
    Screen 2 details pre-filled, so that I only change the one field that's wrong.
29. As a requester whose card came from an EPIF PDF, I want Edit to change line
    items only, so that the card never disagrees with the PDF on file.
30. As a requester who needs to change an EPIF field, I want to upload a corrected
    EPIF and have it replace my old card, so that there's only ever one card to
    approve.
31. As a buyer tidying up a request before approval, I want to be able to edit it
    too, so that I can fix obvious item mistakes without chasing the requester.
32. As an admin, I want to be able to edit any posted card, so that I can repair a
    request on someone's behalf.
33. As a lab member who is none of the above, I want a clear ephemeral denial when
    I click Edit, so that I know why nothing opened and the card is untouched.
34. As Charlie, I want every edit to post one thread line like
    `✏️ Edited by Dylan: Total $412.00 → $455.50; items 4 → 5`, so that a card I
    already read can't change silently under me.
35. As Charlie, I want the draft BOM re-posted when items change, so that the
    newest sheet in the thread is the current one.
36. As a requester who opens Edit and changes nothing, I want nothing posted, so
    that the thread doesn't fill with empty edit notices.
37. As a requester whose card gets approved while my Edit modal is open, I want my
    submit refused with a message saying it was approved meanwhile, so that an
    approved request is never altered.
38. As a requester, I want edits validated exactly like the original submission
    (including the asset fields when the category needs them), so that editing is
    not a way around validation.
39. As Charlie, I want a superseded card to keep its summary but lose every button
    and read "Superseded by a newer EPIF below", so that I can see the history and
    can't approve the stale version.
40. As a lab member posting EPIFs for two different vendors in one thread, I want
    neither card to supersede the other, so that one EPIF per vendor keeps working.
41. As Charlie, I want an approved card never to be superseded by a later upload,
    so that a real purchase can't be hidden by a stray PDF.
42. As the bot's maintainer, I want line items stored in the card message's
    metadata and not the button value, so that a long item list can't overflow
    Slack's ~2 000-character button limit and break the card.
43. As the bot's maintainer, I want one parser and one items modal serving both
    paths, so that the two paths can't drift apart.

## Implementation Decisions

Numbered in dependency order. Each block is one ticket.

### 1. Line items: parse, format, and total-check (domain, pure)

A new domain module, **`bom`**, Slack-free and I/O-free, beside `epif_parser` and
`interview`. Add it to the domain list in the layering test.

- `parse_line_items(text) -> (items, shipping, errors)`.
  - One line per item. Fields are split on `|` if the line contains one,
    otherwise on tab. Each field is whitespace-trimmed.
  - Field order: `qty | name | part_number | unit_price | link | description`.
    Minimum 4 fields. A 5th and 6th are optional. Extra fields beyond 6 are an
    error.
  - `qty` must be a positive whole number. `unit_price` uses the same money
    parser as the EPIF (`$` and commas allowed) and must be ≥ 0. `name` must be
    non-empty.
  - A line whose first field is `shipping` (case-insensitive) is the shipping
    line: `shipping | <amount>`. At most one. Amount ≥ 0.
  - Blank lines are skipped. **Line numbers in errors count every line of the
    original text, blank lines included**, so they match what the user sees.
  - Error strings read like `line 3: unit price "abc" is not a number`.
  - More than 25 item lines is an error.
  - An item is the dict
    `{"qty": int, "name": str, "part_number": str, "unit_price": float, "link": str, "description": str}`.
- `format_line_items(items, shipping) -> str`: the inverse, `|`-separated, used to
  pre-fill an edit. `parse_line_items(format_line_items(x)) == x` for any valid x.
- `check_total(items, shipping, total_price) -> str | None`:
  `sum(qty × unit_price) + shipping` against `total_price` with $0.01 tolerance.
  Returns `None`, or a sentence showing both numbers.
- `needs_bom(items) -> bool`: `len(items) >= 2`.
- `describe_changes(old_request, new_request) -> list[str]`: the fragments of the
  edit line (decision 6), e.g. `"Total $412.00 → $455.50"`, `"items 4 → 5"`, or
  `"items changed"` when the count is equal but the content differs. It compares
  exactly these fields: item description, total price, purpose, link, project ID,
  fund, category, delivery room, vendor contact name, vendor contact email,
  payment method, asset ID, name of system, and the items plus shipping.

### 2. The BOM workbook and its folder (domain builder + storage)

- `bom.build_bom_workbook(request, items, shipping, row) -> bytes`. Pure: builds a
  **new** workbook with openpyxl in memory and returns its bytes. `row=None` means
  a draft.
  - The header block holds the vendor, requester, project ID / fund,
    `Purchasing Log row NNNN` or `DRAFT — not yet approved`, and the date.
  - Columns: `#`, `Item`, `Part #`, `Description`, `Link`, `Qty`, `Unit cost`,
    `Line total`. `Link` is a clickable hyperlink when it is a URL.
  - Then a `Shipping / tax` row and a `Total` row. Totals are **written as numbers,
    not formulas**, so the file reads correctly in every viewer and in tests.
  - Currency formatting on the cost columns.
  - The x14 hazard from `log_writer`'s docstring applies only to
    `Purchasing-Log.xlsx`. It does not apply to this new file.
- `bom.bom_filename(row, vendor) -> str`. Returns `f"{row:04d}_{slug}_BOM.xlsx"`, where
  `slug` is the vendor with spaces replaced by `-`, everything except letters,
  digits and `-` removed, capped at 40 characters, falling back to `Vendor`. The
  draft name is `DRAFT_{slug}_BOM.xlsx`.
- `log_writer.save_bom(xlsx_bytes, filename, target_dir=None) -> str`. Atomic,
  mirroring `save_epif` exactly: `tempfile` in the target dir, then `os.replace`.
- `config.BOMS_DIR`: env `BOMS_DIR`, defaulting beside `QUOTES_DIR` in the same
  OneDrive `Purchasing` folder, as `...\Purchasing\BOMs`. Added to
  `path_validator`'s startup check alongside the other storage paths, and to the
  `docs/SETUP.md` / `.env` example. Invariant 4: the constant lives in `config`
  only.

### 3. Line items on the card: storage, the items modal, and both entry paths

**Where items live (ADR 0006 decision 5, binding):** in the posted card message's
Slack `metadata.event_payload` as `"items"` (list) and `"shipping"` (float). **Never
in a button `value`.** The payload also gains `"source": "epif" | "modal"`, set at
creation, which decides what Edit offers.

- A new `slack_io` read, `get_card_payload(client, channel, thread_ts, card_ts)`.
  It returns the metadata payload of **that exact message**, fetched with
  `include_all_metadata=True`, not the newest card in the thread.
- **Modal path.** `build_stage2_view` gains an optional multiline `block_line_items`
  input:
  - label `Line items (optional)`, `max_length` 1500, and a hint showing the
    format and the `shipping |` line.
  - The 1500 cap exists because the raw text rides in `private_metadata` to
    Screen 3, which Slack caps at 3 000 characters. **The cap is a requirement,
    not a preference.**
  - On submit, parse and total-check against the Total Price field. Errors go on
    `block_line_items` through `response_action: errors`.
  - `_process_interview_completion` stores the items and shipping in the card
    metadata. If `needs_bom`, it uploads the draft BOM to the thread right after
    the card.
- **PDF path.** `build_request_blocks("posted", …)` renders an **Add items**
  button (**Edit items** once items exist) on `source == "epif"` cards. The button
  opens a new `build_items_view(...)`: one items box, pre-filled with
  `format_line_items`. Its `private_metadata` holds only `channel`, `thread_ts` and
  `card_ts`. On submit, it is parsed and checked against the EPIF's
  `total_price`.
- Saving items is **one handler** in `lifecycle`, `handle_items_update`. It
  re-reads the card, checks the card is still `posted`, and writes the new
  metadata and blocks with `chat_update`. It then posts the edit line (decision 6),
  appends history, and re-posts the draft BOM when `needs_bom`. Both the PDF path's
  items modal and the Edit modal's items box call it (invariant 1).
- The card summary shows `📋 N line items (BOM attached in thread)` when
  `needs_bom`, and nothing extra otherwise.
- Draft BOMs are uploaded with `files_upload_v2` into the thread, the way `ops`
  already uploads log files. They are **not** saved to `BOMS_DIR`.

### 4. Approval archives the BOM, points the log at it, and sends it

- Both approval paths already converge on `finalize_purchase_request`. It gains
  `items` and `shipping` arguments.
  - The **Approve button** path gets them via `get_card_payload(…, card_ts)`.
  - The **keyword** path gets them from the metadata lookup it already does.
    Known limitation: that lookup finds the newest card.
- **Guard:** if items are present and `check_total` fails, approval is refused like
  a validation problem: nothing is written, the requester is DM'd, and the thread
  is told.
- Inside the **same queued write task**, when `needs_bom`:
  1. `append_row`
  2. `build_bom_workbook(…, row)`
  3. `save_bom(…, bom_filename(row, vendor))`
  4. `update_row(row, {"Y": f"BOM: {filename} ({n} items)"})`

  **All-or-nothing, as a requirement:** if step 2, 3 or 4 raises, the task calls
  `blank_row(row)` before re-raising, so a failed BOM never leaves an orphan row.
  The Notes column constant is `config.COLUMN_NOTES`, never a literal `"Y"`.
- `on_success`: upload the archived BOM into the thread. Add `"bom_file": filename`
  to the approved card's request payload. It is short, so it may ride in the
  button value. Pass the BOM path to the assignee DM.
- **Assignee DM, in both places it is sent** (`finalize_purchase_request` on
  approval and `handle_assign` afterwards):
  - Upload the BOM into the DM with `files_upload_v2`, opening the DM with
    `conversations_open`.
  - `text_rules.generate_email_draft` gains an optional `bom_filename` and adds
    the line `Itemised BOM attached: <filename>`.
  - A failed upload is logged and alerted to admin. It never fails the approval.

### 5. Cancel moves the BOM out of the live folder

`handle_cancel`: when the request payload carries `bom_file`, the queued cancel
task moves `BOMS_DIR/<bom_file>` to `BOMS_DIR/Cancelled/<bom_file>` (creating the
folder) after blanking the rows. A missing file is logged, not raised. The
cancellation still completes. Nothing else about cancel changes. ADR 0003 stands.

### 6. Edit on a posted card

- `build_request_blocks("posted", …)` renders **Edit** (`config.ACTION_REQ_EDIT`)
  on `source == "modal"` cards, beside Approve and Decline. PDF-born cards use the
  Add/Edit items button from decision 3 as their Edit.
- **Permission** (listener, before opening any modal): the requester (payload
  `user_id`), `roster.is_buyer`, or `roster.is_admin`. A denial goes through
  `slack_io.deny`, ephemeral, and the card is untouched (invariant 5, ticket 12's
  rule).
- **Modal-born edit view**: `build_stage2_view` extended to accept a pre-fill
  dict.
  - Every Screen 2 field comes pre-filled, plus the items box, plus Asset ID and
    Name of System. Those two are required on submit when
    `interview.needs_asset_details(category)`.
  - **Vendor and route (Screen 1) are not editable.** To change vendor, Decline
    and resubmit.
  - Submit validates with the same rules as the interview, then calls a
    `lifecycle.handle_request_edit`. That rebuilds the parsed request, writes the
    card (blocks and metadata), and posts the edit line.
- **The edit line**, from `describe_changes`, is one thread message:
  `✏️ Edited by <name>: <fragment>; <fragment>`. The same text is appended to
  history. **No changes → no thread line, no history line.**
- **Approved meanwhile:** on submit the handler re-reads the card with
  `get_card_payload`. If its state is no longer `posted`, the submit is refused
  with a `response_action: errors` message on the first block:
  `This request was approved while you were editing — nothing was changed.`

### 7. A corrected EPIF supersedes the older posted card

In `handle_epif_drop`, before posting the new card, scan the thread's cards for any
that are:

- in state `posted`,
- with the same requester `user_id`,
- with the same vendor (case-insensitive, trimmed).

Each match is rewritten with `build_request_blocks("superseded", …)`: the summary
kept, **no buttons**, a history line, and a context line
`Superseded by a newer EPIF below`. Its metadata is kept. Approved or later cards
are never touched. A different vendor is never a match. Items do not carry over.

## Testing Decisions

A good test here drives behaviour from the outside and asserts on what the bot
would have **sent or written**: the blocks, the thread text, the uploaded file,
the workbook cell, the file on disk. It never asserts on which internal helper was
called. Where the point is that something must *not* happen (no row, no upload, no
`chat_update`, no DM), assert on the absence.

Three places to test, agreed with Isaac on 2026-09-21:

1. **`bom` parser and checks.** Plain strings in, and the tests assert on what
   comes out.
   - A tab-separated paste copied from Excel parses the same as its `|` form.
   - Blank lines are skipped, and a later bad line reports its true line number.
   - A bad qty, price or missing name each produce the right line-numbered error.
   - A second shipping line is an error. 26 items is an error.
   - `format_line_items` round-trips.
   - `check_total` passes within one cent and fails beyond it, naming both
     numbers.
   - `needs_bom` is false for one line with qty 10, and true for two lines.
   - `describe_changes` yields nothing for identical requests and the exact
     fragments for a price and item-count change.
2. **BOM workbook builder.** Build into `tmp_path`, reopen with openpyxl, and
   assert:
   - the header row number (and `DRAFT` when `row=None`);
   - each item row's cells;
   - the shipping and total rows as numbers;
   - the hyperlink on a URL link.

   `bom_filename` slugging covers punctuation, long names and an empty vendor.
   `save_bom` is atomic (no temp files left behind).
3. **Lifecycle handlers**, through the existing fake-client style (prior art:
   `tests/test_13_card_follows_write.py`, `tests/test_17_buyer_picker.py`,
   `tests/test_05_decline_cancel.py`), against a **temp copy** of a workbook and a
   temp `BOMS_DIR`, both monkeypatched in `config`. Never the real ones (AGENTS.md
   §8). Cover:
   - A 3-item approval writes one row, saves `NNNN_<Vendor>_BOM.xlsx` to the temp
     folder, sets that row's Notes cell, uploads the file to the thread, and
     attaches it to the assignee DM.
   - A 1-item approval writes the row with **no** BOM file, **no** Notes and
     **no** upload.
   - A BOM save that raises leaves the row **blank**, with no file and no card
     advance.
   - A totals mismatch at approval writes nothing.
   - `handle_assign` after an unassigned approval attaches the BOM to the new
     assignee's DM.
   - Cancel moves the BOM to `Cancelled/`.
   - Items submitted on a PDF card land in the card's `metadata`, and the button
     `value` contains **no** items.
   - An edit posts exactly one thread line with the right fragments. A no-change
     edit posts nothing.
   - A non-requester, non-buyer, non-admin Edit click gets an ephemeral denial
     with no `views_open` and no `chat_update`.
   - An edit submitted after approval is refused and changes nothing.
   - A same-vendor EPIF drop supersedes the posted card and leaves an approved card
     alone. A different-vendor drop supersedes nothing.

The full gate stays green: `ruff check .`, `python scripts/check_tests_first.py`,
`pytest -q`.

## Out of Scope

- **Matching Smeet's exact spreadsheet layout.** The standard column set is used
  for now. Isaac may supply the template later as a separate change.
- **Multi-EPIF threads under the keyword path.** `@Purchasing approved` still finds
  the newest card. That is a known limitation, unchanged.
- **Editing after approval.** The path is cancel and resubmit. No per-item control
  on an approved batch (CONTEXT.md **Batch**).
- **Editing vendor or route** (interview Screen 1) on a posted card.
- **Editing EPIF-derived fields on a PDF-born card.** Upload a corrected EPIF
  instead.
- **Parsing line items out of EPIF text, or scraping vendor web pages** for names
  and prices.
- **A new Purchasing Log column** for the BOM. The Notes column carries it.
- **Moving archived EPIFs to `Cancelled/` on cancel.** Today cancel doesn't do this
  for EPIFs, and this set only adds it for BOMs.
- **Reviving `src/store.py`.** Items live in message metadata. The store stays
  dead.

## Further Notes

- **Human task before deploying:** create the `BOMs` folder beside `EPIFs` and
  `Quotes` in the OneDrive `Purchasing` folder on the production server, and set
  `BOMS_DIR` in the server's `.env`. Isaac has to be physically at the server.
  Should be its own `human-task` ticket.
- The bot already has `files:write` (used by `logs all` and `/blank-template`), so
  uploads need no new Slack scope.
- **Uncommitted on `master`:** ADR 0006, the `CONTEXT.md` edit, and this spec.
  Commit all three before branching. An implementing agent cannot read a file that
  was never committed.
