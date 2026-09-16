---
name: pbot-ticket
description: Implement one ticket from a P-Bot ticket set end to end — orientation, implementation, the full local gate, adversarial self-review, and the PR. Use whenever asked to implement, work, pick up or continue a ticket, work the frontier, or act on the ACTIVE-PLAN block in AGENTS.md.
---

# Implementing one P-Bot ticket

This bot spends the lab's money and writes rows into `Purchasing-Log.xlsx`, which
the lab reads as fact. A wrong row is not a cosmetic bug: somebody orders the wrong
thing, or an approved purchase silently never gets ordered. That is why the
conventions here are strict, and why a green suite that was made green by editing a
test is worse than a red one.

Work **one ticket**. Not two, not a ticket and a half. If you finish early, stop
and report; do not wander into the next ticket.

## 1. Orient before touching anything

### Repository and branch housekeeping

Before selecting or starting a ticket:

```bash
git checkout master
git pull origin master
git fetch --prune
```

Then check the frontier from the freshly updated `master`. Delete local branches
already merged into `master`.

### Orientation steps

Read, in this order:

1. **`AGENTS.md`** — the whole file. The layering rule, the five invariants, the
   conventions, the known traps, and the `ACTIVE-PLAN` block at the bottom naming
   the current ticket set and which tickets are unblocked.
2. **The ticket file** under `.scratch/<effort>/issues/NN-*.md`. Its `Blocked by:`
   line and its acceptance criteria are the contract.
3. **Every ADR the ticket references**, in `docs/adr/`. They are binding, not
   background. A ticket that names one expects you to have read it.
4. **`CONTEXT.md`** — the glossary. Use its words. Above all: the stage is
   **processed**, never *submitted*. If a term you need is missing or the code
   contradicts it, say so; do not silently pick a side.
5. **The module docstring of every file you are about to edit.**

**Work the frontier.** Never start a ticket whose `Blocked by:` names an unfinished
one. If the only unblocked ticket is `human-task` — a Slack action, a server
deploy, a lab decision — say so and stop. Do not claim it, do not simulate it, do
not build around it.

**Claim the ticket**: set its `Status:` line to `in-progress` and save, before
writing any code.

## 2. Decide whether to split into parallel agents

Judge by the seam, not by size.

**Split when the pieces do not share a seam:**

- **Independent tickets.** Two unblocked tickets touching disjoint files run
  cleanly as two agents on two branches. After ticket 01 of the current set lands,
  tickets 02, 04 and 05 are exactly this. This is the split that pays.
- **Implementation and tests, written independently.** One agent implements from
  the ticket. A second writes the tests from the acceptance criteria **without
  reading the implementation**. Then reconcile. This is the single most valuable
  split here, because it is the only cheap defence against tests shaped to pass. A
  test written by someone who has just read the code asserts what the code does.
- **A survey across many files** where each verdict is independent.

**Do not split when:**

- **The ticket is one vertical slice.** A slice through blocks → lifecycle →
  listeners → tests splits into three agents editing toward an interface none of
  them owns, then a merge nobody designed.
- **The pieces share a test seam**, such as the fake Slack client helpers.
- **You are splitting to go faster on something small.** Coordination costs more
  than the work.

State your split decision and your reason in one line before acting on it.

## 3. Implement

Follow `AGENTS.md` §2 and §7. The rules broken most often here:

- **Imports flow downward only:** `listeners → handlers → blocks → storage →
  domain → config`. Nothing imports `app`.
- **One lifecycle operation, one implementation.** A button click and an `@p-bot`
  keyword for the same action call the *same* function. If a signature does not fit
  a payload, adapt the payload or extract a shared core — never write a second copy.
- **One writer for the workbook.** Everything goes through `log_writer` via the
  lock queue in `queue_worker`. A direct `openpyxl` save silently destroys the
  workbook's conditional formatting.
- **Roles are Slack IDs, not display names.** An ID can be mentioned, survives a
  profile change, and cannot collide.
- **Every listener acks first.** Slack times out a slash command at 3 seconds.
- **Reply with `respond(...)`**, not `chat_postEphemeral` — that one needs channel
  membership and fails in a DM with the bot.
- **Docstrings explain WHY**, with a `WHY THIS EXISTS` section recording the bug,
  the constraint, or the lab fact that forced the design. When you change
  behaviour, update the reasoning. A stale *why* is worse than none.
