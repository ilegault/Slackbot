# 37: Fill the EPIF from a request (pure, round-trip tested)

**Status:** ready-for-agent

**Runner:** any

**Auto-merge:** yes

**Blocked by:** 36

Spec: `.scratch/purchase-path-and-epif/spec.md`, Implementation Decision 2, first bullet. Binding: ADR 0007 decision 6 (PI and end user), ADR 0001.

**What to build:** A new pure module `src/epif_filler.py` with
`fill_epif(template_bytes: bytes, parsed: dict) -> bytes`. Given the committed template
and a parsed request, it returns a filled PDF that `epif_parser.parse_epif` reads back to
the same values. Nothing calls it yet; tickets 45 and 41–42 do.

## Decided before you start (nothing here is open, do not escalate over it)

- **The fixture is not fully blank.** `tests/fixtures/EPIF_TEMPLATE_HIRST.pdf` has 28
  fields. Three arrive pre-filled from the university form: `Name`, `PI of Funding` and
  `Telephone # for ?'s`. Ticket 36's line "every field empty" is out of date; ignore it.
  The fixture is the file to keep exactly as committed. Do not edit, strip or replace it.
- **`parse_epif` reads 25 of the 28 fields.** The three it does not read are
  `Signature1`, `Telephone # for ?'s` and `List of Other`. `fill_epif` never writes any of
  the three.
  - `Signature1` is a `/Sig` digital-signature field. A person signs it outside the bot.
    It stays empty. This is decided. It is NOT a reason to set this ticket to `blocked`.
  - `Telephone # for ?'s` keeps the value the template already carries.
  - `List of Other` stays empty.
- **PI of Funding and Name are both written from one constant**, so a blank template
  still produces the right form. The value is the name ADR 0007 decision 6 gives. The
  "roles, never names" rule in `docs/agents/issue-tracker.md` governs ticket text only. It
  does not apply to `src/config.py`, which must hold the real name here.
- **The `parsed` dict** uses the key names `epif_parser.parse_epif` returns:
  `item_description`, `purpose`, `total_price` (float), `vendor`, `vendor_contact_name`,
  `vendor_contact_email`, `date_of_purchase` (a `datetime.date`), `name_of_system`,
  `delivery_room`, `project_id`, `fund`, `asset_id`, `category` (the exact dropdown string
  that is a value of `config.CHECKBOX_TO_CATEGORY`) and `payment_method` (`"P-card"` or
  `"Req/PO"`). It may also carry `items` (a list of line-item dicts) and `shipping`
  (float), the same shapes `src/bom.py` uses. Write `total_price` as `f"${total_price:.2f}"`
  and `date_of_purchase` as `%m/%d/%Y`; `parse_money` and `parse_date` read both back.
- **pypdf mechanics you will need:**
  - Read the template with `pypdf.PdfReader(io.BytesIO(template_bytes))`. This template
    carries XMP metadata, and `PdfWriter(clone_from=reader)` raises `NotImplementedError:
    XmpInformation does not implement .clone`. Fix it by deleting the metadata from the
    reader first: `root = reader.trailer["/Root"]`, then `if "/Metadata" in root: del root["/Metadata"]`.
  - Fill text fields with `writer.update_page_form_field_values(page, values,
    auto_regenerate=False)` for every page, then set `/NeedAppearances` to true on the
    AcroForm so viewers redraw.
  - A checkbox is ticked with `/On` and every other box in its group set to `/Off`.
  - Write to an `io.BytesIO` and return `buffer.getvalue()`. Never return the buffer.
  - Never pass `Signature1` to `update_page_form_field_values`.

## Acceptance criteria

- [ ] **Fields written.** `fill_epif` writes every field `epif_parser.parse_epif` reads:
  the text fields in `config.FIELD_TO_COLUMN`, and `PI of Funding` and `Name`. Take field
  names from `config.FIELD_TO_COLUMN`, `config.CHECKBOX_TO_CATEGORY` and
  `config.PAYMENT_CHECKBOXES`, never retype them. For `PI of Funding` and `Name`, add
  `EPIF_PI_FIELD = "PI of Funding"` and `EPIF_END_USER_FIELD = "Name"` to `config` beside the
  new constant and use those. Exactly one category checkbox is `/On` and the other eight
  are `/Off`; exactly one payment checkbox is `/On` and the other is `/Off`. It does no
  file or Slack I/O: bytes in, bytes out.
- [ ] **PI and end user.** `config.EPIF_PI_AND_END_USER` is a new `str` constant holding the
  name ADR 0007 decision 6 gives. `fill_epif` writes it to both `PI of Funding` and `Name`.
  Any field with no source value is left blank.
- [ ] **BOM.** With two or more `items`, `What is being purchased` is
  `See attached BOM — N items` (N is the count) and the amount is `total_price`, which
  `bom.check_total` already guarantees is the BOM total including shipping.
- [ ] **Docstring.** The `src/epif_filler.py` module docstring names the three fields
  `parse_epif` does not read (`Signature1`, `Telephone # for ?'s`, `List of Other`), says
  what each is, and says `fill_epif` never writes them.
- [ ] **Round trip** in `tests/test_37_fill_epif.py`, on `tests/fixtures/EPIF_TEMPLATE_HIRST.pdf`
  read from disk as bytes. For one request per category and for both payment methods,
  `parse_epif(fill_epif(template, parsed))` equals the input for item, purpose, amount,
  vendor, contact name and email, date, room, project, fund, asset ID, name of system,
  category and payment method, and returns `config.EPIF_PI_AND_END_USER` for
  `pi_of_funding` and `end_user`. The same test asserts, on the filled bytes, that
  `Signature1` is still empty and `Telephone # for ?'s` equals the value the fixture has.
  A BOM case with three items reads back `See attached BOM — 3 items` and the BOM total.
  Nothing is faked: the test fills the real fixture and reads the real filled bytes.
- [ ] **Full gate green**, in CI order: `ruff check .`, `python scripts/check_tests_first.py`,
  `pytest -q`. Before pushing, also confirm `pypdf` is in `requirements.txt` (it is, do not
  add it elsewhere).

## Out of scope

Editing the fixture, `epif_parser.py`, `Signature1` handling, the template path, archiving,
naming (tickets 44/45), and anything that calls `fill_epif`.

## Comments

2026-09-25 (planner): The first run was blocked because the ticket said "PI and Name from a
constant" while a later edit said "never write them", and because it treated the `Signature1`
`/Sig` field as an unresolved approval field. Rewritten. The fixture is the real
university form with three pre-filled fields; PI and Name are written from a constant per ADR 0007
decision 6; `Signature1` stays empty by decision. The earlier attempt's "ADR 0002 forbids
real names" was a misreading: that rule is about ticket text, and ADR 0002 is the lifecycle ADR.
