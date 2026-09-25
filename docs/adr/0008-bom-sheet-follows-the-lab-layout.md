# ADR 0008 — The BOM sheet follows the lab's hand-made layout

**Status:** accepted
**Date:** 2026-09-25
**Supersedes:** ADR 0006 decision 10 (sheet layout). Every other ADR 0006 decision stands.

## Context

ADR 0006 shipped the BOM with a "standard column set for now" and said matching the
lab's hand-made BOM was a later, separate change. The developer has now supplied a
hand-made BOM that a lab member built for a six-item consumables order. It is the
format purchasing already receives. This ADR records which parts of it the bot copies
and which it leaves out.

The hand-made sheet: a dark title bar, a short header block, then columns
`Item | Description | Product # | Vendor | Lot Size | Unit Cost | Quantity | Total Cost | Notes`,
a Total row, and live formulas (`=F6*G6` per line, `=SUM(...)` for the total). Each
Item cell is a hyperlink to the product page; there is no separate Link column.

## Decision

1. **Columns are** `Item | Description | Product # | Vendor | Unit Cost | Quantity | Total Cost | Notes`.
   The item name is hyperlinked to the item's link when the link is `http://` or
   `https://`. There is no Link column and no `#` column.
2. **Lot Size is dropped.** The developer does not need it; the paste box does not
   collect it.
3. **Notes is an empty column.** The paste box does not collect per-item notes. The
   column exists so a person can type in it after opening the file.
4. **The header block is a title and a Total Cost line, nothing else.** No order
   description, no BOM creator, no vendor / requester / project / fund / date / log
   row. All of that is on the EPIF, and the BOM exists only to break the EPIF's one
   amount into lines. The draft and the archived file are told apart by their file
   names (`DRAFT_…` vs `NNNN_…`, unchanged from ADR 0006 decision 6).
5. **Totals are live Excel formulas**, like the hand-made sheet: `=E{r}*F{r}` per
   line, `=SUM(G…)` for the Total row, and the header's Total Cost points at the same
   sum. Accepted cost: a file written by openpyxl stores no cached formula results, so
   Slack's file preview and some phone viewers show those cells blank until the file is
   opened in Excel. Purchasing opens it in Excel.
6. **No shipping row.** The sheet lists the item prices as entered. Shipping and tax
   are on the EPIF. The paste box still accepts the optional `shipping | <amount>`
   line and the totals check (ADR 0006 decision 4) is unchanged, so the sheet's Total
   can be lower than the EPIF amount by exactly the shipping entered. That is
   intended.
7. **The paste format is unchanged**:
   `qty | item name | part number | unit price | link | description`, plus the optional
   shipping line.

## Consequences

- `bom.build_bom_workbook` changes layout and signature; the two tests in
  `tests/test_26_line_items_and_bom.py` that assert the ADR 0006 decision-10 layout
  are replaced, not muted. Replacing them is authorised by this ADR.
- Every box that accepts line items must show the same, correct format. The Workday
  details modal's box currently shows a different, wrong example (see ticket 50).
