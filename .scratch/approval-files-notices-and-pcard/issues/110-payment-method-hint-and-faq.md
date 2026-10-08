# 110: The Payment Method hint and FAQ explain P-card vs Req/PO

**Status:** done

**Runner:** any

**Auto-merge:** yes

**Blocked by:** 109

**Spec:** `.scratch/approval-files-notices-and-pcard/spec.md` (Part C, stories 23 and 27)
**Binding:** `docs/adr/0017-p-card-under-5000-req-po-at-5000-and-over.md` (decisions 3–4); AGENTS.md invariant 4; ADR 0001
**Glossary:** `CONTEXT.md` — **P-card**, **Req/PO**

## What to build

1. `src/config.py` — `PAYMENT_METHOD_HINT`, exactly:
   `P-card — the lab's university credit card, for orders under $5,000. Req/PO — a purchase order placed through UW purchasing; required at $5,000 and over (get 3 quotes), or whenever a vendor only accepts a PO.`
2. `src/blocks.py` — the `block_payment_method` input block (in the `if route == "epif":`
   branch that builds `pm_options`) gains
   `"hint": {"type": "plain_text", "text": config.PAYMENT_METHOD_HINT}`. Slack's limit for a
   hint is 2000 characters, and this text is far under it.
3. `src/interview.py` — `FAQ_ANSWERS["p-card"]`, `FAQ_ANSWERS["req/po"]` and
   `FAQ_ANSWERS["req po"]` all become `config.PAYMENT_METHOD_HINT`.
4. The bot does not count quotes anywhere (ADR 0017 decision 3).

## Acceptance criteria

- [x] New `tests/test_110_payment_hint.py`: the Screen 2 view built for the EPIF route has a block with `block_id == "block_payment_method"` whose `hint.text` equals `config.PAYMENT_METHOD_HINT`. Copy the view-building call from `tests/test_81_quotes_on_new_purchase.py::test_screen2_renders_quotes_field_when_not_edit`.
- [x] The Edit view for an EPIF-route card carries the same hint on `block_payment_method`.
- [x] The Workday-route Screen 2 has no `block_payment_method` block (unchanged).
- [x] The three FAQ keys return exactly `config.PAYMENT_METHOD_HINT`.

May fake: nothing beyond roster setup. Builders are pure. Must be real: the block builders and `FAQ_ANSWERS`.

## Gate

Run all four, in CI's order, and all must pass:

    ruff check .
    python scripts/check_tests_first.py
    python tools/type_gate.py
    pytest --tb=short -q -n auto --dist loadfile

Tests need `SLACK_BOT_TOKEN=xoxb-test-not-a-real-token`, `SLACK_APP_TOKEN=xapp-test-not-a-real-token` and `PYTHONUTF8=1` in the environment, as `.github/workflows/tests.yml` sets.

## Comments

### 2026-10-08 - Implementation Summary
- Added `config.PAYMENT_METHOD_HINT`; `blocks.build_stage2_view` puts it as the `hint` on `block_payment_method` (EPIF route, create and Edit); `interview.FAQ_ANSWERS` keys `p-card`, `req/po`, `req po` now return it.
- Tests: `tests/test_110_payment_hint.py` covers all four criteria (create view, Edit view, Workday route has no block, three FAQ keys).
- Gate: ruff, check_tests_first, type_gate (94 <= ratchet 95), pytest 810 passed / 31 skipped.
