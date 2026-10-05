# Spec — Attach a BOM and quotes instead of typing them

**Status:** ready-for-agent
**Binding:** `docs/adr/0012-attached-boms-and-quotes-are-carried-not-read.md`,
`docs/adr/0006-bom-line-items-and-editable-posted-cards.md` (decisions 1, 4, 6, 8 amended
by 0012 for attached files only), `docs/adr/0008-bom-sheet-follows-the-lab-layout.md`,
`docs/adr/0010-linked-cards-and-direct-message-help.md` (decision 5: the bot never guesses),
`docs/adr/0001-tests-first-and-no-muted-failures.md`
**Glossary:** `CONTEXT.md` — **BOM** (made vs. attached), **Quote** (new), **Line item**,
**Edit**, **Posted**, **Batch**
**Builds on:** `.scratch/bom-and-card-editing/` (paste box, made BOM, Add items, Edit).

## Problem Statement

Lab members already keep their order in a spreadsheet and get vendor quotes as PDFs.
To put a multi-item order into the bot they must retype every row into the paste box,
in the box's fixed column order, which matches nobody's spreadsheet. Quotes can only be
saved by typing `@Purchasing quote` in the thread with the file attached, which nobody
remembers, so quotes end up as loose files the buyer has to dig out of the thread.

Every lab spreadsheet is laid out differently — different columns, sometimes no unit
price, links hidden behind cells that just say "Link", the total in a different place —
so the bot cannot read them without guessing. And for the EPIF the only number that
matters is the total, which the requester already types.

## Solution

Every form where items are entered — interview Screen 2 of `/new-purchase`, **Add items**
on a card born from a dropped EPIF, and **Edit** on a posted card — gains two optional
file fields: **BOM** (one `.xlsx` or `.csv`) and **Quotes** (PDFs, up to 10). The bot
never opens these files. It posts them in the thread so the approver sees them, and at
approval archives them next to the EPIF and hands them to the assigned buyer in the
email-draft DM, exactly as it does a made BOM today.

Because one EPIF covers one vendor, attaching a BOM brings up a required tick box —
"Every item in this BOM comes from one vendor." A BOM and pasted line items together are
refused, so an EPIF never has two BOMs. On Edit, current quotes are listed as ticked
boxes, so a bad quote can be removed or swapped without starting over.

## User Stories

