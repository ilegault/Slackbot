# ADR 0020 — Every item has a link or a reason, and links live in the BOM file

**Status:** accepted
**Date:** 2026-11-02
**Supersedes:** ADR 0019 decision 1 ("There is no Link column; links are not asked for")
and the sentence of decision 2 that makes a link optional ("none is required"); ADR 0006
decision 5 as far as it puts item links in the card's metadata. The one-item **Link**
field stops being optional on the form. Everything else in ADR 0019 stands.

## Context

The developer wants every BOM purchasing receives to carry a link to each item's page:
a BOM with links is easier for the buyer and Tina to work from. Under ADR 0019 a link
could only be given by hyperlinking the Item cell (Ctrl+K), which nobody can see on the
check screen, so missing links went unnoticed. An Excel `=HYPERLINK()` formula gave no
link at all.

The earlier worry was that long links do not fit in Slack: a button value is capped at
2,000 characters, a section block at 3,000, and Slack documents no size for message
metadata (only a `metadata_too_large` error). That worry is removed by keeping links out
of Slack: Python reads and writes them in the spreadsheet, where length is no problem.

## Decision

1. **The template gains a plain-text Link column** after Product #:
   `Item | Description | Product # | Link | Vendor | Unit Cost | Quantity | Total Cost | Notes`.
   A copy without it is refused as the old BOM template, with the "Send me the BOM
   template" button. No length limit on links.
2. **What counts as a link.** A cell that looks like a web address: it has a dot and no
   spaces. One without `http://` or `https://` gets `https://` added. The bot never
   visits a link. If the Link cell is blank and the Item cell is hyperlinked, that
   hyperlink is the item link.
3. **A missing link needs a reason, picked on the check screen.** Each row with no item
   link shows a required choice: **No web page** or **Covered by another row's link**.
   Exactly one must be picked; Continue is refused until every such row has one. Rows
   with a link show no choice. Each row's link is shown as its site name, clickable.
4. **Same rule for a one-item request.** Screen 2's link field must hold a link, or the
   requester ticks **No web page**. A URL already in Purpose counts as the link.
5. **Links live in the BOM file, never in Slack.** The card's metadata holds line items
   without links. The draft BOM posted in the thread holds the item links, with each
   no-link reason written as text in that row's Link cell. At approval the bot reads its
   own newest draft BOM in the thread to rebuild the final file. If that draft is gone,
   approval still goes ahead and the bot asks for **Replace BOM**.
6. **The file purchasing receives** has the Link column filled with clickable links (or
   the reason text), and each linked Item name is hyperlinked too.
7. **The thread path is not checked for links.** A BOM dropped in a thread is read and
   approved as under ADR 0019 decision 7; a missing link there is not a problem.

## Consequences

- Every form-path BOM and one-item request reaching purchasing has a link or a stated
  reason for each item.
- Every BOM template copy handed out before this lands stops working; requesters must
  fetch the new one.
- Approval now depends on the bot's own draft file in the thread as well as the card.
- Tests and fixtures built on the ADR 0019 header set are replaced, not muted; this ADR
  authorises that.
