# 32: Edit a posted card

**Status:** done

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

- [x] A posted card born from the interview renders an **Edit** button; an approved or later card does not
- [x] The requester, a buyer and an admin each open the form; anyone else gets an ephemeral denial with no form opened and no card update — asserted on the absence
- [x] The form opens pre-filled with the request's current values, including its line items
- [x] Submitting a changed field updates the card in place and its stored payload
- [x] Exactly one thread line is posted, naming each changed field as `old → new`, and the same line is appended to the card's history
- [x] An edit that changes the line items re-posts the draft spreadsheet
- [x] An edit that changes nothing posts no thread line and adds no history line
- [x] An edit that fails validation is refused on the offending field, with the card unchanged
- [x] Changing the category to one that needs asset details requires those fields before the edit is accepted
- [x] An edit submitted after the card was approved is refused with a message saying so, and nothing is changed — asserted on the payload and the card
- [x] Vendor and route are absent from the edit form
- [x] `ruff check .`, `python scripts/check_tests_first.py` and `pytest -q` all pass

## Comments

2026-09-22 — Implemented by agent.

### What was built
- `config.py`: added `EDIT_CALLBACK_ID = "purchase_edit_submit"` and `ACTION_REQ_EDIT = "req_edit"`.
- `blocks.py`: `build_request_blocks` now renders an Edit button on `source == "modal"` posted cards. `build_stage2_view` extended with `is_edit` flag in meta: pre-fills all fields, uses `EDIT_CALLBACK_ID`, "Edit Request" title, "Save changes" submit, includes asset ID and Name of System fields (optional in form, required at submit when category demands them). Vendor and route shown as read-only context only.
- `lifecycle.py`: `handle_request_edit` — rebuilds parsed from stage2/stage3, calls `describe_changes`, returns immediately if nothing changed, otherwise `chat_update` + `chat_postMessage` edit line + re-posts draft BOM when items changed.
- `app.py`: `handle_req_edit_action` listener (permission check, builds meta, opens pre-filled edit form) and `handle_edit_submit` listener (validates, approved-meanwhile guard before ack, calls `handle_request_edit`). Added `validators` to module imports.

### Tests
17 tests in `tests/test_32_edit_a_posted_card.py`. Gate result: 397 passed, 31 skipped, 0 failed.
