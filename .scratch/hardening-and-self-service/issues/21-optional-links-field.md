# 21: An optional links field on interview Screen 2

**What to build:** A field for the product page or quote link, so the person
buying it does not have to guess which item was meant. Optional, rendered under
the summary in the channel, written to the link column like the EPIF path
already is.

**Blocked by:** None (can start immediately)

**Status:** in-progress

**Read before starting:** `docs/adr/0001-tests-first-and-no-muted-failures.md`
(binding) and `tests/test_interview.py` for the existing seam.

## Why

The interview has nowhere to put the product page or quote link that nearly every
request has, so people paste it into the purpose field where it is neither
validated nor rendered.

**Almost nothing needs building.** `interview.build_parsed_from_stages` already
reads `stage2["link"]` and already falls back to `epif_parser.first_url(purpose)`.
The `link` key is already in the nineteen-key parsed dict. `log_writer.build_row`
already writes it to `config.COLUMN_LINK`. **The field is missing from the modal,
and that is all.**

## Requirements, stated as requirements

1. **Add `block_link` to Screen 2** in `blocks.build_stage2_view` — an optional
   `plain_text_input`, labelled for product pages and quote links, placed **after
   Purpose**, `optional: true`.

2. **`validators.validate` gains no rule for it.** A request without a link is
   valid. A request with a malformed one is valid too — this is not a URL
   validator.

3. **Render it under the summary in the channel post and on the card**, as its own
   bullet, **only when present**. No empty bullet, no "(none)".

4. **On the Excel question, follow the code, not the planning note.** The state doc
   recorded "not written to Excel", but `log_writer.build_row` has always written
   `parsed["link"]` to `COLUMN_LINK` when present, and the EPIF path already fills
   it. Making the modal path alone skip the column would make the two paths write
   **different rows for the same purchase**. The field writes to `COLUMN_LINK` like
   everything else.

   If that is wrong, it is a decision to reverse for **both** paths, in its own
   ticket — not something to special-case here.

## Acceptance criteria

- [ ] Screen 2 renders `block_link` as optional, positioned after Purpose
- [ ] A submission **omitting** the link validates and produces `parsed["link"]`
      from the purpose-URL fallback — asserted on the resulting value
- [ ] A submission **supplying** a link produces that link in `parsed`, in the
      channel summary, and in `COLUMN_LINK` of the written row — all three
- [ ] A submission with neither a link field nor a URL in the purpose validates,
      and the summary contains **no** link bullet — assert on the absence
- [ ] The EPIF path's `COLUMN_LINK` behaviour is unchanged and its existing tests
      pass untouched
- [ ] `ruff check .`, `python scripts/check_tests_first.py` and `pytest -q` all pass

## Out of scope

- Validating that the link is a real URL, or that it resolves. Requirement 2.
- Multiple links. One optional field.
- Any change to `Purchasing-Log.xlsx` structure. `COLUMN_LINK` already exists.
- Re-litigating requirement 4 for the EPIF path.
