# 149: Take ticket-engine's fixed tests-first check, and re-run CI on PR edits and labels

**Status:** ready-for-developer

**Runner:** any

**Auto-merge:** no

**Blocked by:** None (can start immediately)

**Waiting on:** ticket 87 in `ilegault/ticket-engine` merged to its `master`. Until then
an agent must not claim this ticket. The developer changes `Status:` to
`ready-for-agent` once 87 is merged.

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

- [ ] `scripts/check_tests_first.py` is byte-identical to the canonical file: the
  SHA-256 of the local file equals the SHA-256 of a fresh download of the URL in step 1
  (`python -c "import hashlib,sys;print(hashlib.sha256(open(sys.argv[1],'rb').read()).hexdigest())" <file>`
  on each). (no test: the two hashes, pasted under Comments)
- [ ] `python scripts/check_tests_first.py --files src/lifecycle.py` exits 1 and its output
  names `src/lifecycle.py`; adding `tests/test_x.py` to `--files` exits 0. (no test: the command output, pasted under Comments)
- [ ] `.github/workflows/tests.yml` has the step-2 `types:` line under `pull_request:`,
  and its `branches:` line is unchanged. (no test: workflow file)
- [ ] ADR 0001 and `AGENTS.md` carry the step-3 text in place of the passages named in
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
