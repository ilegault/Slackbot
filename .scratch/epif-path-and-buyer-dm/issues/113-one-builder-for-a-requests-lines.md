# 113: One builder for a request's lines

**Status:** ready-for-agent

**Runner:** any

**Auto-merge:** yes

**Blocked by:** None (can start immediately)

**Spec:** `.scratch/epif-path-and-buyer-dm/spec.md` (Part D, "One builder for the request lines")
**Binding:** `docs/adr/0018-the-path-is-the-payment-method-and-the-dm-card-shows-the-request.md` (decision 2); AGENTS.md invariant 1 (one implementation)

## What to build

Groundwork for ticket 114, which shows these same lines on the buyer's DM card. The
thread card's request lines get their own function, so the two cards can never drift
apart. **The thread card does not change at all.**

1. `src/blocks.py`: new **pure** function
   `request_summary_lines(request: dict, state: str, requester: str | None = None, items: list | None = None, attachments: list | None = None) -> list[str]`.
   Move into it the `summary_lines` construction that `build_request_blocks` does today:
   - from `parsed = request.get("parsed", request)`
   - through the `suggest_note` append, including the header line
     `🛒 *New Purchase Request from {display_name}:*`.

   It returns the list. Same lines, same order, same text.
2. `build_request_blocks` calls `request_summary_lines(request, state, requester, items, attachments)`
   and joins the result into its section exactly as today. Nothing else in
   `build_request_blocks` changes.
3. Docstring on `request_summary_lines`: why it exists (one builder for the thread card
   and the DM card, ADR 0018).

## Acceptance criteria

 - [x] New `tests/test_113_request_summary_lines.py` calls `blocks.request_summary_lines` on a request with every field set (link, buyer, expected delivery, three line items so `bom.needs_bom` is true, one `bom` attachment and two `quote` attachments). It asserts the exact list of lines: header; Item; Total; Vendor with payment method; Category; Project ID / Fund; Delivery Room; Purpose; Link; Buyer; Expected delivery; the line-items line; `📎 BOM attached: …`; `📎 Quotes: 2`.
 - [x] In the same file, for each state `posted`, `approved`, `processed`, `confirmed`, `delivered`, `declined`, `cancelled`, `waiting_for_details`: the section text of `blocks.build_request_blocks(state, request, history=[...])` equals `"\n".join(blocks.request_summary_lines(request, state))`. An unassigned request in a non-posted state includes `• *Buyer:* ⚠️ _Unassigned_`; a posted one does not.
 - [x] Every existing test in `tests/` that builds a thread card passes unchanged. No existing test is edited.

May fake: nothing; these are pure functions. Must be real: `blocks.build_request_blocks` and `blocks.request_summary_lines`.

## Gate

Run all four, in CI's order, and all must pass:

    ruff check .
    python scripts/check_tests_first.py
    python tools/type_gate.py
    pytest --tb=short -q -n auto --dist loadfile

Tests need `SLACK_BOT_TOKEN=xoxb-test-not-a-real-token`, `SLACK_APP_TOKEN=xapp-test-not-a-real-token` and `PYTHONUTF8=1` in the environment, as `.github/workflows/tests.yml` sets.

## Comments
2026-10-09: Extracted `request_summary_lines` in `src/blocks.py` as a pure function and updated `build_request_blocks` to call it and join its return value with `\n` to construct the section string. New tests verify the list fields are perfectly translated and exactly equal to the previous output across all valid states without altering the thread card output.
