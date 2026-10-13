# 121: The Filled EPIF ends with the link, and reading an EPIF gives it back

**Status:** done

**Runner:** any

**Auto-merge:** yes

**Blocked by:** 120

**Spec:** `.scratch/purpose-and-link/spec.md` (Part B, stories 6–10)
**Binding:** `docs/adr/0007-purchase-path-and-generated-epif.md` (the bot fills the EPIF); `docs/adr/0001-tests-first-and-no-muted-failures.md`
**Glossary:** `CONTEXT.md` — **Filled EPIF**, **EPIF**

## What to build

When the bot fills an EPIF, the Purpose box ends with a blank line and then
`Link: <url>`, so purchasing has the product page or quote link on the form. It is plain
text, because a PDF form text field cannot hold a clickable link. Nothing is appended
when the request has no link, or when the exact link is already in Purpose. The stored
request's Purpose is never changed; only the PDF gets the extra line.

Reading any EPIF (a signed Filled EPIF dropped back into the thread, or a hand-filled
one): when the last line of Purpose is only a URL, with or without a `Link:` label in any
case, that line is removed from Purpose and becomes the link. In every other case
Purpose is left exactly as written and the link is the first URL in it, as today. Purpose
is never left blank: if the URL is the whole of Purpose, nothing is split.

Today `epif_filler.fill_epif` writes only `parsed["purpose"]`, and the Link field never
reaches the EPIF.

1. **`src/text_rules.py`** — add two pure functions beside `link_in_purpose` (ticket 120).
   Each docstring names `.scratch/purpose-and-link/spec.md`. Both must be pure functions in
   `text_rules`, so that filling and reading share one rule and can be tested with plain
   strings.
   - `purpose_with_link(purpose: str | None, link: str | None) -> str`:
     - returns `(purpose or "").rstrip()` when `link` is empty after `.strip()`, or when
       `link_in_purpose(purpose, link)` is true;
     - otherwise returns `f"{(purpose or '').rstrip()}\n\nLink: {link.strip()}"`.
   - `split_trailing_link(purpose: str | None) -> tuple[str, str | None]`:
     1. Let `text = (purpose or "").strip()`.
     2. Take the last non-blank line of `text` and `.strip()` it.
     3. Match that line against `re.compile(r"^(?:link:\s*)?(https?://\S+)$", re.IGNORECASE)`.
     4. On a match, let the remainder be the lines before that line, joined with `"\n"`
        and `.rstrip()`. If the remainder is non-empty, return `(remainder, url)`.
     5. In every other case return `(text, None)`.
2. **`src/epif_filler.py` `fill_epif`** — inside the existing
   `for parsed_key, pdf_key in mapping.items()` loop, next to the `item_description` BOM
   special case: when `parsed_key == "purpose"`, set
   `val = text_rules.purpose_with_link(parsed.get("purpose"), parsed.get("link"))`.
   - Import `text_rules` with the same two-way pattern the module uses for `config`.
   - Add one sentence to the module docstring: Purpose on the Filled EPIF ends with the
     request's link, per `.scratch/purpose-and-link/spec.md`.
   - Do not change `parsed`.
3. **`src/epif_parser.py` `parse_epif`**:
   - compute
     `purpose, trailing_link = text_rules.split_trailing_link(fields.get("Purpose", ""))`;
   - the returned dict's `"purpose"` is `purpose`, and its `"link"` is
     `trailing_link or first_url(purpose)`;
   - `raw_fields` stays the PDF's text, unchanged;
   - import `text_rules` with the module's existing two-way pattern.

## Acceptance criteria

- [x] New `tests/test_121_link_on_the_filled_epif.py`, test `test_purpose_with_link`, asserts:
  - `purpose_with_link("why", "https://a.com/x") == "why\n\nLink: https://a.com/x"`;
  - `purpose_with_link("why https://a.com/x", "https://a.com/x") == "why https://a.com/x"`;
  - `purpose_with_link("why", "")` and `purpose_with_link("why", None)` both `== "why"`.
