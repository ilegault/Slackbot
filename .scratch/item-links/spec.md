# Spec — Every item has a link or a reason

**Status:** ready-for-agent
**Binding:** ADR 0020 (every item has a link or a reason, and links live in the BOM file —
supersedes ADR 0019 decision 1 and part of decision 2, and ADR 0006 decision 5 for item
links), ADR 0019 (BOMs come in through the lab template and are read), ADR 0015 (thread
files at approval), ADR 0001 (tests first, no muted failures)
**Glossary:** `CONTEXT.md` — new: **Item link**, **No-link reason**. Rewritten: **Line
item**, **BOM template**, **BOM check**.

## Problem Statement

Purchasing works from the BOM a buyer receives. A BOM where every item name opens the
product page is much faster to order from than one where the buyer has to search for each
part. Today a link is optional and nearly invisible: the only way to give one is to
hyperlink the Item cell in Excel, the BOM check never shows whether a row has one, and an
Excel `=HYPERLINK()` formula is not read as a link at all. So most BOMs reach purchasing
with no links and nobody notices until the buyer is ordering.

A one-item request has the same gap: Screen 2's "Link to item (optional)" field is often
left blank.

Links were left optional partly because long URLs do not fit in Slack: a button value is
capped at 2,000 characters, a section block at 3,000, and Slack publishes no size limit
for message metadata, where line items currently ride with their links.

## Solution

The **BOM template** gains a plain-text **Link** column. On the form path, every item
must have an **item link** or a **no-link reason**: on the **BOM check**, each row without
a link asks the requester to pick **No web page** or **Covered by another row's link**, and
Continue is refused until every such row has a choice. A one-item request must fill its
link field or tick **No web page**.

Links never pass through Slack. The bot reads them from the uploaded spreadsheet, writes
them (and the reasons) into the draft BOM it posts in the thread, and at approval reads
them back from that draft to build the final BOM. The file the assigned buyer and
purchasing receive has a clickable Link column and hyperlinked item names. The check
screen shows only each link's site name.

## User Stories

1. As a requester, I want a Link column in the BOM template, so that I can paste each item's product page as plain text instead of hyperlinking cells.
2. As a requester, I want to paste a link with or without `https://`, so that copying from the address bar always works.
3. As a requester, I want links of any length accepted, so that I never have to shorten a vendor's URL.
4. As a requester, I want a row whose Item name I hyperlinked (and whose Link cell I left blank) to count as linked, so that the old habit still works.
5. As a requester, I want the BOM check to show each row's link as its site name, so that I can see at a glance which rows have a link and click one to check it.
6. As a requester, I want each row without a link to ask me why, with a required choice of **No web page** or **Covered by another row's link**, so that I can explain a gap in one click instead of editing the spreadsheet.
7. As a requester, I want Continue refused while any row without a link has no reason picked, so that I can't send an incomplete BOM by mistake.
8. As a requester, I want a clear message when I upload an old copy of the template that has no Link column, plus the button that sends me the new one, so that I know what to fix.
9. As a requester, I want a Link cell that isn't a web address (spaces in it, or no dot) flagged by row number, so that a typo doesn't reach purchasing.
10. As a requester filing a one-item request, I want the link field required unless I tick **No web page**, so that the same rule applies with or without a BOM.
11. As a requester filing a one-item request, I want a URL I already put in Purpose to count as the link, so that I'm not asked twice.
12. As a requester using **Add items**, **Edit** or **Replace BOM**, I want the same link check and reason choice, so that every route that takes a BOM behaves the same.
13. As an approver, I want the draft BOM in the thread to show each item's link or reason, so that I can see what is being bought before I approve.
14. As an assigned buyer, I want the BOM in my DM to have a clickable Link column and hyperlinked item names, so that I can open each product page directly.
15. As an assigned buyer, I want rows without a link to say **No web page** or **Covered by another row's link** in the Link column, so that I know the gap is on purpose.
16. As purchasing, I want the archived BOM to carry the same links and reasons, so that the file I'm sent is complete.
17. As a requester, I want approval to keep the links I gave even though Slack never stored them, so that nothing is lost between posting and approval.
18. As an approver, I want approval to go ahead even if the bot's draft BOM has been deleted from the thread, and the requester asked to **Replace BOM**, so that a missing file never blocks a purchase.
19. As a requester who drops a BOM straight into a thread, I want it handled exactly as today with no link check, so that the thread path is unchanged.
20. As the developer, I want long links kept out of Slack message metadata, so that a 50-row BOM can never hit Slack's undocumented `metadata_too_large` limit.

