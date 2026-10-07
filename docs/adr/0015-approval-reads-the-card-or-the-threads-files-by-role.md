# ADR 0015 — Approval reads the card, or the thread's files by role; a dropped EPIF waits for approval

**Status:** accepted
**Date:** 2026-10-07
**Amends:** ADR 0010 (a dropped EPIF no longer posts a card), ADR 0006 decision 9
(superseding is no longer created), ADR 0012 decision 1 (no **Add items** on a dropped
EPIF) and decision 2 (role by field — extended to thread files by type),
`handle_epif_processing`'s "Ticket 14" resolution order.

## Context

Production, 2026-10-05. A requester submitted `/new-purchase` with a vendor quote in the
Quotes field. The bot re-posted the quote PDF in the thread (ADR 0012 decision 5). When
the approver pressed **Approve** on the card, `handle_epif_processing` looked for "the
newest PDF in the thread" *before* reading the card it was pressed on, found the quote,
tried to read it as an EPIF form, and failed with "This PDF has no fillable form
fields". Nothing was approved. The error DM went to the quote's poster — the bot itself
— so the approver was never told.

`slack_io.find_epif_in_thread` treats any file ending `.pdf` as the EPIF: it does not
look at who posted it or whether it is a form. A test (`test_14_approve_payload.py`,
case 2, "PDF in thread beats posted_payload") encoded that order as intended.

## Decision

### 1. The Approve button approves the card it is on

A click on **Approve** reads the request from that card. It never searches the thread
for an EPIF. A file passed to the handler directly still comes first; the thread search
is gone from the button path.

Cards posted from a dropped EPIF before this change carry no file reference. For those
cards only (`source == "epif"`), the button falls back to the thread search in
decision 2. After decision 3 no new such cards are made.

### 2. What counts as an EPIF in a thread

When the bot searches a thread for an EPIF (`@Purchasing approved`, and decision 1's
fallback):

- Files posted by the bot itself are skipped.
- A PDF is an EPIF only if its AcroForm has the EPIF's fields (`Amount of Purchase` and
  `Vendor` at minimum).
- A PDF with no form fields whose file name contains "epif" (any case) still gets the
  existing flattened-PDF error, as `handle_epif_drop` does today.
- Any other PDF is not an EPIF and is never parsed as one.

### 3. A dropped EPIF posts no card

Dropping an EPIF in a thread no longer posts a card with Approve / Decline. The bot reads
it and replies in the thread in plain text, with no buttons:

> 📄 EPIF read: *{item}* — {vendor}, ${total}. Waiting for approval.

Problems the bot can see at once (flattened PDF, missing fields, a P-card at $5,000 or
more — ADR 0017) are reported in that reply instead, and to the uploader by DM
(ADR 0016). The card appears when an approver types `@Purchasing approved`, already in
the `approved` state (ADR 0010 decision 1). This matches **Request** in `CONTEXT.md`:
before approval there is only a conversation.

Because no posted card exists, nothing is superseded and there is no **Add items** or
**Edit** on a dropped EPIF. A requester who wants a BOM with a dropped EPIF drops their
own `.xlsx` / `.csv` in the thread (decision 4) or uses `/new-purchase`.

### 4. At `@Purchasing approved`, the thread's files are taken by type

If the thread holds a posted card, the keyword approves that card, exactly as the button
does (decision 1). Otherwise the bot takes every file a person posted in the thread:

| File | Role |
|---|---|
| PDF with the EPIF fields (decision 2) | **EPIF** |
| `.xlsx` or `.csv` | **BOM** (attached, ADR 0012) |
| any other PDF | **Quote** |
| images, anything else, the bot's own files | skipped |

Files already saved with `@Purchasing quote` are not saved twice. More than one BOM file
is refused, naming the files: "One BOM per EPIF — delete the extra and approve again."

### 5. Several EPIFs are a batch

Two or more EPIFs in the thread are a **batch**: each gets its own row and its own card,
approved together. EPIFs from the same uploader for the same vendor collapse to the
newest — the older one is an earlier draft. A batch with a BOM file in the thread is
refused, because the bot cannot tell which EPIF it belongs to without reading it
(ADR 0010 decision 5): "This thread has N EPIFs and a BOM — I can't tell which EPIF the
BOM belongs to. Put each vendor's order in its own thread." Quotes in a batch are
archived with every EPIF's row (one copy per row, named for that row), so each card's
buyer gets them in their DM.

### 6. The request-log entry is created at approval for a dropped EPIF

A dropped EPIF that is never approved leaves no trace, like a declined request
(ADR 0003). Modal cards keep creating their entry when posted.

## Consequences

- `test_14_approve_payload.py` case 2 is rewritten in place to assert the card wins.
- `slack_io.find_epif_in_thread` changes meaning (decision 2) and a classifier for thread
  files is added; both are pure over a list of Slack messages plus a PDF reader.
- The **Add items** / **Edit** handlers for PDF-born cards, and the superseding code,
  stay for cards posted before this change and are removed later, not here.
- `CONTEXT.md`: **Quote**, **Superseded**, **Edit**, **Batch** and **Bare-thread
  approval** are updated; **Thread files at approval** is added.
