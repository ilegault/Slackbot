# 30: The buyer's DM carries the BOM

**Status:** done

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

- [x] Approving an itemised request with a buyer named attaches the archived spreadsheet to that buyer's DM
- [x] The email draft text names the attached file
- [x] Assigning a buyer after an unassigned approval attaches the same file to their DM
- [x] Re-assigning to a different buyer attaches it to the new buyer's DM
- [x] A request with no line items DMs exactly what it does today, with no attachment and no mention of a sheet
- [x] An upload that fails leaves the approval, the row and the card intact, logs the failure and alerts admin — asserted on the workbook and the card
- [x] `ruff check .`, `python scripts/check_tests_first.py` and `pytest -q` all pass

## Comments

2026-09-22: Implemented. Changes:
- `src/text_rules.py`: `generate_email_draft` gains optional `bom_filename` param; adds
  "Itemised BOM attached: <filename>" line to the email body.
- `src/lifecycle.py`: `_send_assignee_dm` private helper is the single implementation of
  the assignee DM (invariant 1). Both `finalize_purchase_request` (at approval) and
  `handle_assign` (post-approval assignment) call it. It sends the DM text, then uploads
  the BOM to the DM via `conversations_open` + `files_upload_v2`. A failed upload is
  logged and alerted to `ADMIN_ALERT_CHANNEL` but never reverses the approval.
- `tests/test_30_buyers_dm_carries_bom.py`: 8 tests covering all 6 acceptance criteria.
  Gate: 351 passed, 31 skipped, 0 failures.
