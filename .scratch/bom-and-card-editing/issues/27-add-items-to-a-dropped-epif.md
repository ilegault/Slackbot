# 27: Add items to a dropped EPIF

**Status:** ready-for-agent

**Blocked by:** 26

**Spec:** `.scratch/bom-and-card-editing/spec.md` decision 3 (the EPIF path)
**Binding:** `docs/adr/0006-bom-line-items-and-editable-posted-cards.md` decisions 1, 2, 3, 5, 6

## What to build

A lab member drops an EPIF for five different Ruland couplings into a thread. The
posted card now carries an **Add items** button. They click it, paste the five
parts into one box, and submit. The card updates to show `📋 5 line items (BOM
attached in thread)`, and the bot posts a draft spreadsheet into the thread, so
Charlie can see what the total is made of before he approves.

If the items don't add up to the EPIF's amount, the submit is refused inside the
modal with both numbers shown, and the card is untouched. Once items exist, the
button reads **Edit items** and reopens the box pre-filled, so a mistyped price is
a two-click fix.

## Notes

- **Line items live in the card message's Slack metadata, never in a button
  `value`** (ADR 0006 decision 5). Slack caps a button value at ~2 000 characters
  and the parsed request already fills much of it; five items with links would
  overflow it and break the card. This is a requirement.
- The posted card's payload gains a key recording **which path it was born on**,
  because ticket 32's Edit behaves differently for each.
- Reading the card's metadata must fetch **that exact message**, not the newest
  card in the thread — multi-EPIF threads are real.
- Saving items is **one handler**, which ticket 28 and ticket 32 both call. Do not
  write a second copy for the other path (invariant 1).
- The draft spreadsheet is uploaded to the thread and **not** saved to `BOMS_DIR`.
  Only approval archives.
- A denial or refusal must never replace or delete the card (invariant 5, the rule
  ticket 12 established).

## Acceptance criteria

- [ ] A posted card from a dropped EPIF renders an **Add items** button, and an approved or later card does not
- [ ] Submitting a valid paste stores the items and shipping in that card message's metadata
- [ ] The button `value` on the updated card contains no line items — asserted on the value's contents
- [ ] The updated card summary names the number of line items when there are two or more, and says nothing extra for one item
- [ ] Two or more items cause a draft spreadsheet to be uploaded into the thread; one item uploads nothing
- [ ] The draft file is not written to `BOMS_DIR`
- [ ] A paste whose totals disagree with the EPIF amount is refused inside the modal, naming both numbers, with no metadata change, no upload and no card update — asserted on the absence
- [ ] A paste with a bad line is refused inside the modal with the line-numbered error, and the card is untouched
- [ ] Re-opening the button once items exist pre-fills the box with the current items and reads **Edit items**
- [ ] Re-submitting different items replaces the stored items and re-posts the draft spreadsheet
- [ ] Reading a card's items in a thread holding two cards returns the items of the card that was clicked, not the newest card
- [ ] `ruff check .`, `python scripts/check_tests_first.py` and `pytest -q` all pass
