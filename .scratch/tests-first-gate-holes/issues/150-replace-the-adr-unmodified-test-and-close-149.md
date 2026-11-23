# 150: Replace `test_docs_adr_is_unmodified` with a test that holds everywhere, and close 149

**Status:** in-progress

**Runner:** any

**Auto-merge:** no

**Blocked by:** None (can start immediately)

**Binding:** `docs/adr/0001-tests-first-and-no-muted-failures.md`. The developer made the
human decision this ticket carries out (see 149's `## Comments`, 2026-11-13). Changing this
test is therefore a decided fix of a broken test, not a mute.

## Why

Ticket 149 escalated on `tests/test_59_readme_and_docs.py::test_docs_adr_is_unmodified`.
That test is broken, not the code:

1. **It turned a one-time check into a permanent rule.** Ticket 59
   (`.scratch/commands-paths-and-name/issues/59-readme-and-docs.md`, criterion 4) required
   that *its own* rename of P-Bot through `docs/` leave `docs/adr/` alone, because ADRs are a
   historical record. The test turned that into "no branch may ever change `docs/adr/`".
   ADRs are routinely added (0021) and amended (149 amended 0001), so every such branch fails.
2. **It can never fail in CI.** The `test` job in `.github/workflows/tests.yml` checks out
   with depth 1. In that checkout `master`, `origin/master` and `HEAD^1` all fail
   `git rev-parse --verify`, so `base_ref` is `None` and the diff half is skipped. What is left,
   `git status --porcelain -- docs/adr`, is always empty on a fresh checkout. That is why
   PR 182 was green in CI and red locally.

What ticket 59 actually protects is: **the historical ADRs keep the bot's old name; nobody
scrubs "P-Bot" out of them.** A test can assert that the same way locally and in CI, and it
still fails if someone runs a docs-wide rename over `docs/adr/`.

## What to build

1. In `tests/test_59_readme_and_docs.py`, replace `test_docs_adr_is_unmodified` with
   `test_historical_adrs_keep_the_old_bot_name`. For each of these four files under
   `docs/adr/`:
   - `0001-tests-first-and-no-muted-failures.md`
   - `0002-request-lifecycle-and-surfaces.md`
   - `0007-purchase-path-and-generated-epif.md`
   - `0009-keywords-storage-settings-and-the-bot-name.md`

   assert that the file exists and that `re.search(r"\bp-bot\b", text, re.IGNORECASE)`
   matches, using the same regex as `test_docs_contain_no_p_bot_outside_adr`
   in the same module. Collect all misses and assert once, naming each file that lost the
   name. No `subprocess`, no git, no comparison against a branch.
2. Remove the now-unused `import subprocess` if nothing else in the module uses it
   (ruff will flag it).
3. Update the module docstring's acceptance-criteria bullet
   "No file under docs/ outside docs/adr/ contains @p-bot or P-Bot; docs/adr/ is untouched."
   to say instead that docs/adr/ is a historical record and the ADRs listed above still name
   P-Bot. Add one sentence of *why*: the original "untouched" check compared against `master`,
   which blocked every legitimate ADR change locally and could not run in CI's shallow checkout.
4. Do **not** change any other test, any file under `src/`, `docs/adr/`, or `scripts/`.
   `scripts/check_tests_first.py` is the canonical copy and is never edited.
5. Close ticket 149: in
   `.scratch/tests-first-gate-holes/issues/149-take-the-fixed-tests-first-check-and-rerun-on-pr-edits.md`,
   tick its last acceptance criterion, set its `Status:` to `done`, and append a dated line
   under its `## Comments` naming this ticket's PR.

## Acceptance criteria

- [ ] `test_docs_adr_is_unmodified` no longer exists; `test_historical_adrs_keep_the_old_bot_name`
  passes on master and on this branch. (test: the new test itself)
- [ ] The new test fails when the old name is removed. Prove it by hand, not with a committed
  test: temporarily replace `P-Bot` with `Purchasing` in ADR 0009, run the test, confirm it fails
  and names `0009-…`, then `git checkout -- docs/adr`. Paste the failing output under
  `## Comments`. (no test: the pasted output)
- [ ] The new test still passes on a branch that edits an ADR without touching the old name.
  Prove it by hand: append a blank line to ADR 0021, run the test, confirm it passes, then
  `git checkout -- docs/adr`. Paste the output under `## Comments`. (no test: the pasted output)
- [ ] `tests/test_59_readme_and_docs.py` has no `subprocess` import left unless still used,
  and its module docstring carries the reworded bullet and the *why* from step 3.
  (no test: ruff plus reading the docstring)
- [ ] Ticket 149 is `done` with its last criterion ticked. (no test: ticket file)

## Gate

Run all of them, in CI's order (`.github/workflows/tests.yml`). All must pass.

```
ruff check .
python scripts/check_tests_first.py
python tools/type_gate.py
pytest --tb=short -q -n auto --dist loadfile
```

**One known local-only failure is not this ticket's:**
`tests/test_54_storage_settings.py::test_no_default_paths_and_no_template_dir` fails on a
machine whose `.env` sets `PURCHASING_LOG_PATH`. The test clears `config._env_candidates`
and then calls `importlib.reload(config)`, and the reload rebuilds the list and reads `.env`
again. It passes in CI, which has no `.env`. Do not fix it on this branch and do not count it
against this gate; say in the PR body that you saw it. Every other test must pass.

## Comments
