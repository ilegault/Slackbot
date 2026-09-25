# 37: Fill the blank EPIF from a request (pure, round-trip tested)

**Status:** blocked

**Runner:** any

**Auto-merge:** yes

**Blocked by:** 36

Spec: Implementation Decision 2, first bullet. Binding: ADR 0007 (PI and end user), ADR 0001.

**What to build:** A new pure module `src/epif_filler.py` with
`fill_epif(template_bytes: bytes, parsed: dict) -> bytes`. Given the committed blank
template and a parsed request, it returns a filled PDF that `epif_parser.parse_epif`
reads back to the same values. Nothing calls it yet; tickets 45 and 41–42 do.

- [ ] `fill_epif` writes every field `epif_parser.parse_epif` reads, using the field names from the same `config` maps `epif_parser` uses (open `src/epif_parser.py` and reuse its constants, never retype a field name). It sets exactly one category checkbox and exactly one payment checkbox, and uses `pypdf`. It does no file or Slack I/O (pure, so the round trip below is the proof).
- [ ] PI of Funding and Name come from a new constant `config.EPIF_PI_AND_END_USER`, holding the name ADR 0007 decision 6 gives. Template fields with no source value are left blank.
- [ ] With two or more `items`, *What is being purchased* is `See attached BOM — N items` and the amount is the BOM total including shipping (`bom.check_total` already guarantees it equals `total_price`).
- [ ] The module docstring lists the template fields `parse_epif` does not read, by name. If one looks like a signature or approval field, set this ticket to `blocked` with an escalation brief instead of guessing.
- [ ] **Round trip** in `tests/test_37_fill_epif.py`, on `tests/fixtures/EPIF_TEMPLATE_HIRST.pdf`: for one request per category and for both payment methods, `parse_epif(fill_epif(template, parsed))` equals the input for item, purpose, amount, vendor, contact, date, room, project, fund, asset ID, name of system, category and payment method, and reads `config.EPIF_PI_AND_END_USER` for PI and end user. A BOM case reads back `See attached BOM — 3 items` and the BOM total. Nothing may be faked here: it reads the real filled bytes.
- [ ] Full gate green, in CI order: `ruff check .`, `python scripts/check_tests_first.py`, `pytest -q`.

## Comments

## Escalation — 2026-09-22
Ticket: 37 Fill the blank EPIF from a request   Branch: ticket/37-fill-the-epif
Goal: A new pure module `src/epif_filler.py` with `fill_epif(template_bytes: bytes, parsed: dict) -> bytes`.
Attempt 1: Found unread fields `Telephone # for ?'s`, `Signature1`, and `List of Other` in `tests/fixtures/EPIF_TEMPLATE_HIRST.pdf`. → Ticket instructions explicitly say to escalate if one looks like a signature or approval field.
Failing output (exact, trimmed to the relevant lines):
```
```
Decision needed: Should `Signature1` be left blank, skipped, or filled with a specific value? The instructions forbid guessing when a field looks like a signature or approval field.
