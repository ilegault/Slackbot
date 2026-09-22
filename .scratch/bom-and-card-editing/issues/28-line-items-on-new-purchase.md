# 28: Line items on /new-purchase

**Status:** ready-for-agent

**Blocked by:** 27

**Spec:** `.scratch/bom-and-card-editing/spec.md` decision 3 (the modal path)
**Binding:** `docs/adr/0006-bom-line-items-and-editable-posted-cards.md` decisions 1, 2, 3, 4

## What to build

A lab member who has no EPIF yet runs `/new-purchase` and itemises their order
while filling in the interview. Screen 2 gains an optional **Line items** box
taking the same paste as ticket 27, with a hint showing the format and the
shipping line. Leave it empty and the interview behaves exactly as it does today.

Fill it in and the request posts to the purchasing channel already itemised: the
card names the line items, and a draft spreadsheet follows it into the thread.

## Notes

- The items text travels through the interview's carried state to Screen 3, which
  Slack caps at 3 000 characters. **The items box is capped at 1 500 characters so
  the carried state cannot overflow** — a requirement, not a preference: an
  overflow silently breaks the Fabrication-category path (Screen 3), which is the
  one hardest to notice in testing.
- Items are checked against the Total Price field on the same screen, so the
  request and its sheet can never disagree.
- Errors go back on the items box itself, not as a thread message.
- Storing the items and posting the draft spreadsheet must go through the handler
  ticket 27 built. No second implementation (invariant 1).

## Acceptance criteria

- [ ] Screen 2 renders an optional multiline **Line items** input with a hint naming the format and the shipping line
- [ ] An empty items box completes the interview exactly as before — no metadata key, no upload
- [ ] A valid paste stores items and shipping in the posted card's metadata and names the line items on the card
- [ ] Two or more items post a draft spreadsheet into the thread right after the card
- [ ] A paste whose totals disagree with the Total Price field is refused on the items box, and no card is posted
- [ ] A line-numbered parse error is shown on the items box, and no card is posted
- [ ] The items box carries its own maximum length, and a request with a full box plus a Fabrication category still completes Screen 3 and posts
- [ ] A one-item paste posts the card with no spreadsheet
- [ ] `ruff check .`, `python scripts/check_tests_first.py` and `pytest -q` all pass