1. As a requester, I want to attach my own BOM spreadsheet in `/new-purchase`, so that I don't retype rows I already have.
2. As a requester, I want to attach a `.csv` as well as an `.xlsx`, so that a sheet exported from Google Sheets works.
3. As a requester, I want to attach vendor quote PDFs in `/new-purchase`, so that the quotes travel with the request instead of being lost in the thread.
4. As a requester, I want to attach more than one quote, so that an order quoted in parts is covered.
5. As a requester with more than 10 quotes, I want the field hint to tell me to drop the rest in the thread with `@Purchasing quote`, so that I'm not stuck at Slack's limit.
6. As a requester, I want the Quotes field to accept only PDFs, so that a spreadsheet can't land in the quotes by mistake.
7. As a requester, I want the BOM field to accept only one `.xlsx` or `.csv`, so that the bot never has to decide which of two files is the BOM.
8. As a requester, I want the bot to keep my BOM exactly as I made it, so that my formatting and formulas reach purchasing unchanged.
9. As a requester, I want the Total Price I type to stay the amount on the EPIF, so that an attached sheet never overrides what I entered.
10. As a requester attaching a BOM, I want a required "Every item in this BOM comes from one vendor" tick box, so that I'm reminded one EPIF covers one vendor.
11. As a requester who leaves that box unticked, I want the form to refuse with "One EPIF per vendor — split this into one request per vendor.", so that I know exactly what to do.
12. As a requester, I want the form to refuse "Attach a BOM or paste line items, not both." when I do both, so that my request never carries two BOMs.
13. As a requester with no spreadsheet, I want the paste box to keep working as before, so that a short order still gets a made BOM.
14. As a requester who drops an EPIF PDF in a thread, I want **Add items** to offer the same two file fields, so that the PDF path is as easy as the form path.
15. As an approver, I want the attached BOM and quotes posted in the thread when the request is posted, so that I see them before I approve.
16. As an approver, I want the posted card to say how many quotes and whether a BOM is attached, so that I can tell at a glance what came with it.
17. As a buyer, I want the archived BOM and quotes attached to my email-draft DM at approval, so that I can forward everything to purchasing in one email.
18. As a buyer, I want an attached BOM archived as `NNNN_<Vendor>_BOM.xlsx` (or `.csv`) in the BOMs folder, so that it sits beside the made BOMs under the same naming.
19. As a buyer, I want quotes archived as `NNNN_<Vendor>_Quote_1.pdf`, `_2`, … in the Quotes folder, so that a log row's quotes are easy to find.
20. As anyone reading the Purchasing Log, I want an attached BOM named in the Notes column like a made BOM, so that the row points at its file.
21. As an approver who declines a request, I want nothing archived to the folders, so that declined orders leave no files behind.
22. As an approver or admin who cancels a request, I want its quotes moved out the same way its BOM is, so that the Quotes folder holds only live orders.
23. As a requester editing a posted card, I want an empty file field to keep what's already attached, so that editing one text field doesn't lose my files.
24. As a requester editing a posted card, I want a new BOM to replace the old one, so that I can fix a wrong sheet.
25. As a requester editing a posted card, I want my current quotes listed as ticked boxes by file name, so that I can untick a bad one to remove it.
26. As a requester editing a posted card, I want to untick a quote and attach a new one in the same edit, so that I can replace it.
27. As a requester editing a posted card, I want newly attached quotes added to the ones I kept, so that I can add a late quote.
28. As anyone in the thread, I want the edit's thread line to name the quotes removed and added and a replaced BOM, so that the change is visible.
29. As a buyer or admin editing someone's posted card, I want the same file controls, so that I can fix attachments for them.
30. As a requester, I want attachments frozen at approval like line items, so that what the buyer emails is what the approver saw.
31. As a requester whose file fails to download from Slack, I want a thread line naming the file and a DM telling me to drop it in the thread with `@Purchasing quote`, so that a missing file is never silent. (A form error is not possible: Slack gives a form 3 seconds to answer, too little to fetch files.)
32. As an admin, I want a missing `BOMS_DIR` or `QUOTES_DIR` at approval reported the way other storage problems are, so that a bad setting is loud.

## Implementation Decisions

- **Slack element.** Both fields are Block Kit `file_input` elements inside `input`
  blocks, marked optional. BOM: `filetypes` `["xlsx", "csv"]`, `max_files` 1. Quotes:
  `filetypes` `["pdf"]`, `max_files` 10 (Slack's maximum). New block ids for each; the
  submitted files arrive in the view state as file objects and are fetched with the
  existing download helper (bot scope `files:read`, already required).
- **Role by field.** A file's role is the field it came in through. No extension sniffing
  beyond what `filetypes` enforces, and the bot never opens the file's contents.
- **One-vendor box.** A `checkboxes` input with one option, shown on every form that has
  the BOM field. Validation on submit: a BOM attached and the box unticked → field error
  on the box with the exact text in story 11. Because Slack modals cannot show a block
  conditionally without a view update, the box is always present, labelled "Required if
  you attach a BOM"; it is ignored when no BOM is attached.
- **Attach or paste.** Validation on submit: a BOM file and a non-empty line-items box →
  error on the BOM field with the exact text in story 12. This sits beside the existing
  items/total validation in the submit handlers and uses the same error mechanism.
- **Where attachments live before approval.** Card metadata (the same Slack message
  metadata that carries line items, ADR 0006 decision 5) gains an `attachments` entry:
  the Slack file ids and names of the BOM and each quote, with a role. Never in the button
  value. The request log's existing `attachments` field is filled from it at approval.
- **Posting.** When the card is posted, the bot shares the attached files into the thread
  (re-posting via upload, like the made-BOM draft today) with one line naming them. The
  card summary gains "BOM attached" and "Quotes: N".
- **Approval.** In the approval path that archives a made BOM today, an attached BOM is
  instead saved as `NNNN_<Vendor>_BOM.<ext>` in `BOMS_DIR` with the original extension,
  named in the Notes column as the made BOM is. Quotes are saved as
  `NNNN_<Vendor>_Quote_<k>.pdf` in `QUOTES_DIR`, k from 1 in attachment order. Both are
  attached to the assignee's email-draft DM beside the EPIF. For a **batch**, each EPIF's
  request carries its own attachments.
- **One BOM per EPIF.** An attached BOM replaces the made BOM; a request never has both.
  The two-distinct-lines rule (ADR 0006 decision 3) applies only to made BOMs.
- **Decline / cancel.** Decline saves nothing. Cancel moves archived quotes out alongside
  the BOM, reusing the existing move-to-cancelled behaviour for BOMs.
- **Edit.** The edit modal adds a `checkboxes` block listing current quotes by file name,
  all initially ticked, plus the two empty file fields. Result: kept quotes (ticked) +
  new quotes; a new BOM replaces the old; an empty BOM field keeps the old. The existing
  change-description function gains lines for quotes removed, quotes added, and BOM
  replaced. PDF-born cards' Edit / Add items get the same file controls (an amendment to
  ADR 0006 decision 8, recorded in ADR 0012).