- Use `logging.getLogger(__name__)`. Never `print()`.
- **Never touch the production server, the real workbook, or the live roster.**

## 4. Run the full gate locally, before the PR

CI runs these and they fail in this order. Run all three yourself. Do not open a
pull request and let CI find them — that round trip is the main way time gets
wasted here.

```
ruff check .
python scripts/check_tests_first.py
pytest -q --tb=short
```

### Strict test-first and zero-failure enforcement

1. **Tests first.** Written against the acceptance criteria, before or alongside
   the implementation.
2. **Observe the failure and diagnose the root cause.** Read the log. Find what
   actually broke — a wrong payload shape, a missing ack, a fake client that does
   not model the call, a real logic error. Fix the implementation or the harness
   properly. **Never weaken an assertion, never loosen a check without a stated
   reason, never skip or `xfail` a test (ADR 0001).**
3. **100% pass before push.** Run the full suite and confirm **zero** failures
   before pushing any branch or opening any PR. Never assume tests will pass, and
   never push with "the remaining failures look unrelated" — that is a claim, and
   the way to support it is to fix it or escalate it.

## 5. Review your own diff, adversarially

Before the PR, review the change as if looking for the reason it will be reverted.
If you split agents, use a fresh one here: a reviewer that has not just written the
code sees more.

Check, concretely:

- **Every acceptance criterion** — tick them off individually, not in a batch. If
  one cannot be ticked, the ticket is not done.
- **Does it break an invariant in `AGENTS.md` §2?** One lifecycle operation one
  implementation, one writer for the workbook, one store for request state, one
  home for every constant, replies that work everywhere.
- **Do the two surfaces still agree?** If your change touches a lifecycle
  operation, the button and the `@p-bot` keyword must do the same thing. Nothing in
  the suite historically caught a divergence; you have to look.
- **Do the tests actually fail if the behaviour is wrong?** Break the
  implementation deliberately and confirm the test goes red. A test never observed
  failing is not known to work. This is the point of the exercise.
- **Are the tests asserting behaviour or shape?** A test that breaks on a rename
  but not on a wrong Excel column is testing the wrong thing.
- **Did you assert on absence where absence was the point?** That no DM was sent,
  that `chat_update` was not called, that the row is untouched.
- **Did you leave a stale docstring** describing behaviour you just changed?
- **Did you write `submitted` anywhere?** The word is **processed**.

## 6. Land it, or escalate

### Landing the ticket

Once the gate passes and adversarial review is complete:

1. **Update the ticket file**: `Status: done` (exact casing), tick every criterion
   (`- [x]`), and append under `## Comments` a dated summary of what was
   implemented, what the tests cover, and anything verified by hand.
2. **Commit everything to the ticket branch** — code, tests, docstrings, and the
   updated ticket file — so the PR carries the status into `master` on merge.
   Never commit to `master`.
3. **Push**: `git push -u origin <branch-name>`.
4. **Open the PR**:
   ```
   gh pr create --base master --head <branch> --title "<ticket title>" --body "<summary, criteria, gate results>"
   ```
   If `gh` is unavailable, give the URL
   `https://github.com/ilegault/Slackbot/pull/new/<branch>` and output a structured
   PR block ready to paste.

5. **Watch CI.** `gh pr checks --watch --fail-fast`. The ticket is not done until
   the run is green and you saw it go green. If it goes red, work the section
   below — two fix-and-push cycles, then escalate.

**Merging is not deploying.** The bot runs on a separate production server; Isaac
merges and then runs `@p-bot update`. Never report a fix as live.

### Watching CI, and fixing what it finds

**Do not open the pull request and walk away.** The session that wrote the code is
by far the cheapest place to fix it: it still holds the ticket, the ADRs, the diff
and its own reasoning. The same failure found an hour later costs a fresh session
that has to re-read all of that before it can even read the error message.

After pushing the branch and opening the PR:

```
gh pr checks --watch --fail-fast
```

`--watch` blocks until every check resolves; `--fail-fast` returns as soon as one
fails. The gate here is three checks and the suite is small, so a run is
typically a couple of minutes. Wait it out — a slow check is not a reason to stop watching.

