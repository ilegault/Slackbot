# 30: The buyer's DM carries the BOM

**Status:** ready-for-agent

**Blocked by:** 29

**Spec:** `.scratch/bom-and-card-editing/spec.md` decision 4 (assignee DM)
**Binding:** `docs/adr/0004-assignment-replaces-claim.md`, `docs/adr/0005-assignment-can-be-a-button.md`, `docs/adr/0006-...` decision 6

## What to build

The buyer named on an itemised purchase gets the spreadsheet where they need it:
attached to the email-draft DM they already receive, with the draft naming the
file so Tina knows to open it. Instead of pasting five links into an email, the
buyer forwards one EPIF and one sheet.

This holds both ways a buyer is named: in the approval itself, and later with
`@Purchasing assign` or the picker on the card.

## Notes

- The email draft is generated in one place today and DM'd from two. Both must
  attach the file; neither may grow its own copy of the draft text (invariant 1).
- A failed upload is logged and raised to the admin alert channel. **It must never
  fail or reverse the approval** — the money decision already happened (ADR 0004
  decision 2, same spirit).
- A request with no BOM sends exactly the DM it sends today.

## Acceptance criteria

- [ ] Approving an itemised request with a buyer named attaches the archived spreadsheet to that buyer's DM
- [ ] The email draft text names the attached file
- [ ] Assigning a buyer after an unassigned approval attaches the same file to their DM
- [ ] Re-assigning to a different buyer attaches it to the new buyer's DM
- [ ] A request with no line items DMs exactly what it does today, with no attachment and no mention of a sheet
- [ ] An upload that fails leaves the approval, the row and the card intact, logs the failure and alerts admin — asserted on the workbook and the card
- [ ] `ruff check .`, `python scripts/check_tests_first.py` and `pytest -q` all pass