## Implementation Decisions

- **Template file.** The bundled BOM template gets a `Link` column right after `Product #`.
  The column order becomes
  `Item | Description | Product # | Link | Vendor | Unit Cost | Quantity | Total Cost | Notes`.
  The header block, the Total row and live formulas keep their meaning. Formulas move
  with their columns: Total Cost is Quantity × Unit Cost, which are now one column further
  right. The template header constant in config changes to match. The filled-example test
  fixture is rebuilt to the new layout with a link on every row.
- **Reader (`bom.read_bom_template`).** It stays a pure function from bytes to
  `(items, problems)`, so it can be tested without Slack.
  - Header match stays exact (case and surrounding spaces ignored). A header row that
    matches the *previous* set exactly is refused with its own problem sentence, naming
    the file as the old BOM template with no Link column. Any other mismatch is still the
    existing "not the template" problem.
  - Each item gains `link` and `no_link_reason`. `link` is the Link cell's text if it
    looks like a web address (contains a dot, no spaces), with `https://` added when it
    starts with neither `http://` nor `https://`. If the Link cell is blank, the Item
    cell's hyperlink target is used.
  - A Link cell whose exact text (case-insensitive, spaces trimmed) is one of the two
    reason phrases, `No web page` or `Covered by another row's link`, gives an empty
    `link` and that reason in `no_link_reason`. This is how the reason survives in the
    draft file for the approval rebuild.
  - A Link cell holding anything else is a row problem: "Row N: Link '…' isn't a web
    address."
  - A blank Link cell with no Item hyperlink is **not** a reader problem. The item comes
    back with an empty `link` and empty `no_link_reason`. The BOM check asks for the
    reason; the thread path ignores it.
- **Builder (`bom.build_bom_workbook`).** It writes the new layout. The Link cell holds the
  URL as a clickable hyperlink, or the reason text when there is no link. The Item cell is
  hyperlinked to the same URL when there is one. Reading back a built file gives the same
  items (links and reasons included). This round trip is what lets approval rebuild from
  the draft.
- **BOM check view.** Each preview row shows its link as a clickable site name: the host
  with any leading `www.` removed, as mrkdwn `<url|host>`. A row without a link shows
  "no link". After the preview, one required radio-button input per row that has neither a
  link nor a reason, labelled with the row's spreadsheet number and item name, with exactly
  two options: `No web page` and `Covered by another row's link`. The block cap is 100;
  with at most 4 preview sections, 50 rows and a few fixed blocks it fits. Each block's
  `block_id` encodes the spreadsheet row number, so the submit handler can match a pick to
  its row without putting items in `private_metadata`. That field holds 3,000 characters,
  and items with links would overflow it.
- **BOM check submit.** Continue is refused with a per-block error on every reason input
  left unpicked. Picks are applied to the items by row number. A re-upload on the check
  screen re-reads the file and redraws the screen, and the reason inputs start empty.
  The same view and submit handler serve interview Screen 2, **Add items**, **Edit** and
  **Replace BOM**. No route gets its own copy.
- **One-item request, Screen 2.** The link input stops being optional in meaning; the
  Slack block stays `optional: true` so the handler can apply the rule. A new checkbox
  input with the single option `No web page` sits beside it. On submit: if the link field
  is blank, no URL is in Purpose, and the box is unticked, the view returns an error on
  the link block. A link that isn't a web address is refused the same way the reader
  refuses one. When the box is ticked and the field is blank, the request's Link is empty
  and the card shows "No web page" where the link would be. The rule applies only when the
  request has no BOM.
- **Links leave the card's metadata.** Line items stored in the card message's metadata
  no longer carry `link`; they keep `no_link_reason` only as a flag that the row was
  explained. Every place that writes items to card metadata strips `link`.
