# ADR 0012 — Attached BOMs and quotes are carried, never read

**Status:** accepted
**Date:** 2026-10-05
**Amends:** ADR 0006 decisions 1, 4, 6 and 8 for attached files only. A **made** BOM
(built from pasted line items) is unchanged, and so is ADR 0008's layout for it.

## Context

Lab members already build their own BOMs in Excel and receive vendor quotes as PDFs.
Today the only way in is retyping the rows into the paste box in its fixed column order,
or typing `@Purchasing quote` in the thread with a file attached. Two real lab BOMs
(a Prusa order and a UHV valve assembly) share almost nothing: different columns, one
with no unit price, links hidden behind cells that say "Link", the total in a different
place in each. Reading them would mean guessing, and the bot never guesses (ADR 0010
decision 5). What purchasing needs from the EPIF is the total, and the requester
already types it.

## Decision

### 1. Two upload fields on all three item forms

Interview Screen 2, **Add items** on a PDF-born card, and **Edit** each gain two
optional file fields: **BOM** (`.xlsx` or `.csv`, at most one file) and **Quotes**
(PDF only, up to 10 — Slack's limit for one field; the hint points to
`@Purchasing quote` in the thread for more). The field a file arrived in is its role.

### 2. Carried, never read

An attached BOM or quote is never opened by the bot. There is no items-add-up check
against it (ADR 0006 decision 4 applies to pasted items only) and no re-layout. The
typed Total Price is the amount.

### 3. One vendor, confirmed by the requester

Beside the BOM field sits a checkbox, "Every item in this BOM comes from one vendor.",
always shown (a Slack form cannot reveal a block when a file is picked) and required
only when a BOM is attached. Unticked with a BOM, the form refuses: "One EPIF per vendor — split this into one
request per vendor." A Manufacturer column would not do this job: a manufacturer is not
the vendor (Swagelok parts bought from IMS Supply).

### 4. Attach or paste, not both

A BOM file and pasted line items together are refused: "Attach a BOM or paste line
items, not both." One EPIF has at most one BOM.

### 5. Where the files go

At submission the files are posted in the thread, so the approver sees them. At
approval the BOM is archived as `NNNN_<Vendor>_BOM.<xlsx|csv>` in `BOMS_DIR` and named
in the Notes column, as a made BOM is; quotes as `NNNN_<Vendor>_Quote_<k>.pdf` in
`QUOTES_DIR`. Both are attached to the assigned buyer's email-draft DM. Decline archives
nothing; cancel moves quotes out the same way it moves the BOM.

### 6. Editing

Slack cannot pre-fill a file field, so on **Edit** an empty field keeps what is there.
A new BOM replaces the old one. Current quotes are listed as pre-ticked checkboxes by
file name: untick to remove, untick and add to replace, add to append. The edit's
thread line names what was removed and added. Edit stays pre-approval only.

## Consequences

- Purchasing receives BOMs in mixed layouts. If that becomes a problem, a BOM template
  whose exact headers the bot can read is the next step, not header guessing.
- A wrong attached BOM total is caught by people, not by the bot.