- [x] Test `test_split_trailing_link` asserts:
  - `"why\n\nLink: https://a.com/x"` gives `("why", "https://a.com/x")`;
  - `"why\nhttps://a.com/x"` gives `("why", "https://a.com/x")`;
  - `"why\nLINK:  https://a.com/x"` gives `("why", "https://a.com/x")`;
  - `"we need this per https://a.com/x for the beamline"` gives that same string and `None`;
  - `"https://a.com/x"` gives `("https://a.com/x", None)`.
- [x] **Rewrite in place, same name:** in `tests/test_37_fill_epif.py`, test `test_fill_epif_round_trip`.
  - Add `"link": "https://www.airgas.com/product/ABC123"` to `base_parsed`.
  - Keep every existing assertion.
  - Add, inside the loop: `parsed_out["link"] == parsed_in["link"]`, and
    `parsed_out["raw_fields"]["Purpose"].endswith("\n\nLink: https://www.airgas.com/product/ABC123")`.
  - No test function is deleted.
- [x] In `tests/test_121_link_on_the_filled_epif.py`, one test function, `test_fill_appends_the_link_only_when_needed`, covers three cases. Each case fills the real template with `fill_epif` (load the fixture as `tests/test_37_fill_epif.py` does) and reads it back with `parse_epif`. Keep the three cases in **one** function: the gate holds a PR that adds a new test which already passes on today's code, and only the first case fails today.
  - Purpose `"For the beamline"` with link `https://fisher.com/a`: `raw_fields["Purpose"] == "For the beamline\n\nLink: https://fisher.com/a"`.
  - Purpose `"For the beamline https://fisher.com/a"` with the same link: `raw_fields["Purpose"]` contains `https://fisher.com/a` exactly once and does not contain `Link:`.
  - Link `None`: `raw_fields["Purpose"] == "For the beamline"`.
- [x] Test `test_reading_an_epif_takes_a_url_on_the_last_line`: fill the real template with purpose `"For the beamline\nhttps://fisher.com/a"` and link `None`, then `parse_epif` it. Assert `purpose == "For the beamline"` and `link == "https://fisher.com/a"`. In the same function (the first half fails on today's code, the second does not), do the same with purpose `"Per https://fisher.com/a for the beamline"` and assert that `purpose` is unchanged and `link == "https://fisher.com/a"`. Every existing test that calls `fill_epif` (`tests/test_100_thread_file_classifier.py`, `tests/test_101_keyword_approves_posted_card.py`, `tests/test_103_thread_files_at_approval.py`, `tests/test_45_epif_approval_archives.py`, `tests/test_117_switch_to_epif_submit.py`) passes unchanged.

May fake: nothing in these tests needs Slack. Must be real: `text_rules`, `epif_filler.fill_epif` on `tests/fixtures/EPIF_TEMPLATE_HIRST.pdf`, and `epif_parser.parse_epif` on its output. A test that patches `fill_epif`, `parse_epif`, `read_fields` or the `text_rules` helpers does not count.

## Gate

Run all four, in CI's order, and all must pass:

    ruff check .
    python scripts/check_tests_first.py
    python tools/type_gate.py
    pytest --tb=short -q -n auto --dist loadfile

Tests need `SLACK_BOT_TOKEN=xoxb-test-not-a-real-token`, `SLACK_APP_TOKEN=xapp-test-not-a-real-token` and `PYTHONUTF8=1` in the environment, as `.github/workflows/tests.yml` sets.

## Comments
2026-10-13: Added `text_rules.purpose_with_link` and `split_trailing_link`; `fill_epif` writes the link at the end of Purpose; `parse_epif` splits a URL-only last line into `link`. Tests: `tests/test_121_link_on_the_filled_epif.py` (all four new tests) and the in-place rewrite of `test_fill_epif_round_trip`; all fail on the old code. Gate green locally: ruff, tests-first, type_gate (95/95), pytest 851 passed. Deploy is a human step.
