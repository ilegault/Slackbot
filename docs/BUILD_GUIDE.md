# P-Bot (Hirst Lab Purchasing Bot) — Build Guide

Your four-phase plan is sound in shape. Three things in it don't survive contact
with the actual files, and one of them would quietly damage the workbook. Those
are called out below where they come up.

---

## What I found in your files

**The EPIF is a real AcroForm.** 28 named fields, values stored in the PDF's form
dictionary. `pypdf.PdfReader(...).get_fields()` returns them all by name in one
call. Field names are things like `What is being purchased`, `Amount of Purchase`,
`Project ID Number`, `room address`, `Email add`. The nine category checkboxes and
the two payment checkboxes come back as `/On` or `/Off`.

So **Phase 3's coordinate mapping is unnecessary** — skip `pdfplumber` entirely.
The only case it would help is a flattened PDF (someone printed to PDF instead of
saving the filled form), and in that case the right answer is to bounce it back to
the requester, not to guess at pixel positions. The code does that.

**The Order Log is an Excel Table, not a plain range.**

| | |
|---|---|
| Table name | `OrderLog`, ref `A11:Z1999` |
| Header row | 11 (rows 3–8 are the greyed-out example block) |
| Data starts | row 12; first empty row today is **17** |
| Columns | **26 (A–Z)**, not 31 |
| Column A | array formula for Order ID — *don't write to it* |
| Column Z | array formula for Status — *don't write to it* |
| Columns H | already has `=Qty*Unit Price` on some rows |

Both formula columns are pre-filled all the way to row 1999, so "appending" really
means *filling in the blanks of a row that already exists*. Nothing needs to be
inserted or extended.

**14 dropdowns constrain what you're allowed to write.** Requester Name, Urgency,
How Buying, EPIF Category, Delivery Room, Project ID, Fund, Received By, Status.
Their source lists are on the `Roles & Lists` sheet and are mirrored into
`config.py`. Write a value that isn't in the list and Excel marks the cell invalid
— so validation has to check against the lists, not just check for "not empty".

---

## The Lab Purchasing Lifecycle

```
1. Approval: Charlie replies "@p-bot approved"
   -> Bot logs row to Purchasing-Log.xlsx & saves EPIF to EPIFs/
   -> If Undergrad: Pings grad student buyers to claim
   -> If Grad Student: Pings requester with ready-to-use email draft

2. Claiming: Grad student replies "@p-bot claim"
   -> Bot tags grad student and requester to collaborate on punchout/cart

3. Processing: Grad student replies "@p-bot submitted $152.49"
   -> Bot fills Date Processed (Col U) and updates Total Price (Col H)

4. Confirmation: User replies "@p-bot confirmed" (with optional attachment)
   -> Bot fills Date Confirmed (Col V) and saves confirmation file to Order-Confirmations/

5. Delivery: User replies "@p-bot delivered"
   -> Bot fills Date of Delivery (Col W) and Received By (Col X)

6. Quotes: User replies "@p-bot quote" with attached quote file
   -> Bot saves file to Quotes/
```

---

## Bot Slack Commands

| Command | Action |
|---|---|
| `@p-bot approved` | Parse, validate, and log EPIF PDF to workbook and save PDF to `EPIFs/` |
| `@p-bot claim` | Grad student claims an approved undergrad purchase |
| `@p-bot submitted [$price]` | Mark order as submitted in Workday (`Date Processed`, Col U) and update cart total |
| `@p-bot confirmed` | Mark order as confirmed (`Date Confirmed`, Col V) and save confirmation to `Order-Confirmations/` |
| `@p-bot delivered` | Mark order as delivered (`Date of Delivery`, Col W, `Received By`, Col X) |
| `@p-bot quote` | Save attached quote PDF/document to `Quotes/` |
| `@p-bot help` | Display command guide |

---

## Directory Layout on OneDrive

All files sync directly to the lab's OneDrive Purchasing directory:
- `Purchasing-Log.xlsx` — Main order log
- `EPIFs/` — Approved EPIF PDF forms
- `Order-Confirmations/` — Workday/vendor confirmation receipts & emails
- `Quotes/` — Vendor quote documents

---

## Running the Bot

```powershell
python app.py
```