If `gh` is not installed or not authenticated, install it (`winget install
GitHub.cli` on Windows, then `gh auth login`). If you genuinely cannot reach it,
**say plainly that CI was not observed.** Never report a run green that you did
not watch resolve.

#### When it goes green

Tick the acceptance criteria individually, set the ticket's `Status:` to `done`,
commit the ticket file, report what landed, and stop. Do not start the next ticket.

#### When it goes red

**Read the failure before theorising about it.**

```
gh run list --branch "$(git branch --show-current)" --limit 1 --json databaseId --jq '.[0].databaseId'
gh run view <run-id> --log-failed
```

`--log-failed` prints only the steps that failed. **Never pull the full run log
into context** — on this repo that is thousands of lines of passing tests, and it
tells you nothing the failed-step output does not.

Then fix and push again, under a budget.

#### The budget: two fix-and-push cycles, then escalate

Not three. Not "one more, I think I have it this time." A third attempt at the same
failure means the diagnosis is wrong, and the cost of being wrong a third time is
higher than the cost of a person spending five minutes on it.

Each cycle is: read the failed-step log, diagnose the **root cause**, fix it, commit
with a message naming what the failure actually was, push, watch again.

#### Classify the failure, and say which you concluded

State your classification in the commit message. A fix whose reasoning is not
written down is indistinguishable from a guess that happened to work.

- **A real defect** — the test is right, the code is wrong. Fix the code. This is
  the test doing its job; it is good news.
- **A harness defect** — the test asserts something the code never promised, or
  models the world wrong (a fake that does not behave like the real thing, a
  fixture that leaks). Fix the test, and say in the commit message why the old
  assertion was wrong. **This is the category an agent under pressure abuses**, so
  the bar is: you can state what the test should have asserted instead, and it
  still fails if the behaviour is wrong.
- **An environment difference** — passes locally, fails in CI. A Python version difference, a missing entry in
  `requirements-dev.txt`, a path separator, a test that reached for a real
  token or a real workbook the runner does not have. Fix
  the cause. "It's environmental" is a diagnosis, not an excuse, and it is never a
  reason to skip or condition the test on CI.

#### The loop makes muting more tempting, not less

You can now watch the build go red and push again thirty seconds later. That is
precisely the situation `docs/adr/0001-tests-first-and-no-muted-failures.md` was
written for. Under time pressure the cheapest-looking move is to edit the test
rather than the code, and it is the one move that is always forbidden: no `xfail`,
no `skip`, no deleted or weakened assertion, no loosened tolerance, no narrowed
input, no `try/except` swallowing the error the test existed to surface.

**If you are editing a test so that it stops reporting a problem you have not
fixed, you are escalating, not fixing.** Stop and escalate.

#### When the budget runs out

Escalate in the four steps — commit the finished work, set the ticket's `Status:`
to `blocked`, append to `## Comments`, convert the PR to a draft
(`gh pr ready --undo`). In the ticket comment, record:

- what CI said, quoted from the failed-step log, not paraphrased
- what you concluded each attempt, and what each attempt changed
- why you think it is still red
- what decision you need from a human

The draft PR plus its failing run **is** the report. Nothing else needs writing,
and nothing goes anywhere a reviewer cannot reach.

#### A red check you did not cause is not yours to fix silently

If `master` is already failing, or a check fails for a reason unrelated to your
diff, say so and do not bury the fix inside your ticket's branch. A refactor with
someone else's bug fix smuggled into it cannot be reviewed.

### Escalation — never mute a test

**A failing test is fixed or escalated, never muted.** No `xfail`, no skips, no
deleted or weakened assertions, no loosened checks, no inputs narrowed until it
passes. Those are all the same move.

**When you cannot fix it, escalate in four steps and stop:**

1. Commit the finished, correct work to the branch. Nothing good is thrown away.
2. Set the ticket's `Status:` to `blocked`.
3. Append under `## Comments`: what you attempted, what failed, and what needs a
   human decision.
4. Commit the ticket update, push, and open the pull request as a **draft**.
   `master` is untouched.

The report goes in the ticket file under `.scratch/`, never under `.claude/` and
never in `Claude outputs/` — both are gitignored, so nothing written there is ever
pushed and no reviewer, human or agent, will see it.

Guessing at a lab decision is not an alternative to escalating. A plausible-looking
answer about who may approve a purchase, or which Excel column a date belongs in,
is worse than no answer, because it will be believed.
