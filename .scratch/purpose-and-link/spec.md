# Spec — Purpose asks why, the link is entered once and lands on the EPIF

**Status:** ready-for-agent
**Binding:** `docs/adr/0007-purchase-path-and-generated-epif.md` (the bot fills the EPIF),
`docs/adr/0018-the-path-is-the-payment-method-and-the-dm-card-shows-the-request.md`
(one builder for a request's lines: `blocks.request_summary_lines`),
`docs/adr/0001-tests-first-and-no-muted-failures.md`
**Glossary:** `CONTEXT.md` — **Filled EPIF**, **EPIF**, **Quote**, **DM card**,
**Link** (new, Part C)

Three parts. **Part A** (the form and the cards) and **Part B** (the Filled EPIF and reading
EPIFs back) are code and are independent of each other. Both use the three pure helpers
defined under Part A, so Part B is blocked by Part A. **Part C** is the glossary entry: it
changes `CONTEXT.md`, so it is held for review and must be a leaf.

## Problem Statement

1. **People enter the link twice.** On interview Screen 2 (`blocks.build_stage2_view`) the
   Purpose field is labelled "Purpose / Why Necessary & Link" with the placeholder "Why
   needed for research, and product URL (https://...)". The field directly below is
   "Product Page / Quote Link". Requesters paste the URL into both.
2. **The purchasing-channel card then shows the link twice.** `blocks.request_summary_lines`
   prints `• *Purpose:* …` (with the URL inside it) and then `• *Link:* …`. The same
   happens even when the link is entered only in Purpose: `interview.build_parsed_from_stages`
   copies the first URL out of Purpose into `link` when the Link field is blank, and the
   card prints both. The plain-text fallback built in
   `lifecycle._process_interview_completion` (`link_line`) does the same.
3. **The Filled EPIF never carries the Link field.** `epif_filler.fill_epif` writes only
   `parsed["purpose"]` into the EPIF's `Purpose` field. The only reason a link ever reaches
   purchasing on the EPIF is that the requester typed it into Purpose — which is the habit
   that causes problems 1 and 2.

## Solution

**Part A — Purpose asks only why, and nothing shows the same link twice.** Screen 2's
Purpose label and placeholder stop asking for a link, a hint under Purpose points to the
Link field, and the Link field's label says the link goes onto the EPIF. The request keeps
Purpose and Link separate everywhere (card, DM card, log). When the exact Link URL already
appears in the Purpose text, the card leaves out its `• *Link:*` line.

**Part B — the Filled EPIF gets the link, and reading an EPIF gives it back.** When the bot
fills an EPIF, Purpose is followed by a blank line and `Link: <url>`. Nothing is appended if
there is no link or the exact link is already in Purpose. Reading any EPIF, a Purpose whose
last line is only a URL (with or without a `Link:` label) gives that line back as the link
and drops it from Purpose.

**Part C — a **Link** glossary entry** in `CONTEXT.md`.

## User Stories

### Part A
1. As a requester, I want the Purpose field to ask only why I need the item, so that I do not paste the link twice.
2. As a requester with the old habit, I want a hint under Purpose telling me the link goes in the field below and is added to the EPIF for me, so that I know where it belongs.
3. As anyone reading the purchasing channel, I want each request card to show a link at most once, so that the card is not cluttered with the same URL twice.
4. As a requester who still pastes the URL into Purpose and leaves Link blank, I want the request to still record the link (log column E), so that nothing is lost.
5. As a buyer, I want the DM card to follow the same rule as the thread card, so that the two never differ.

### Part B
6. As purchasing (the person reading the EPIF), I want the product page or quote link at the end of the Purpose box, so that I can find the item without asking.
7. As a requester who puts the link in both fields anyway, I want the EPIF to show it once, so that the form looks clean.
8. As a requester who signs the Filled EPIF and drops it back into the thread, I want the card and the log to show Purpose without the link line, so that column D stays "why" only.
9. As a requester who fills an EPIF by hand and puts the URL on the last line of Purpose, I want the bot to take it as the link, so that it lands in column E.
10. As a requester who writes a URL in the middle of a sentence in Purpose, I want my purpose left exactly as written, so that the bot never cuts words out of it.

### Part C
11. As the next agent or developer, I want **Link** defined in the glossary, so that "where does the link live" has one answer.

## Implementation Decisions

### Part A

- **Three pure helpers in `src/text_rules.py`** (a pure layer that imports only `config`,
  so `blocks`, `epif_filler` and `epif_parser` can all import it without import cycles).
  They are pure functions so they can be tested with plain strings:
  - `link_in_purpose(purpose: str | None, link: str | None) -> bool` — `True` when `link`
    is non-empty after `.strip()` and the stripped link is a substring of `purpose`
    (exact, case-sensitive; no trailing-slash or `www.` normalisation). Otherwise `False`.
  - `purpose_with_link(purpose: str | None, link: str | None) -> str` — returns
    `(purpose or "").rstrip()` unchanged when the link is empty or
    `link_in_purpose(purpose, link)` is true. Otherwise returns
    `f"{(purpose or '').rstrip()}\n\nLink: {link.strip()}"`.
  - `split_trailing_link(purpose: str | None) -> tuple[str, str | None]` — strip the text,
    take its last non-blank line, and match it (after `.strip()`) against
    `r"^(?:link:\s*)?(https?://\S+)$"` with `re.IGNORECASE`. On a match **and** a non-empty
    remainder (the lines before it, joined with `"\n"`, then `.rstrip()`), return
    `(remainder, url)`. In every other case — no match, or the URL is the whole of
    Purpose — return `(purpose.strip(), None)`. Never removes anything but that last line,
    and never leaves Purpose blank (`validators` rejects a blank Purpose).
  - Each helper's docstring names this spec and says why it exists in one sentence.
  Part B uses `purpose_with_link` and `split_trailing_link`. They are defined here so both
  parts share one rule.
- **Screen 2 form**, `blocks.build_stage2_view`, the `block_purpose` input:
  - label text becomes exactly `Purpose / Why Necessary`;
  - the `_text_elem("purpose", …)` placeholder becomes exactly
    `Why this is needed for the research`;
  - the input block gains
    `"hint": {"type": "plain_text", "text": "Put the product page or quote link in the field below. It's added to the end of the EPIF's purpose for you."}`.
  The `block_link` input's label text becomes exactly
  `Product Page / Quote Link (added to the EPIF)`. Its placeholder, `optional: True`,
  `block_id`s and `action_id`s are unchanged, so stored answers and the edit form's
  prefill keep working.
- **The card's Link line**, `blocks.request_summary_lines`: append `• *Link:* {link}` only
  when `link` is truthy **and** `not text_rules.link_in_purpose(purpose, link)`. Every
  other line is unchanged. `build_request_blocks` and `build_dm_card_blocks` already call
  this function, so the thread card and the DM card follow automatically.
- **The plain-text fallback**, `lifecycle._process_interview_completion`, `link_line`: same
  condition — empty string when `text_rules.link_in_purpose(parsed["purpose"], parsed.get("link"))`.
- **Unchanged:** `interview.build_parsed_from_stages` keeps its fallback (blank Link →
  first URL in Purpose), so column E still gets a link for old-habit requests.
  `log_writer.build_row` is unchanged: column D gets Purpose as stored, column E the link.

### Part B

- **`epif_filler.fill_epif`:** the value written to the EPIF's `Purpose` field is
  `text_rules.purpose_with_link(parsed.get("purpose"), parsed.get("link"))`, applied in the
  existing `for parsed_key, pdf_key in mapping.items()` loop next to the existing
  `item_description` BOM special case. Plain text: a form text field cannot hold a
  clickable link. Every caller (approval in `finalize_purchase_request.write_action`, the
  bare-thread EPIF finalize, edits of a posted card, Switch to EPIF) goes through
  `fill_epif`, so all of them get it. The stored request's `purpose` is never changed.
  The module docstring gains one sentence: Purpose on the Filled EPIF ends with the link
  (this spec).
- **`epif_parser.parse_epif`:**
  `purpose, trailing_link = text_rules.split_trailing_link(fields.get("Purpose", ""))`;
  the returned dict's `"purpose"` is `purpose` and `"link"` is
  `trailing_link or first_url(purpose)`. `raw_fields` is unchanged (it still holds the
  PDF's text exactly).

### Part C

- `CONTEXT.md`: add one entry directly after **Quote**, exactly:

  > **Link** — the product page or quote URL for a request, given in Screen 2's
  > Product Page / Quote Link field. Kept apart from Purpose on the thread card, the DM
  > card and the log (its own column). Only on a **Filled EPIF** is it added to the end of
  > Purpose, as a last line `Link: <url>`, and not if the exact URL is already in Purpose.
  > Left blank, the first URL in Purpose is used. Reading any EPIF, a Purpose whose last
  > line is only a URL (with or without `Link:`) gives that URL back as the link.

- No ADR: this applies ADR 0007's Filled EPIF and does not change a decision.

## Testing Decisions

- **Part A helpers:** unit tests on plain strings, at least: `link_in_purpose` true/false
  and empty-link cases; `purpose_with_link` appends, skips a duplicate, skips an empty
  link; `split_trailing_link` splits `"why\n\nLink: https://a.com/x"`, splits
  `"why\nhttps://a.com/x"` (no label), splits `"why\nLINK:  https://a.com/x"` (case and
  spacing), leaves `"we need this per https://a.com/x for the beamline"` unchanged with
  `None`, and leaves `"https://a.com/x"` (URL only) unchanged with `None`.
- **Part A form:** build `blocks.build_stage2_view(meta)` and assert the `block_purpose`
  label text, the purpose placeholder, the hint text, and the `block_link` label text equal
  the strings above.
- **Part A card:** build `blocks.request_summary_lines` for (a) purpose without the URL and
  a link → one `• *Link:*` line; (b) purpose containing the exact link → no
  `• *Link:*` line and the URL appears once across all lines; (c) purpose containing a
  *different* URL → the `• *Link:*` line is present.
- **Rewrite in place, same name:**
  `tests/test_interview.py::test_stage2_modal_submit_omitting_link_falls_back_to_purpose_url`
  keeps `parsed["link"] == "https://fishersci.com/purpose-gloves"` and now asserts
  `"*Link:*"` is **not** in the card text nor in `call_kwargs["text"]`, and the URL still
  appears in the `• *Purpose:*` line. No test function is deleted.
- **Part B fill and read:** must use the real `epif_filler.fill_epif` on
  `tests/fixtures/EPIF_TEMPLATE_HIRST.pdf` and the real `epif_parser.parse_epif` on its
  output (a fake proves nothing about what the PDF holds):
  - **Rewrite in place, same name:** `tests/test_37_fill_epif.py::test_fill_epif_round_trip`
    adds `"link": "https://www.airgas.com/product/ABC123"` to `base_parsed` and asserts
    `parsed_out["purpose"] == parsed_in["purpose"]`,
    `parsed_out["link"] == parsed_in["link"]`, and
    `parsed_out["raw_fields"]["Purpose"]` ends with `"\n\nLink: https://www.airgas.com/product/ABC123"`.
  - Link already in Purpose → `raw_fields["Purpose"]` equals the purpose and contains the
    URL exactly once.
  - No link → `raw_fields["Purpose"]` equals the purpose.
  - A Purpose ending in a bare URL line → `parse_epif` returns the purpose without it and
    that URL as `link`.
- May fake: the Slack client. Must be real: `text_rules`, `blocks`, `interview`,
  `epif_filler` on the fixture, `epif_parser`.
- New test files are named after their ticket number, as in the rest of `tests/`.
- Prior art: `tests/test_37_fill_epif.py` (fixture loading), `tests/test_113_request_summary_lines.py`
  (calling `request_summary_lines` directly), `tests/test_interview.py` (Screen 2 submit).

## Human tasks

- Review and merge Part C (it changes `CONTEXT.md`, so it is held).
- Deploy (`@Purchasing update`) once Parts A and B are merged.

## Out of Scope

- The bare-thread Workday details form (`blocks.build_workday_details_view`): it already
  asks "Why is this being purchased?" and "Link to item (optional)" separately and fills no
  EPIF. Its card follows Part A's rule through `request_summary_lines` without changes.
- Making the EPIF link clickable (a link annotation drawn over the field).
- Rewriting Purpose on requests posted before the deploy.
- The buyer's email draft (`text_rules.generate_email_draft`), which already lists the link
  on its own line.
- Requiring the Link field, or validating that Purpose contains no URL.
- Log columns: no change to `config.FIELD_TO_COLUMN` or `log_writer.build_row`.
