# 07: Restore the lint gate to the rules it was meant to enforce

**What to build:** Clear the lint debt with `ruff check --fix`, fix by hand what
`--fix` cannot, and then **narrow the ignore list back down** so the gate enforces
import sorting, unused imports, empty f-strings and unused locals again.

**Blocked by:** 01

**Status:** done

`docs/adr/0001-tests-first-and-no-muted-failures.md` is binding. This ticket is
the lint-side application of its reasoning.

## Why

When CI was introduced the gate was `select = ["E", "F", "I"]` with no blanket
ignores. Against the tree at that moment it reported **137 errors**, so the gate
was made green by narrowing the gate: `I` was dropped from `select`, and
`ignore = ["E501", "F401", "F541", "F841"]` was added.

That is a defensible call on a legacy tree, and the comment in `pyproject.toml`
invited exactly it. But it is structurally the same move ADR 0001 forbids for
tests — making the check stop reporting the problem rather than fixing the problem
— and it happened on the one check where that ADR does not literally apply. Left
alone it quietly stops being a gate: new code inherits the silence, and the debt
only grows.

The debt is small and mostly mechanical:

| Rule | What it is | Count |
|---|---|---|
| `E501` | line longer than 120 characters | 78 |
| `I001` | import block un-sorted | 27 |
| `F541` | f-string with no placeholders | 22 |
| `F401` | imported but unused | 9 |
| `F841` | local variable assigned but never used | 1 |

**59 of the 137 are auto-fixable.** This is an afternoon, not a project.

## Timing: this runs before 02, 04 and 05, and alone

An import-sorting and unused-import sweep touches nearly every file in `src/` and
`tests/`. Run concurrently with any other ticket it produces a merge conflict in
every file both branches touched, for no reason.

**Work this ticket when no other branch is open.** 01 is done; 02, 04 and 05 have
not started. That makes right now the cheapest moment this sweep will ever have.
If another ticket is already in flight when you pick this up, say so and stop.

## Requirements

1. **No behaviour change.** Same rule as ticket 01: if the diff contains anything
   that is not a lint fix, it is the wrong diff.
2. **Check `--fix` did not remove an import with a side effect.** Ruff's unused-import
   fix is safe in general, but this codebase imports for side effects in places and
   every module carries the `try: from . import config / except ImportError: import
   config` shim. Read every removed import before accepting it. An import removed
   because it "looked unused" is how the PyInstaller build breaks at runtime rather
   than at build time.
3. **`E501` stays ignored, and that is deliberate.** 78 long lines are mostly Block
   Kit dictionaries and message strings where a hard wrap hurts readability. Leave
   the ignore in place with a comment saying it is the one accepted exception —
   an accepted exception that is written down is not the same as a silenced rule.
4. **Everything else comes off the ignore list.** `F401`, `F541` and `F841` go, and
   `I` goes back into `select`. If any of them cannot be cleared, that is an
   escalation with the specific files named — not a reason to leave the rule off.
5. **Use the documented tests-first escape.** This touches `src/` and adds no
   tests, which is exactly the case the escape exists for. Commit with
   `[no-test-needed: lint-only cleanup, no behaviour change]` in the message so the
   reason is visible in review. Do not add a token test to get past the gate —
   that is gaming the check, and it is the same move in a third costume.

## Acceptance criteria

- [x] `ruff check --fix` has been run and its changes reviewed file by file
- [x] Every import `--fix` removed has been read and confirmed genuinely unused —
      state in the PR how many were removed and that each was checked
- [x] Remaining `I001`, `F541`, `F401` and `F841` violations are fixed by hand
- [x] `pyproject.toml` `select` is back to `["E", "F", "I"]`
- [x] `pyproject.toml` `ignore` is `["E501"]` and nothing else, with a comment
      stating why that one is accepted
- [x] The `per-file-ignores` for the `E402` import shims are unchanged — those are
      a real structural constraint, not debt
- [x] `ruff check .` passes with the narrowed configuration
- [x] `python app.py` still starts against a test `.env`, proving no
      side-effect import was dropped
- [x] The full suite passes **unchanged in meaning** — no test file's assertions
      are altered, only its imports
- [x] The commit message carries `[no-test-needed: lint-only cleanup, no behaviour
      change]`
- [x] `ruff check .`, `python scripts/check_tests_first.py` and `pytest -q` all pass
- [x] CI is green and was watched to green

## Comments

### 2026-09-16 Implementation Summary
- Updated `pyproject.toml` to restore `select = ["E", "F", "I"]` and narrow `ignore = ["E501"]` with a documented rationale that line length wrapping hurts readability in Block Kit dicts and messages.
- Ran `ruff check --fix` and resolved all 59 violations (27 `I001` import sorts, 22 `F541` empty f-strings, 9 `F401` unused imports, 1 `F841` unused local variable in `src/queue_worker.py`).
- Audited all 9 removed imports file-by-file to confirm they were genuinely unused and that no side-effect imports or PyInstaller relative-import shims were affected:
  - `src/heartbeat.py`: `import time`
  - `src/path_validator.py`: `from pathlib import Path`
  - `src/queue_worker.py`: `import time`
  - `src/roster.py`: `from typing import Optional`
  - `tests/test_monitoring_and_queue.py`: `from datetime import date`, `import platform`
  - `tests/test_roster.py`: `import tempfile`
  - `tests/test_store.py`: `import json`, `import tempfile`
- Verified `python app.py` starts cleanly and runs initialization logic without error.
- Ran full test suite locally: 75 passed, 28 skipped (all unchanged).
- Passed full local gate: `ruff check .`, `python scripts/check_tests_first.py`, and `pytest -q --tb=short`.
