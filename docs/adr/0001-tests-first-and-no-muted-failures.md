# ADR 0001 — Tests first, and a failing test is never muted

**Status:** accepted
**Date:** 2026-09-16
**Applies to:** every change to `src/`, by any tool, human or agent

## Context

P-Bot spends the lab's money and writes rows into `Purchasing-Log.xlsx`, which the
lab reads as fact. A bug here is not cosmetic: somebody orders the wrong thing, or
a purchase silently never gets ordered, or an approved row disappears.

The repo grew the other way round — the app was built, and tests were written
afterwards where they were convenient. That produces two failure modes, both of
which have already happened here:

- **Invariants nobody tested.** The `/roster-list` and `/purchasing-help`
  `channel_not_found` bug shipped and stayed live because nothing asserted that a
  command actually replies. The handler ran, built its text correctly, and failed
  at the last step.
- **Tests shaped to pass.** A test written by someone who has just read the
  implementation tends to assert what the implementation does, which is not the
  same as asserting what it should do.

There is a third pressure specific to agentic development: an implementing model
is rewarded for a green build, and the cheapest way to make a red build green is
to stop the test reporting the problem. That move is always available and always
wrong.

## Decision

**1. Tests are written against the acceptance criteria, before or alongside the
implementation — never after.** CI enforces this: any commit or PR touching
`src/` must also touch `tests/` (`scripts/check_tests_first.py`). Changes to
`docs/`, `scripts/`, `.github/` or `tests/` alone pass automatically.

**2. A failing test is fixed or escalated, never muted.** Specifically, none of
the following is an acceptable response to a red test:

- marking it `xfail`, `skip`, or conditionally skipping it
- deleting the assertion, or weakening it to something that cannot fail
- loosening a tolerance without a stated domain reason
- narrowing the inputs until the case that failed is no longer exercised
- catching the exception the test was written to surface

These are all the same move under different names: making the test stop reporting
the problem instead of fixing the problem. A green suite obtained this way is
worse than a red one, because it now also lies.

**3. When a failure cannot be fixed, escalate in four steps and stop.**

1. Commit the finished, correct work to the branch. Nothing good is thrown away.
2. Set the ticket's `Status:` to `blocked` in `.scratch/<effort>/issues/NN-*.md`.
3. Append under the ticket's `## Comments` heading: what was attempted, what
   failed, and what needs a human decision.
4. Push the branch and open the pull request as a **draft**. `master` is untouched.

Guessing at a lab decision is not an alternative to escalating. A plausible-looking
answer about who may approve a purchase, or which Excel column a date belongs in,
is worse than no answer, because it will be believed.

**4. The escalation report goes in the ticket file, under `.scratch/`.** Never
under `.claude/` and never in `Claude outputs/` — both are gitignored, so anything
written there is never pushed and no reviewer, human or agent, ever sees it. The
ticket file travels with the branch, so the draft PR plus its failing CI run *is*
the handoff.

**5. The escape from the tests-first gate is explicit and visible.** For a change
under `src/` that genuinely needs no test change — a comment-only clarification, a
pure structural move fully covered by existing tests — the author declares it:
`[no-test-needed: <reason>]`, `[tests-exempt: <reason>]` or `[skip-test-gate]` in
the commit message or PR body, or a `tests-exempt` / `skip-test-gate` label. The
reason is recorded in the PR history and read during review. Silent bypassing is
not available.

**6. Zero failures before a push.** Not "the remaining failures look unrelated" —
zero. A failure that looks unrelated is a claim, and the way to support it is to
fix it or escalate it.

## Consequences

- Every ticket carries its own tests. There is no separate "write the tests" phase
  at the end of an effort, and the one in the current set (ticket 06) exists only
  to cover work that shipped before this ADR.
- CI is where test results live. Nobody is expected to run the suite locally to
  find out whether master is healthy — though an implementer runs the full gate
  before pushing, every time.
- Some tickets will end as draft PRs rather than merges. That is the intended
  outcome, not a failure: a blocked ticket with a written-down reason is a working
  handoff to a planning session.

## What this does not say

It does not say every line needs a test, and it does not say a test must exist
before a line of exploratory code is written on a scratch branch. It says that
what lands on `master` was checked by something that would have failed if the
behaviour were wrong — and that the check was never edited into agreement.
