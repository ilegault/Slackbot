# ADR 0006 — Line items, the BOM spreadsheet, and editable posted cards

**Status:** accepted
**Date:** 2026-09-21
**Related:** ADR 0002 (lifecycle and surfaces), ADR 0003 (decline / cancel), ADR 0005 (the posted card)
**Superseded in part:** decision 10 (sheet layout) by ADR 0008

## Context

Dylan, 2026-09-21: an order of five different parts from one vendor (his example:
five Ruland links) is still one EPIF, but sending Tina five bare links in an email
is a mess. He asked for a spreadsheet — a **BOM** — listing each item with its name,
link, description, quantity, unit cost and line total, sent *alongside* the EPIF.
Smeet has been making these by hand.

**One EPIF per vendor does not change.** A BOM is an attachment to one EPIF, never a
way to put two vendors on one request.

The EPIF itself cannot carry line items: it has one `What is being purchased` field
and one `Amount of Purchase`. So the bot has nothing to build a BOM *from* on either
path today. The line items need an input.

Separately, a requester has no way to fix a card once it is posted. The only move is
Decline and start again, or drop a corrected EPIF, which leaves the old card live with
its own Approve button — two approvable cards for one purchase.

## Decision

### 1. Line items are entered through one items form, used by both paths

- **Modal path** (`/new-purchase`): interview Screen 2 gains an optional multiline
  **Line items** box.
- **PDF path** (EPIF dropped in a thread): the posted card gains an **Add items**
  button that opens a modal containing the same box.

One parser and one validation rule serve both. There is no second implementation
(invariant 1).

### 2. The box is a paste box, one line per item

```
qty | item name | part number | unit price | link | description
```

`|` or a tab separates fields, so rows pasted straight out of Excel or Google Sheets
work. `part number`, `link` and `description` may be empty. One optional line
`shipping | <amount>` carries shipping and tax. Blank lines are ignored. Errors are
reported per line ("line 3: unit price 'abc' is not a number").

Parsing is a pure function in the domain layer — no Slack, no I/O — so it can be
tested against pasted text directly.

### 3. A BOM exists when there are two or more distinct lines

Quantity does not count: ten of one part is one line and gets no spreadsheet. Two or
more lines produce a BOM. One line is accepted and stored, but produces no file.

### 4. The items must add up to the EPIF amount

`sum(qty × unit price) + shipping` must equal the request's total price to within
$0.01. If it doesn't, the items are refused and both numbers are shown. On the modal
path the Total Price field stays required and is checked the same way. Nothing is
logged against a BOM that disagrees with the EPIF Tina receives.

### 5. Items live in the card message's metadata, never in the button value

The card's button `value` is capped at ~2 000 characters by Slack and already carries
the parsed request. Five items with links would overflow it. Line items therefore ride
in the posted card message's Slack `metadata` (`event_payload["items"]`, a list of
dicts), the same channel `find_request_metadata_in_thread` already reads. The button
value never carries items. This extends invariant 3 ("the message is the store") to
message metadata. It does **not** revive `src/store.py`.

### 6. The BOM is posted, archived, pointed at, and sent

- **When items are entered** (before approval): the bot posts a draft BOM to the
  thread so Charlie sees the itemised list before approving. It is not archived.
- **At approval**: the BOM is regenerated with the log row number in its header, and
  saved as `BOMS_DIR/NNNN_<Vendor>_BOM.xlsx`. `NNNN` is the Purchasing Log row,
  zero-padded to 4 digits. This happens inside the same queued write task as the row
  append, so it is all-or-nothing. The row's **Notes** column (Y) gets
  `BOM: NNNN_<Vendor>_BOM.xlsx (N items)`. The archived file is uploaded to the thread.
  It is also attached to the assignee's email-draft DM, whether assignment happens at
  approval or later.
- `BOMS_DIR` is a new OneDrive folder beside `EPIFs/` and `Quotes/`. It is configured
  like them and checked at startup like them.

### 7. Items are frozen at approval

Add / Edit items exist only on a **posted** card. After approval the BOM is fixed; to
change it, Cancel and resubmit. On Cancel the archived BOM moves to
`BOMS_DIR/Cancelled/`, keeping its prefix, the same way the row is un-written.

### 8. A posted card can be edited, depending on how it was born

- **Modal-born card**: **Edit** reopens interview Screen 2, pre-filled, covering every
  detail field plus the items box. Vendor and route (Screen 1) are not editable;
  to change vendor, Decline and resubmit.
- **PDF-born card**: **Edit** edits line items only. The EPIF PDF is the source for
  every other field; to change one, upload a corrected EPIF (decision 9).

Permission: the requester, any buyer, or an admin. Everyone else gets an ephemeral
denial (invariant 5). Editing is refused once the card is not in `posted` state.

Each edit updates the card in place (blocks and metadata). It also posts **one**
thread line listing what changed, e.g.
`✏️ Edited by Dylan: Total $412.00 → $455.50; items 4 → 5`, and appends the same
line to the card's history. When the items changed, the draft BOM is re-posted.

### 9. A corrected EPIF supersedes the old card

When an EPIF is dropped in a thread that already has a **posted** card from the same
requester for the same vendor (vendor compared case-insensitively, whitespace
trimmed), the older card becomes terminal. It keeps its summary, loses every button,
and reads `Superseded by a newer EPIF below`. Items do not carry over. Approved or
later cards are never superseded.

### 10. Sheet layout is the standard column set for now

Header block: vendor, requester, project ID / fund, the log row (or `draft`), date.
Columns: `#`, `Item`, `Part #`, `Description`, `Link`, `Qty`, `Unit cost`,
`Line total`. Below them: a `Shipping / tax` row and a `Total` row. The file is newly
created with openpyxl. The x14 formatting hazard applies only to
`Purchasing-Log.xlsx` and does not apply here. Matching Smeet's exact layout is a
later, separate change.

## Consequences

- `CONTEXT.md` gains **BOM**, **Line item**, **Edit** and **Superseded**.
- A new storage path, `BOMS_DIR`, has to exist on the production server and be set in
  its `.env` before this can be deployed. That is a human task.
- The thread keyword `@Purchasing approved` still finds only the newest card in a
  thread. Multi-EPIF threads remain a known limitation, and this ADR does not change
  that.
