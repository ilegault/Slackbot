# 120: Purpose asks why, and the card shows the link once

**Status:** done

**Runner:** any

**Auto-merge:** yes

**Blocked by:** None (can start immediately)

**Spec:** `.scratch/purpose-and-link/spec.md` (Part A, stories 1–5)
**Binding:** `docs/adr/0018-the-path-is-the-payment-method-and-the-dm-card-shows-the-request.md` (one builder for a request's lines); `docs/adr/0001-tests-first-and-no-muted-failures.md`
**Glossary:** `CONTEXT.md` — **DM card**, **Quote**

## What to build

On `/new-purchase` Screen 2 the Purpose field asks only why the item is needed, and a
hint under it tells the requester that the product page or quote link goes in the field
below and is added to the EPIF. The request card in the purchasing channel, the buyer's DM
card, and the channel post's plain-text fallback show a link at most once: when the exact
Link URL already appears in the Purpose text, the `• *Link:*` line is left out.

Today the Purpose field is labelled "Purpose / Why Necessary & Link", so requesters paste
the URL into both Purpose and the Link field. Even when they enter it only in Purpose,
`interview.build_parsed_from_stages` copies the first URL out of Purpose into `link`
(keep that fallback, because it fills the log's link column), and the card prints the URL
twice.

1. **`src/text_rules.py`** — add a pure function
   `link_in_purpose(purpose: str | None, link: str | None) -> bool`. It returns `True` when
   `link` is non-empty after `.strip()` and the stripped link is a substring of
   `purpose or ""` (exact and case-sensitive, with no trailing-slash or `www.`
   normalisation). Otherwise it returns `False`. The docstring names
   `.scratch/purpose-and-link/spec.md` and says in one sentence that it keeps a link from
   showing twice. It must be a pure function in `text_rules` because `blocks`,
   `epif_filler` and `epif_parser` all import it (ticket 121), and `text_rules` imports
   only `config`.
2. **`src/blocks.py` `build_stage2_view`**, the `block_purpose` input block:
   - label text becomes exactly `Purpose / Why Necessary`;
   - the placeholder passed to `_text_elem("purpose", …)` becomes exactly
     `Why this is needed for the research`;
   - the input block (the dict that holds `block_id`, `element` and `label`) gains
     `"hint": {"type": "plain_text", "text": "Put the product page or quote link in the field below. It's added to the end of the EPIF's purpose for you."}`.

   In the same function, the `block_link` input's label text becomes exactly
   `Product Page / Quote Link (added to the EPIF)`. Leave every `block_id`, `action_id`,
   placeholder, `optional` flag and `prefill_key` as it is, so the edit form's prefill
   keeps working.
3. **`src/blocks.py` `request_summary_lines`** — the `• *Link:* {link}` line is appended
   only when `link` is truthy **and** `not text_rules.link_in_purpose(purpose, link)`.
   Add `text_rules` to the module's existing two-way import block (the `from . import …`
   line and the `except ImportError` fallback). Nothing else in the function changes.
   `build_request_blocks` and `build_dm_card_blocks` already call this function, so do not
   touch them.
4. **`src/lifecycle.py` `_process_interview_completion`** — `link_line` is the empty
   string when `text_rules.link_in_purpose(parsed["purpose"], parsed.get("link"))` is
   true. Otherwise it stays as it is today.

Do **not** change `interview.build_parsed_from_stages`, `log_writer.build_row`, or
`blocks.build_workday_details_view`.

## Acceptance criteria

- [x] New `tests/test_120_purpose_and_link_on_the_card.py`, test `test_link_in_purpose`, asserts:
  - `link_in_purpose("why https://a.com/x", "https://a.com/x")` is `True`;
  - `link_in_purpose("why", "https://a.com/x")` is `False`;
  - `link_in_purpose("why https://a.com/x", "")` and `link_in_purpose("why https://a.com/x", None)` are `False`;
  - `link_in_purpose("why https://a.com/x/", "https://a.com/x/y")` is `False`.
- [x] Test `test_screen_2_purpose_asks_only_why` builds `blocks.build_stage2_view(meta)` (copy a `meta` dict from an existing Screen 2 test in `tests/test_interview.py`). Find the blocks by `block_id` and assert:
  - `block_purpose`'s `label.text == "Purpose / Why Necessary"`;
  - its `element.placeholder.text == "Why this is needed for the research"`;
  - its `hint.text` equals the hint string above;
  - `block_link`'s `label.text == "Product Page / Quote Link (added to the EPIF)"`.
- [x] Test `test_card_shows_a_link_once` calls `blocks.request_summary_lines(request, "posted")` (build `request` the way `tests/test_113_request_summary_lines.py` does) for three cases:
  - (a) purpose `"For the beamline"` with link `https://fisher.com/a`: exactly one line equals `• *Link:* https://fisher.com/a`;
  - (b) purpose `"For the beamline https://fisher.com/a"` with the same link: no line starts with `• *Link:*`, and `https://fisher.com/a` occurs exactly once across all lines joined;
  - (c) purpose `"See https://other.com/b"` with link `https://fisher.com/a`: the `• *Link:* https://fisher.com/a` line is present.
- [x] Same file, test `test_dm_card_shows_a_link_once`: `blocks.build_dm_card_blocks` for case (b) above (copy the call from `tests/test_67_dm_card.py`). Assert `https://fisher.com/a` occurs exactly once in the section text and `*Link:*` does not occur.
- [x] **Rewrite in place, same name:** in `tests/test_interview.py`, test `test_stage2_modal_submit_omitting_link_falls_back_to_purpose_url`.
  - Keep its assertion `parsed["link"] == "https://fishersci.com/purpose-gloves"`.
  - Replace its two `• *Link:*` assertions with: `"*Link:*" not in card_text`, `"*Link:*" not in call_kwargs["text"]`, and `"• *Purpose:* Supplies https://fishersci.com/purpose-gloves" in card_text`.
  - No test function is deleted. All other tests in `tests/test_interview.py` and `tests/test_113_request_summary_lines.py` pass unchanged.

May fake: the Slack client (`MagicMock`), as `tests/test_interview.py` already does. Must be real: `text_rules`, `blocks.build_stage2_view`, `blocks.request_summary_lines`, `blocks.build_dm_card_blocks`, `app.handle_stage2_submit` → `lifecycle._process_interview_completion` → `interview.build_parsed_from_stages`. A test that patches `link_in_purpose` or `request_summary_lines` does not count.

## Gate

Run all four, in CI's order, and all must pass:

    ruff check .
    python scripts/check_tests_first.py
    python tools/type_gate.py
    pytest --tb=short -q -n auto --dist loadfile

Tests need `SLACK_BOT_TOKEN=xoxb-test-not-a-real-token`, `SLACK_APP_TOKEN=xapp-test-not-a-real-token` and `PYTHONUTF8=1` in the environment, as `.github/workflows/tests.yml` sets.

## Comments
2026-10-13: Added `text_rules.link_in_purpose`; Screen 2 Purpose/Link labels, placeholder and hint; `request_summary_lines` and the channel post drop the Link line when the URL is already in Purpose. Tests: `tests/test_120_purpose_and_link_on_the_card.py` (all four criteria) and the in-place rewrite of `test_stage2_modal_submit_omitting_link_falls_back_to_purpose_url`. Gate green locally: ruff, tests-first, type_gate (95/95), pytest 847 passed. No bench verification needed; deploy is a human step.
