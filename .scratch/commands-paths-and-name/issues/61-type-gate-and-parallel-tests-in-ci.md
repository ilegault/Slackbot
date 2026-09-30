# 61: Add the layered type gate and parallel test run to CI

**Status:** in-progress

**Runner:** any

**Auto-merge:** no

**Blocked by:** 51, 52, 53, 54, 55, 56, 57, 58, 59

**Spec:** `.scratch/commands-paths-and-name/spec.md` (tooling follow-on)
**Binding:** `docs/adr/0001-tests-first-and-no-muted-failures.md`

## What to build

The developer's other repo (RBL) runs four CI gates; this repo runs three. Bring this
repo to the same four:

```
ruff check .
python scripts/check_tests_first.py
python tools/type_gate.py
pytest --tb=short -q -n auto --dist loadfile --durations=25
```

This ticket changes `.github/`, so it is **held** (`Auto-merge: no`) and is a leaf. It is
blocked by the rest of this set so tickets 51–59 keep the gate list they were written with.

1. **`tools/type_gate.py` (new).** Port RBL's `tools/type_gate.py` (reproduced in the
   `## Reference` section below; do not fetch it from anywhere). Two changes for this
   repo's layout: the config table is `[tool.pbot.type_gate]`, and hard entries are
   module *files* under `src/` (`src/text_rules.py`), not packages — `_is_hard` matches
   `normalized == "src/" + module + ".py"`. Keep its module docstring's reasoning and add
   one line on the flat-module difference.
2. **`pyproject.toml`:** add
   ```toml
   [tool.mypy]
   python_version = "3.12"
   warn_redundant_casts = true
   warn_unused_ignores = true
   implicit_optional = true
   ignore_missing_imports = true
   files = ["src"]

   [tool.pbot.type_gate]
   hard = [ ... ]
   ```
   **Hard candidates:** `config`, `epif_parser`, `validators`, `interview`, `bom`,
   `text_rules` (the config and domain layers, AGENTS.md §2). Run mypy once; `hard` is
   exactly the candidates with **zero** errors in that run. Record each excluded
   candidate and its error count under `## Comments`. Do not fix type errors in this
   ticket.
3. **`tools/mypy_ratchet.txt` (new):** one integer, the number of non-hard errors in that
   same run.
4. **`requirements-dev.txt`:** add `mypy>=1.10.0` and `pytest-xdist>=3.6`.
5. **`.github/workflows/tests.yml`:** after the tests-first step, add the type-check step
   exactly as RBL does it — a step with `id: typecheck`, `continue-on-error: true`,
   `run: python tools/type_gate.py`, then an `Enforce type gate` step with
   `if: always() && steps.typecheck.outcome != 'success'` and `run: exit 1`. Change the
   pytest step to `pytest --tb=short -q -n auto --dist loadfile --durations=25`.
6. **`AGENTS.md` is not edited** (the developer's file). Note in the PR description that
   §1's gate block and §11 step 5 list three gates and the developer should update them.

## Acceptance criteria

- [ ] `python tools/type_gate.py` exits 0 on the branch, and its last summary line
  reports 0 hard-layer errors and a soft count equal to `tools/mypy_ratchet.txt`.
- [ ] **The gate bites (hard).** In `tests/test_61_type_gate.py`, run
  `tools/type_gate.py`'s bucketing on a synthetic mypy output containing one error line
  for a hard module file: `main`'s logic returns 1. Factor the bucketing into a pure
  function (`classify(lines, hard_prefixes) -> (hard, soft)`) so the test drives it
  without running mypy.
- [ ] **The gate bites (ratchet).** Soft count one above the ratchet → returns 1; equal →
  returns 0. Test the comparison as a pure function too.
- [ ] **Parallel is safe.** The full suite passes with
  `pytest --tb=short -q -n auto --dist loadfile` three runs in a row locally; paste the
  three summary lines under `## Comments`. If any test fails only under `-n`, fix the
  shared state (a temp path, a module global) — never mark it serial or skip it.
- [ ] CI on the PR shows the four gates in the order above, all green.

## Reference — RBL `tools/type_gate.py` `main` logic to port

Run `python -m mypy` from the repo root; mypy exit codes other than 0/1 are a hard
failure. Bucket each `^<path>:<line>:(<col>:)? error:` line into hard (path under a hard
module) or soft. Any hard error → print them, return 1. Soft count above the integer in
`tools/mypy_ratchet.txt` → print "soft-layer error count rose from N to M; fix the new
error(s), or if every error is pre-existing, lower the ratchet — it may only decrease",
return 1. Otherwise return 0. Read the hard list from `pyproject.toml` with `tomllib`.

## Gate

Before this ticket lands, CI runs the three below; this ticket adds the other two
commands above.

```
ruff check .
python scripts/check_tests_first.py
pytest -q --tb=short --durations=25
```

## Comments
