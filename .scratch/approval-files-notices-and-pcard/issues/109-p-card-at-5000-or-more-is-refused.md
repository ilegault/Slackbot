# 109: A P-card at $5,000 or more is refused

**Status:** done

**Runner:** any

**Auto-merge:** yes

**Blocked by:** None (can start immediately)

**Spec:** `.scratch/approval-files-notices-and-pcard/spec.md` (Part C, stories 24–26)
**Binding:** `docs/adr/0017-p-card-under-5000-req-po-at-5000-and-over.md` (decisions 1–2); AGENTS.md invariant 4 (constants live in `config.py`); ADR 0001
**Glossary:** `CONTEXT.md` — **P-card**, **Req/PO**

## What to build

1. `src/config.py` — `PCARD_LIMIT = 5000.00` and
   `PCARD_LIMIT_MESSAGE = "P-card is for orders under $5,000. Pick Req/PO."`.
2. `src/validators.py` — new **pure** function
   `pcard_problem(payment_method: str | None, total_price: float | None) -> str | None`.
   It returns `config.PCARD_LIMIT_MESSAGE` when `payment_method` lowercased equals `"p-card"`
   and `total_price` is a number `>= config.PCARD_LIMIT`. Otherwise it returns `None`. In
   `validate`, right after the existing payment-method check, append its result when not
   `None`. This one rule then covers approval (`finalize_purchase_request`), the Edit
   submission (`src/app.py` around the `EDIT_CALLBACK_ID` view, whose error mapping already
   sends "p-card" problems to `block_payment_method`), and dropped EPIFs (ticket 102's reply
   lists every `validate` problem).
3. `src/app.py` `handle_stage2_submit` — Screen 2 moves on to Screen 3 **without** running
   `validate` when the category needs asset details. An error raised later would point at
   `block_payment_method`, which is not on Screen 3, and Slack rejects that. So, after the
   existing BOM/line-item checks and before the Screen 3 / completion branch, call
   `validators.pcard_problem(stage2.get("payment_method"), stage2.get("total_price"))`. If it
   returns a message, `ack(response_action="errors", errors={"block_payment_method": msg})`
   and return.

## Acceptance criteria

- [x] New `tests/test_109_pcard_limit.py` tests `pcard_problem` directly: (`"P-card"`, 4999.99) → None; (`"P-card"`, 5000.00) → the message; (`"p-card"`, 12000) → the message; (`"Req/PO"`, 2520) → None; (`"Req/PO"`, 9000) → None; (`"P-card"`, None) → None.
- [x] Submitting Screen 2 (drive `app.handle_stage2_submit` with a view state, as `tests/test_28_line_items_modal_path.py` does) with P-card and total 6000 calls `ack` with `response_action="errors"` and `errors == {"block_payment_method": "P-card is for orders under $5,000. Pick Req/PO."}`. This holds for a category that needs asset details too: the view is not advanced to Screen 3.
- [x] Approving an EPIF whose parsed `payment_method` is `"P-card"` and total 7500 writes no row. The thread reply says "Not logged", and the requester is DM'd text that contains the message.
- [x] Req/PO at $2,520 approves normally. A row is written on the temp workbook.

May fake: the Slack client, `parse_epif` in criterion 3. Must be real: `validators.validate`, `pcard_problem`, `handle_stage2_submit`, the workbook write on a temp copy.

## Gate

Run all four, in CI's order, and all must pass:

    ruff check .
    python scripts/check_tests_first.py
    python tools/type_gate.py
    pytest --tb=short -q -n auto --dist loadfile

Tests need `SLACK_BOT_TOKEN=xoxb-test-not-a-real-token`, `SLACK_APP_TOKEN=xapp-test-not-a-real-token` and `PYTHONUTF8=1` in the environment, as `.github/workflows/tests.yml` sets.

## Comments

2026-10-08: Added config.PCARD_LIMIT/MESSAGE, validators.pcard_problem (also in validate), and a Screen 2 check in app.handle_stage2_submit. All four criteria covered by tests/test_109_pcard_limit.py. Gate green locally.