- **Storage errors.** A missing or bad `BOMS_DIR` / `QUOTES_DIR` at approval is reported
  through the existing approval storage-problem path (ADR 0009), naming the setting.

## Testing Decisions

- Tests check what a person would see: the form errors and their text, thread posts and
  which files they carry, the card summary text, the file names written to temporary BOM
  and Quotes folders, the Notes cell, the files attached to the buyer's DM, and what was
  **not** written or sent. A test that only asserts a mock was called is not enough.
  ADR 0001 applies: tests first, no muted failures.
- **One seam: the app's Slack handlers, driven with a fake client.** Submit Screen 2,
  Add items and Edit through their `view_submission` handlers; approve through the
  existing approval path; decline and cancel through their buttons. Prior art:
  `tests/test_28_line_items_modal_path.py`, `tests/test_27_line_items_epif_path.py`,
  `tests/test_29_approval_archives_bom.py`, `tests/test_30_buyers_dm_carries_bom.py`,
  `tests/test_31_cancel_moves_bom.py`, `tests/test_32_edit_a_posted_card.py`.
- May fake: the Slack client (including the file download, which returns fixed bytes) and
  the workbook lock queue. Must be real: the submit validation, card builder, metadata,
  archive naming and the file writes into temporary `BOMS_DIR` / `QUOTES_DIR`; the
  workbook Notes write on a temporary copy.
- Use a real lab-style `.xlsx` with a formula total as the BOM fixture, and assert the
  archived file is byte-identical to what was attached (proof it was carried, not read).
- Cover at least: BOM only; quotes only; both; BOM + pasted items refused; BOM with box
  unticked refused; no files behaves exactly as before; approval naming for `.xlsx` and
  `.csv`; three quotes numbered 1–3; decline writes nothing; cancel moves quotes out;
  Edit keep / remove / replace / add; a download failure posts a thread line and DMs the requester.

## Out of Scope

- Reading anything inside an attached file: no total check, no line extraction, no
  header matching, no re-layout into the lab BOM format.
- A downloadable BOM template (the follow-up if purchasing objects to mixed layouts).
- Changing attachments after approval (cancel and resubmit, or `@Purchasing quote`).
- Detecting multiple vendors in a sheet.
- Image quotes (PDF only).

## Further Notes

- The UHV valve sheet that prompted this has items from more than one vendor; the tick box
  is how the requester confirms, because a manufacturer column does not name the vendor.
- Slack cannot pre-fill a `file_input`, which is why Edit lists current quotes as
  checkboxes rather than showing them in the file field.
