# 36: Commit the blank EPIF template as a test fixture

**Status:** ready-for-developer

**Runner:** developer

**Auto-merge:** yes

**Blocked by:** None (can start immediately)

Spec: `.scratch/purchase-path-and-epif/spec.md`, Testing Decisions (seam 2).

**What to build:** The developer copies the blank `EPIF_TEMPLATE_HIRST.pdf` from the
lab's `Purchasing/_TEMPLATE` folder into `tests/fixtures/` and commits it. It is a blank
university form with no personal data. Ticket 37's round-trip test fills this exact
file. **An agent must not claim this ticket.**

- [x] `tests/fixtures/EPIF_TEMPLATE_HIRST.pdf` is on `master`.
- [x] It is the blank, unflattened form: `epif_parser.read_fields(open(path, "rb").read())` returns every field empty.

## Comments
