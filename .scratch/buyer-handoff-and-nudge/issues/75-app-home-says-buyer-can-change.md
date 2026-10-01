# 75: App Home says the buyer can be changed until Processed

**Status:** in-progress

**Runner:** any

**Auto-merge:** yes

**Blocked by:** 73

**Spec:** `.scratch/buyer-handoff-and-nudge/spec.md` (Further Notes)
**Binding:** `docs/adr/0011-buyers-hand-off-requests-and-the-request-log.md` decision 1, ADR 0001

## What to build

The help text on App Home and `/purchasing-help` tells people the buyer can be changed from
the card by any buyer until the request is Processed, and stops teaching the old rule.

1. `blocks._BUTTON_LIST` (the shared constant both `build_app_home_view` and
   `get_help_message` render): replace the last sentence
   `Any buyer can take it with \`@Purchasing assign @themselves\`.` with
   `Any buyer can pick a buyer from the card — or move it to someone else — until it is *Processed*.`

## Acceptance criteria

New test file `tests/test_75_help_says_buyer_can_change.py`.

- [ ] `blocks.get_help_message()` contains `until it is *Processed*` and does not contain
  `@Purchasing assign @themselves`.
- [ ] The JSON of `blocks.build_app_home_view("U_ANY")` contains `until it is *Processed*`
  and does not contain `@Purchasing assign @themselves`.

**Tests may fake:** nothing needed beyond a temp roster if `build_app_home_view` reads it.
**Must be real:** `blocks`.

## Gate

Run in this order, exactly as CI does (`.github/workflows/tests.yml`). Zero failures before
you push. If `tools/type_gate.py` exists on `master` when you start, also run
`python tools/type_gate.py` after `check_tests_first.py`, and use
`pytest --tb=short -q -n auto --dist loadfile` in place of the last line.

```
ruff check .
python scripts/check_tests_first.py
pytest -q --tb=short --durations=25
```

## Comments
