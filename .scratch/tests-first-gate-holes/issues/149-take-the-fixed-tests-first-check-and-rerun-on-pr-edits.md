# 149: Take ticket-engine's fixed tests-first check, and re-run CI on PR edits and labels

**Status:** blocked

**Runner:** any

**Auto-merge:** no

**Blocked by:** None (can start immediately)

**Was waiting on:** ticket 87 in `ilegault/ticket-engine`. It is merged; the canonical file's
SHA-256 at the time of writing is
`ab072943baad008881a06373b4d8b632dc05c7efee2513adc0773b850b18e2c8`.

**Spec:** `.scratch/tests-first-gate-holes/spec.md` in `ilegault/ticket-engine` (D1–D7)
**Binding:** `docs/adr/0001-tests-first-and-no-muted-failures.md`

## What to build

This repo's `scripts/check_tests_first.py` passes when git cannot work out what changed,
ignores commit-message tags on PR runs, lets one tag exempt every later commit, and
treats a docstring-only edit as code. Ticket-engine's canonical copy fixes all four.
This repo takes that file unedited, so every repo runs the same gate.

1. Replace `scripts/check_tests_first.py` with the canonical file, byte for byte:
   `curl -fsSL https://raw.githubusercontent.com/ilegault/ticket-engine/master/scripts/check_tests_first.py -o scripts/check_tests_first.py`.
   Do not edit it, not even for lint. If the download fails, or `ruff check .` flags
   the file, set `Status: blocked` and say what failed under `## Comments`.
2. `.github/workflows/tests.yml`: under `pull_request:`, after its `branches:` line,
   add
   `    types: [opened, synchronize, reopened, edited, labeled, unlabeled]`.
   Nothing else in the workflow changes. The checkout already has `fetch-depth: 0`; leave it.
3. `docs/adr/0001-tests-first-and-no-muted-failures.md`, decision 5: keep the bold lead `**5. The escape from the tests-first gate is explicit and visible.**` and take the rest of that paragraph, through "Silent bypassing is not available.": replace it with:

   > A change under `src/` must also touch `tests/`. A `.py` file whose code is unchanged
   > once docstrings and comments are removed does not count as a change. Otherwise the
   > escape is explicit and visible, and its reach depends on where it is written: a tag
   > (`[no-test-needed: <reason>]`, `[tests-exempt: <reason>]` or `[skip-test-gate]`) in
   > a commit message covers only the files that commit changed, and a file is exempt
   > only when every commit that changed it is tagged; the same tag in the PR title or
   > body, or the `tests-exempt` / `skip-test-gate` label, covers the whole PR, and CI
   > re-runs when the PR text or labels change. The check fails, never passes, when it
   > cannot work out what changed.

4. `AGENTS.md`, section `### Tests-first CI check and documented escape`: the paragraph that starts "When a change touching `src/` genuinely does not require test additions", its two bullets, and the paragraph that ends "Silent bypassing is not possible.": replace it with the same text as step 3.

## Acceptance criteria

The canonical file's own tests live in ticket-engine. Here, prove the copy and the
wiring with the commands below on the PR branch; paste their output under
`## Comments`.

- [x] `scripts/check_tests_first.py` is byte-identical to the canonical file: the
  SHA-256 of the local file equals the SHA-256 of a fresh download of the URL in step 1
  (`python -c "import hashlib,sys;print(hashlib.sha256(open(sys.argv[1],'rb').read()).hexdigest())" <file>`
  on each). (no test: the two hashes, pasted under Comments)
- [x] `python scripts/check_tests_first.py --files src/lifecycle.py` exits 1 and its output
  names `src/lifecycle.py`; adding `tests/test_x.py` to `--files` exits 0. (no test: the command output, pasted under Comments)
- [x] `.github/workflows/tests.yml` has the step-2 `types:` line under `pull_request:`,
  and its `branches:` line is unchanged. (no test: workflow file)
- [x] ADR 0001 and `AGENTS.md` carry the step-3 text in place of the passages named in
  steps 3 and 4. (no test: documentation)
- [ ] The gate below passes on the PR branch (this PR changes `scripts/`, `.github/`,
  `docs/` and `AGENTS.md` only, so the tests-first check passes with no tag). (no test: the gate itself)

## Gate

