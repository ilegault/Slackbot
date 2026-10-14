# ADR 0019 — BOMs come in through the lab template and are read

**Status:** accepted
**Date:** 2026-10-14
**Supersedes:** ADR 0012 decisions 2 and 4, and decision 1 for the BOM field (the Quotes
field is unchanged); ADR 0006 decisions on the paste box and the `NNNN_<Vendor>_BOM.xlsx`
name; ADR 0008 decisions 1, 4 and 7. ADR 0015's thread-file sorting is amended by
decision 7 below.

## Context

On 2026-10-13 a requester attached a hand-made BOM to an EPIF-path request (a valve
assembly from Swagelok). Nothing crashed, but the bot did nothing useful with it. Under
ADR 0012 an attached BOM is carried and never read, so the filled EPIF did not say "See
attached BOM", nobody checked the total against the EPIF amount, and the file that went to
the buyer was in whatever layout the requester used. The only way to get a BOM the bot
understood was to retype every row into the paste box in a fixed `|`-separated order,
which nobody does for a real order.

ADR 0012 already named the next step: "a BOM template whose exact headers the bot can
read, not header guessing." A lab buyer has since built that template
(`templates/HIRST_LAB_BOM_TEMPLATE.xlsx`), and the developer adopted it as the standard.

## Decision

1. **One template is the standard.** `templates/HIRST_LAB_BOM_TEMPLATE.xlsx` (sheet
   `BOM`): a header block (title, *Order Description*, *BOM Creator*, *Total Cost*), then
   the columns `Item | Description | Product # | Vendor | Unit Cost | Quantity | Total Cost
   | Notes`, then a Total row with "Total" in the Quantity column. `.xlsx` only — no CSV.
   There is no Link column; links are not asked for.
2. **The bot reads it.** It finds the column-header row (case and surrounding spaces
   ignored) anywhere in the first 10 rows of the first sheet, ignores the header block,
   and reads down to the row with "Total" in the Quantity column. A row with both Unit
   Cost and Quantity blank is skipped. Formula cells (Total Cost) are never read: the bot
   computes quantity × unit cost, because a file saved without Excel holds no formula
   results. A hyperlink on an Item cell is kept as that line's link; none is required.
3. **Row rules.** Every read row needs an Item, a whole-number Quantity of 1 or more, and
   a numeric Unit Cost. Description, Product #, Vendor and Notes are optional. Problems are
   reported by spreadsheet row number. The Vendor column is not compared with anything;
   the one-vendor checkbox (ADR 0012 decision 3, still required when a BOM is given) is the
   vendor check.
4. **The paste box is gone.** Interview Screen 2, Add items and Edit take a BOM file
   instead. One item is the ordinary Screen 2 fields; two or more is the template.
5. **A check screen before anything is posted.** After a form with a BOM is submitted, the
   modal moves to a check screen: the rows as read, the BOM total, and every problem. It
   refuses to continue while there is any problem, or while the BOM total differs from the
   typed Total Price by even a cent (shipping and tax are not tracked). The fix is to edit
   the spreadsheet and upload it again on that screen. A "Send me the BOM template" button
   beside every BOM field DMs the template, the same file `/blank-template` hands out.
6. **The bot rebuilds the BOM from what it read.** The uploaded file is not kept. The
   rebuilt file follows the template exactly: Order Description is the request's "What is
   being purchased", BOM Creator is the requester's roster name, Total Cost points at the
   Total row, each row's Notes and Item hyperlink carried over. It is named
   `HIRST_LAB_BOM_<Description>_<MM.DD.YYYY>.xlsx` — Description from "What is being
   purchased" with spaces removed inside words, words joined by `-`, characters a file
   name cannot hold dropped, at most 60 characters; the date is the approval date; a clash
   adds `_2`, `_3`. The draft posted before approval is the same name with `DRAFT_` in
   front. The log row is linked through the Notes column, not the file name.
7. **The thread path never blocks approval over a BOM.** At `@Purchasing approved`, an
   `.xlsx` in the thread is checked against the template. If it reads cleanly and adds up to
   the EPIF amount, it is treated as in decision 6. Otherwise approval still goes ahead, the
   file is archived as given under the decision-6 name, and the bot posts in the thread
   naming the problem and asking the requester to use **Replace BOM**. Until it is replaced
   the buyer's DM card says the BOM is not in the lab template.
8. **Replace BOM.** A button available to the requester and buyers from approval until the
   request is **processed**. It opens the same upload and check screen; a passing upload
   replaces the archived BOM and is sent again to the assigned buyer's DM. It never blocks
   Mark Processed.

## Consequences

- Every BOM the buyer receives after this lands is in one layout, and its total equals the
  EPIF amount on the form path.
- The paste-box tests and `blocks.line_items_input` are replaced, not muted; this ADR
  authorises that.
- "Made" vs "attached" BOM stops being a distinction: every BOM is made from line items,
  and the template is how line items arrive.
- A requester whose BOM is not in the template on the thread path is told, not stopped.
