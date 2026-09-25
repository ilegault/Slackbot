# 37: Fill the blank EPIF from a request (pure, round-trip tested)

**Status:** ready-for-agent

**Runner:** any

**Auto-merge:** yes

**Blocked by:** 36

Spec: Implementation Decision 2, first bullet. Binding: ADR 0007 (PI and end user), ADR 0001.

**What to build:** A new pure module `src/epif_filler.py` with
`fill_epif(template_bytes: bytes, parsed: dict) -> bytes`. Given the committed blank
template and a parsed request, it returns a filled PDF that `epif_parser.parse_epif`
reads back to the same values. Nothing calls it yet; tickets 45 and 41–42 do.

- [ ] fill_epif never writes Name, PI of Funding or Telephone # for ?'s; the template already contains them. No EPIF_PI_AND_END_USER constant is added. The round trip asserts those three fields read back exactly as they are in the template fixture.
- [ ] PI of Funding and Name come from a new constant `config.EPIF_PI_AND_END_USER`, holding the name ADR 0007 decision 6 gives. Template fields with no source value are left blank.
- [ ] With two or more `items`, *What is being purchased* is `See attached BOM — N items` and the amount is the BOM total including shipping (`bom.check_total` already guarantees it equals `total_price`).
- [ ] The module docstring lists the template fields parse_epif does not read, by name. Signature1 is a /Sig digital-signature field and is always left blank; that is decided, do not block on it. Leave every field in the template that is already pre-filled (Name, PI of Funding, Telephone # for ?'s) untouched
- [ ] **Round trip** in `tests/test_37_fill_epif.py`, on `tests/fixtures/EPIF_TEMPLATE_HIRST.pdf`: for one request per category and for both payment methods, `parse_epif(fill_epif(template, parsed))` equals the input for item, purpose, amount, vendor, contact, date, room, project, fund, asset ID, name of system, category and payment method, and reads `config.EPIF_PI_AND_END_USER` for PI and end user. A BOM case reads back `See attached BOM — 3 items` and the BOM total. Nothing may be faked here: it reads the real filled bytes.
- [ ] Full gate green, in CI order: `ruff check .`, `python scripts/check_tests_first.py`, `pytest -q`.

## Comments