Run all of them, in CI's order (`.github/workflows/tests.yml`). All must pass.

```
ruff check .
python scripts/check_tests_first.py
python tools/type_gate.py
pytest --tb=short -q -n auto --dist loadfile
```

## Comments

### Verification of Acceptance Criteria

**Criterion 1: Byte-identical hash verification**
Local file hash:
`ab072943baad008881a06373b4d8b632dc05c7efee2513adc0773b850b18e2c8`
Remote download hash:
`ab072943baad008881a06373b4d8b632dc05c7efee2513adc0773b850b18e2c8`

**Criterion 2: Command output verification**
```
$ python scripts/check_tests_first.py --files src/lifecycle.py
FAIL: Application source files modified under 'src/' without corresponding test changes under 'tests/':
  - src/lifecycle.py

Tests-first rule violation (see ADR 0001 under docs/adr/):
1. Write tests under 'tests/' covering the application changes.
2. If this change is genuinely exempt from test updates, provide an explicit escape reason:
   - PR Label: 'tests-exempt' or 'skip-test-gate'
   - Commit message or PR body: [no-test-needed: <reason>], [tests-exempt: <reason>], or [skip-test-gate]
     (a commit tag covers only the files that commit changed)
[exit code: 1]

$ python scripts/check_tests_first.py --files src/lifecycle.py tests/test_x.py
OK: Application source changes (1 file(s)) accompanied by test changes (1 file(s)).
[exit code: 0]
```

## Escalation — 2026-11-10
Repo: Slackbot   Ticket: 149 Take ticket-engine's fixed tests-first check, and re-run CI on PR edits and labels   Branch: ticket/tests-first-gate-holes-149-take-the-fixed-tests-first-check-and-rerun-on-pr-edits
Goal: Replace scripts/check_tests_first.py with ticket-engine's canonical copy, re-run CI on PR text and label edits, and update ADR 0001 and AGENTS.md.
Attempt 1: Implemented steps 1–4 exactly as specified and ran the gate → `ruff check .`, `check_tests_first.py`, and `type_gate.py` all passed, but `pytest` failed at `tests/test_59_readme_and_docs.py::test_docs_adr_is_unmodified`.
Attempt 2: Investigated failure cause → `tests/test_59_readme_and_docs.py:121` runs `git status --porcelain -- docs/adr` and `git diff --stat master -- docs/adr` to assert `docs/adr/` has not been modified relative to `master`. Modifying `docs/adr/0001-tests-first-and-no-muted-failures.md` (mandated by Ticket 149 step 3) directly causes this test to fail.
Attempt 3: Evaluated options under ADR 0001 → ADR 0001 forbids deleting, weakening, or muting an existing test without explicit human decision, and Ticket 149 scope explicitly excludes modifications under `tests/`. Therefore, the agent must not delete or modify `test_docs_adr_is_unmodified`.
Failing output:
```
================================== FAILURES ===================================
_________________________ test_docs_adr_is_unmodified _________________________
[gw1] win32 -- Python 3.14.3 C:\Users\IGLeg\AppData\Local\Python\pythoncore-3.14-64\python.exe
tests\test_59_readme_and_docs.py:121: in test_docs_adr_is_unmodified
    assert status.stdout.strip() == "", f"docs/adr has uncommitted modifications:\n{status.stdout}"
E   AssertionError: docs/adr has uncommitted modifications:
E      M docs/adr/0001-tests-first-and-no-muted-failures.md
E     
E   assert 'M docs/adr/0...d-failures.md' == ''
E     
E     + M docs/adr/0001-tests-first-and-no-muted-failures.md
=========================== short test summary info ===========================
FAILED tests/test_59_readme_and_docs.py::test_docs_adr_is_unmodified - Assert...
1 failed, 929 passed, 31 skipped in 39.94s
```
Decision needed: `test_docs_adr_is_unmodified` in `tests/test_59_readme_and_docs.py` was written for Ticket 59 ("No file under docs/ outside docs/adr/ contains @p-bot or P-Bot; docs/adr/ is untouched") but permanently asserts in git that `docs/adr/` is never modified relative to master. Should `test_docs_adr_is_unmodified` be removed or adapted so ADRs (such as ADR 0001) can be amended as required by Ticket 149?
