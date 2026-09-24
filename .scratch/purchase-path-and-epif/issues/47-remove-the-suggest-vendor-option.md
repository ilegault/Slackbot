# 47: Finish 34: remove the suggest option and relabel the EPIF option

**Status:** ready-for-agent

**Runner:** any

**Auto-merge:** yes

**Blocked by:** None (can start immediately)

Spec: Implementation Decision 1, first bullet. Binding: ADR 0007 decisions 1–2.

**What to build:** Ticket 34 added `add-vendor` but left Screen 1 unchanged. Remove the
"Suggest a new vendor that was added to workday" option everywhere, and relabel the last
option **"None of these — this will be an EPIF order"**.

- [ ] `config.VENDOR_SUGGEST_OPTION` is deleted, with every reader: `blocks.build_stage1_view`, the branches in `src/interview.py`, the "Suggested new vendor" note and admin alert in `src/lifecycle.py`, and the near-miss check in `app.handle_stage1_submit`. `grep -rn VENDOR_SUGGEST_OPTION src tests` returns nothing.
- [ ] `config.VENDOR_OTHER_OPTION == "None of these — this will be an EPIF order"`. A test builds `blocks.build_stage1_view()` and asserts its last vendor option's text and value are exactly that string, and that no option contains `Suggest`.
- [ ] Routing still comes only from `interview.route_vendor`: a test asserts a listed vendor routes to `workday` and `VENDOR_OTHER_OPTION` routes to `epif`.
- [ ] The near-miss tests in `tests/test_35_warn_near_miss_vendor.py` still pass unmodified.
- [ ] Full gate green, in CI order: `ruff check .`, `python scripts/check_tests_first.py`, `pytest -q`.

**Tests may fake:** the Slack client. Use the real `blocks`, `interview` and `config`.

## Comments
