# 142: A one-item request needs a link or "No web page"

**Status:** ready-for-agent

**Runner:** any

**Auto-merge:** yes

**Blocked by:** 140

**Spec:** `.scratch/item-links/spec.md` (Implementation Decisions: One-item request, Screen 2)
**Binding:** `docs/adr/0020-every-item-has-a-link-or-a-reason.md` (decision 4); `docs/adr/0001-tests-first-and-no-muted-failures.md`
**Glossary:** `CONTEXT.md` — **Item link**, **No-link reason**

## What to build

On interview Screen 2 a request with no BOM must give its item link or tick **No web page**.
A URL already in Purpose counts as the link. A ticked box shows "No web page" where the card
would show the link.

The Screen 2 field is the one in `blocks.build_stage2_view` labelled "Product Page / Quote
Link (added to the EPIF)", `block_id` `block_link`. (The spec calls it "Link to item
(optional)"; that label belongs to `build_workday_details_view`, which this ticket does not
change.)

1. **`src/blocks.py` `build_stage2_view`** — keep `block_link` `optional: True` (the handler
   applies the rule, because it depends on the BOM field). Change its label to
   `"Product Page / Quote Link (added to the EPIF)"` → `"Link to the item's web page"`, add the
   hint `"Required unless you attach a BOM or tick No web page."`, and directly after it add:
   `{"type": "input", "block_id": "block_no_link", "optional": True, "label": {"type": "plain_text", "text": "No link?"}, "element": {"type": "checkboxes", "action_id": "no_link", "options": [{"text": {"type": "plain_text", "text": "No web page"}, "value": "no_web_page"}]}}`.
2. **`src/app.py` `handle_stage2_submit`** — right after the `bom_errors` refusal, only when
   `raw_bom_files` is empty:
   - link field non-blank → `bom.normalize_link` (ticket 140). `None` → answer
     `response_action="errors"` with
     `{"block_link": "That isn't a web address. Paste the item's web page, or tick No web page."}`;
     otherwise store the normalized value in `stage2["link"]`.
   - link field blank and `epif_parser.first_url(stage2["purpose"])` finds a URL → accepted,
     nothing stored (`interview.build_parsed_from_stages` already takes that URL as the link).
   - link field blank, no URL in Purpose, box ticked → `stage2["no_link_reason"] = config.NO_LINK_REASONS[0]`.
   - link field blank, no URL in Purpose, box unticked → errors
     `{"block_link": "Paste the item's web page, or tick No web page."}`.
3. **`src/interview.py` `build_parsed_from_stages`** — carry `no_link_reason` from `stage2`
   into the returned dict (empty string when absent), next to `link`.
4. **`src/blocks.py` `request_summary_lines`** and the `link_line` in
   **`src/lifecycle.py` `_process_interview_completion`** — when `parsed["link"]` is empty
   and `parsed.get("no_link_reason")` is set, show `• *Link:* No web page`.

## Acceptance criteria

New file `tests/test_142_one_item_link_rule.py`, driven through `app.handle_stage2_submit`
with the helpers of `tests/test_81_quotes_on_new_purchase.py`
(`_make_stage2_view_submission`, `_sample_stage1_meta`) and a `MagicMock` client. May be
faked: the Slack client. Must be real: the handler, `bom.normalize_link`,
`interview.build_parsed_from_stages`, `blocks.request_summary_lines`.

- [ ] `test_blank_link_no_url_no_tick_is_refused` — `ack` is called with `response_action="errors"` and `errors == {"block_link": "Paste the item's web page, or tick No web page."}`; `client.chat_postMessage` is not called.
- [ ] `test_bad_link_is_refused` — link `see the quote` gives the "That isn't a web address…" error on `block_link`.
- [ ] `test_link_without_scheme_is_stored_with_https` — link `mcmaster.com/91251A540` posts a card whose text contains `https://mcmaster.com/91251A540`.
- [ ] `test_url_in_purpose_counts_and_no_web_page_shows_on_card` — blank link with `https://x.org/p` in Purpose is accepted; blank link, no URL, `no_web_page` ticked is accepted and the posted card's text contains `• *Link:* No web page`.
- [ ] `test_rule_skipped_with_a_bom` — blank link, no tick, a BOM attached: no `block_link` error (the BOM check view is shown instead).
- [ ] Existing Screen 2 tests that submit a blank link without a URL in Purpose are updated in place (give them a link) under their existing names; none deleted. (no test: existing tests rewritten in place; the full suite passing is the proof)

## Gate

    ruff check .
    python scripts/check_tests_first.py
    python tools/type_gate.py
    pytest --tb=short -q -n auto --dist loadfile --durations=25

## Out of scope

The Workday details form's link field, Edit's link field, EPIF-born requests. The BOM check
(141). Visiting the link.

## Comments
