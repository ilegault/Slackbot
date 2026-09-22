# 33: A corrected EPIF supersedes the old card

**Status:** ready-for-agent

**Blocked by:** 27

**Spec:** `.scratch/bom-and-card-editing/spec.md` decision 7
**Binding:** `docs/adr/0006-bom-line-items-and-editable-posted-cards.md` decision 9, `CONTEXT.md` (**Superseded**)

## What to build

Someone notices a wrong fund number on the EPIF they just posted, fixes it, and
uploads the corrected PDF into the same thread. Today that leaves two cards, each
with its own Approve button, and whichever Charlie happens to click decides what
gets logged.

After this ticket the older card becomes terminal: it keeps its summary so the
history is readable, loses every button, and reads
`Superseded by a newer EPIF below`. There is exactly one card to approve.

## Notes

- Only **posted** cards from the **same requester** for the **same vendor**
  (compared case-insensitively and trimmed) in that thread are superseded.
- An approved, processed, confirmed, delivered or cancelled card is **never**
  superseded — a real purchase must not be hidden by a stray upload.
- A second vendor's EPIF in the same thread supersedes nothing. One EPIF per
  vendor is the lab's rule and multi-vendor threads are normal.
- Line items do not carry across; the new card starts empty.

## Acceptance criteria

- [ ] A second EPIF for the same vendor from the same requester rewrites the older posted card with no buttons and a line saying it was superseded
- [ ] The superseded card keeps its summary text
- [ ] The new card is posted as usual with its own buttons
- [ ] An EPIF for a different vendor in the same thread leaves the existing card untouched — asserted on the absence of a card update
- [ ] An EPIF from a different requester leaves the existing card untouched
- [ ] An approved card in the thread is never superseded, whatever is uploaded after it
- [ ] Vendor comparison ignores case and surrounding whitespace
- [ ] Line items on a superseded card do not appear on the new card
- [ ] `ruff check .`, `python scripts/check_tests_first.py` and `pytest -q` all pass