- **Approval reads links from the draft.** At approval of a request whose items came
  from a BOM, the bot lists the thread's files, takes the newest file it posted itself
  whose name starts with `DRAFT_HIRST_LAB_BOM_`, downloads it, and reads it with the
  reader. It reuses the thread-file listing and download helpers that **Thread files at
  approval** already uses. Those links and reasons are merged onto the card's items by
  position before the final BOM is built. The merge is refused, and the next step taken,
  if the draft's row count, item names or quantities differ from the card's items.
  - No draft found, the download fails, or the merge is refused → approval still goes
    ahead and the final BOM is built from the card's items without links. The thread is
    told the links could not be recovered and asks the requester to use **Replace BOM**,
    reusing the existing Off-template wording and buyer-DM flag.
- **Replace BOM after approval** reads links straight from the newly uploaded file (it
  passes the BOM check like every other route), so it needs no draft lookup.
- **Thread-dropped BOMs.** At **Thread files at approval** the reader runs as today. Blank
  links and missing reasons are not problems there, and an old-template file is still an
  **Off-template BOM** exactly as ADR 0019 decision 7 says.
- **Help text.** Every place that tells a requester the template's columns names the Link
  column. That includes the BOM field hints and the template kit's guide text, if it lists
  columns.

## Testing Decisions

- Tests exercise behaviour through the highest existing seam and assert what a person
  would see: rows and problems returned, cell values and hyperlinks in a real workbook,
  view `callback_id`s and `errors`, and text posted to a fake Slack client. No test
  asserts that an internal helper was called.
- **Seam 1 — reader and builder, pure.** Real `.xlsx` bytes in, items or a workbook out.
  Cover: link with and without a scheme; Item-hyperlink fallback; both reason phrases;
  bad Link text gives a row problem; blank link with no hyperlink gives an empty link and
  no problem; the old template's headers give the old-template problem; built → read
  round trip keeps links and reasons; the built Link and Item cells carry hyperlinks.
  Prior art: `test_131_read_bom_template`, `test_132_bom_round_trip`.
- **Seam 2 — view submissions through the app with a fake client.** Screen 2 with a BOM:
  the check view shows site names and one reason input per unlinked row; a submit with an
  unpicked reason returns an error on that block; picking all reasons moves on. Screen 2
  one-item: blank link, no URL in Purpose and no tick → error on the link block; ticking
  **No web page** → accepted. **Add items**, **Edit** and **Replace BOM** each reach the
  same reason inputs. Prior art: `test_134_screen2_bom_check`,
  `test_135_edit_and_add_items_bom`, `test_137_replace_bom`.
- **Seam 3 — approval with a fake client whose thread holds the bot's draft file.** The
  archived BOM (written to a temporary `BOMS_DIR`) has the draft's links and reasons while
  the card metadata has none. With the draft absent, approval still writes the log row,
  the archived BOM has no links, and the thread gets the Replace BOM request. The card's
  metadata never contains a `link` key for a BOM item. Prior art:
  `test_29_approval_archives_bom`, `test_136_thread_bom`.
- What may be faked: the Slack client, file downloads (returning real bytes built by
  the builder) and the clock. What must be real: the reader, the builder, the workbook
  and archive writes, on temporary copies.
- Existing tests and fixtures built on the ADR 0019 header set are rewritten in place
  under their existing names; ADR 0020 authorises it. None are deleted.

## Out of Scope

- Visiting links to check they load.
- Any link check on BOMs dropped into a thread, beyond what the reader already does.
- A "same as row N" pointer; **Covered by another row's link** is a plain reason with no
  target row.
- Links for EPIF-born (PDF) requests or the Workday path's one-item link, beyond what
  Screen 2 already collects.
- Migrating BOMs already posted or approved before this lands.
- Showing full URLs anywhere in Slack.

## Further Notes

- Slack documents no size limit for message metadata, only a `metadata_too_large` error.
  Keeping links out of the card's metadata removes that risk instead of guessing a cap.
- Every template copy handed out before this lands stops working on the form path.
  Requesters get the new one from the button on the check screen or `/blank-template`.
- This effort touches `docs/adr/` and `CONTEXT.md` only through the developer's own
  commit; no ticket in it should edit either.
