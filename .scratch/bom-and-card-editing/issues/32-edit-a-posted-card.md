# 32: Edit a posted card

**Status:** ready-for-agent

**Blocked by:** 28

**Spec:** `.scratch/bom-and-card-editing/spec.md` decision 6
**Binding:** `docs/adr/0006-bom-line-items-and-editable-posted-cards.md` decision 8, `CONTEXT.md` (**Edit**)

## What to build

A requester spots a typo on the card they just submitted through `/new-purchase`.
Today their only options are Decline and start over. This ticket gives that card
an **Edit** button: it reopens the request's details pre-filled, they fix the one
wrong field, and the card updates in place.

Charlie may already have read that card, so every edit posts one line in the
thread saying what changed —
`✏️ Edited by Dylan: Total $412.00 → $455.50; items 4 → 5` — and the same line
joins the card's history. Change nothing and nothing is posted.

The requester, any buyer and any admin may edit. Anyone else gets an ephemeral
denial and the card is untouched. If the card was approved while the form was
open, the submit is refused and nothing changes.

## Notes

- Edit exists on **posted** cards born from the interview. Cards born from a
  dropped EPIF use the Add / Edit items button from ticket 27, because the PDF is
  the source for every other field (ADR 0006 decision 8).
- **Vendor and route are not editable.** To change vendor, Decline and resubmit.
- The edit form validates with the same rules as the interview, including
  requiring the asset fields when the category needs them. Editing must not be a
  way around validation.
- The refusal when the card has been approved meanwhile is checked by **re-reading
  the card at submit time**, not from anything the form carried when it opened.
- A denial replaces nothing and deletes nothing (invariant 5).

## Acceptance criteria

- [ ] A posted card born from the interview renders an **Edit** button; an approved or later card does not
- [ ] The requester, a buyer and an admin each open the form; anyone else gets an ephemeral denial with no form opened and no card update — asserted on the absence
- [ ] The form opens pre-filled with the request's current values, including its line items
- [ ] Submitting a changed field updates the card in place and its stored payload
- [ ] Exactly one thread line is posted, naming each changed field as `old → new`, and the same line is appended to the card's history
- [ ] An edit that changes the line items re-posts the draft spreadsheet
- [ ] An edit that changes nothing posts no thread line and adds no history line
- [ ] An edit that fails validation is refused on the offending field, with the card unchanged
- [ ] Changing the category to one that needs asset details requires those fields before the edit is accepted
- [ ] An edit submitted after the card was approved is refused with a message saying so, and nothing is changed — asserted on the payload and the card
- [ ] Vendor and route are absent from the edit form
- [ ] `ruff check .`, `python scripts/check_tests_first.py` and `pytest -q` all pass
