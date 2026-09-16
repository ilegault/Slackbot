# AGENTS.md — orientation for AI sessions working on P-Bot

## Agent skills

### Issue tracker

Issues live as local markdown files under `.scratch/<effort>/`. See `docs/agents/issue-tracker.md`.

### Domain docs

Single-context layout: one `CONTEXT.md` at the repo root, ADRs in `docs/adr/`. See `docs/agents/domain.md`.

P-Bot is the purchasing bot for the **Hirst Lab** (UW–Madison NEEP). It runs in
Slack, walks lab members through a purchase request, gates approval on one
person, tracks the order through four stages, and writes each approved purchase
as a row in `Purchasing-Log.xlsx` on OneDrive.

**Read this before touching code.** Then read the module docstring of whatever
file you are about to edit — this codebase puts its *reasoning* in docstrings,
not in a wiki.

**This bot spends real money and writes to a workbook the lab reads as fact.** A
wrong row in `Purchasing-Log.xlsx` is not a cosmetic bug; someone orders the wrong
thing or nobody orders anything. That is why the conventions here are strict and
why a green test suite that was made green by editing a test is worse than a red one.

---

## 1. Quick facts

| | |
|---|---|
| Language / runtime | Python 3.12+ (dev venv is Windows, `.venv\Scripts\`) |
| Framework | `slack_bolt` in **Socket Mode** — no public HTTP endpoint |
| Entry point | `python app.py` → `src/app.py:main()` |
| Package | `src/` — ~5 500 lines across 12 modules |
| Tests | `pytest` — ~100 test functions in `tests/` |
| Build | `pyinstaller p_bot.spec` (see `docs/EXECUTABLE_BUILD.md`) |
| Deploy target | **A separate production server, not the dev machine.** `@p-bot update` pulls git and restarts. |
| Repo | `master`; remote `origin` = `github.com/ilegault/Slackbot`. CI on push and PR. |

```
# setup
.venv\Scripts\activate
pip install -r requirements-dev.txt

# run the bot (needs .env with SLACK_BOT_TOKEN + SLACK_APP_TOKEN)
python app.py

# run the gate, in the order CI runs it
ruff check .
python scripts/check_tests_first.py
pytest -q
```

**The local repo is not the live bot.** `p_bot.log`, `roster.json` and `dist/` on
the dev machine say nothing about what the production server is doing. Never
diagnose a live problem from a local log file, and never claim a fix is deployed
because the tests pass — deployment is a separate human step.

---

## 2. Layered architecture — the one rule that matters

```
config.py      constants only. Paths, column letters, callback IDs, category maps.
               No Slack, no I/O, no state.
domain         pure functions. Parse, validate, route, draft, decide. Given the
               same input they return the same output, and none of them import
               slack_bolt: epif_parser.py, validators.py, interview.py
storage        the outside world that is not Slack: Excel, OneDrive, JSON files.
               log_writer.py, queue_worker.py, roster.py, path_validator.py
blocks         Block Kit builders. Take a dict, return a list of blocks. They do
               not hold a Slack client and they do not call one.
handlers       one function per lifecycle operation. Takes a client plus channel
               and thread_ts, calls storage, posts the result. This is the only
               layer that knows what "approve" means.
listeners      `@app.command` / `@app.action` / `@app.view` / `@app.event`
               registrations. Ack, extract, permission-check, delegate. Thin.
```

**Imports flow downward only:** `listeners → handlers → blocks → storage → domain → config`.

Today `blocks`, `handlers` and `listeners` are all inside one 2 855-line
`src/app.py`, which is why every open ticket collides with every other one.
Ticket 01 of the current set splits them. Until it lands, treat the section
comments in `app.py` as the layer boundaries and do not move code across one
without saying so.

### Five invariants the whole design rests on

1. **One lifecycle operation, one implementation.** A button click and an
   `@p-bot` keyword for the same action call the *same* function. `handle_claim`
   is the only thing that knows how a claim works; `handle_req_claim_action`
   extracts the payload and calls it. Two implementations of "mark delivered" is
   the failure mode this repo exists to avoid — the two drift, and then the
   button and the keyword write different things to Excel.
2. **One writer for the workbook.** Every write to `Purchasing-Log.xlsx` goes
   through `log_writer` via the lock-retry queue in `queue_worker`. Nothing else
   opens that file. The workbook is routinely open in Excel on somebody's
   desktop; the queue is what turns "locked, try later" into "written" instead of
   "lost". A direct `openpyxl` save also destroys the workbook's x14 conditional
   formatting silently — `log_writer`'s docstring explains why it edits the zip.
3. **One store for request state.** A request's position in the lifecycle lives in
   exactly one place. Today that place is the Block Kit button's `value` on the
   channel message — the message *is* the store, which is why a bot restart
   cannot lose a request's position. **`src/store.py` is not in use: nothing
   imports it.** Do not build on it without an ADR saying it is now the store.
4. **Every constant has one home.** Tunables, column letters, callback IDs and
   role lists live in `config.py` or the roster, never as a literal in a handler.
   `config.GRAD_STUDENT_BUYERS = {"Isaac", "Dylan", "Smeet", "Finn"}` is the live
   violation: a role list hardcoded as display-name strings, which is why buyers
   cannot be @-mentioned and why adding one requires a code edit and a restart.
   Ticket 02 removes it.
5. **Every reply goes out the way that works everywhere.** Slash commands and
   block actions carry a `response_url`; use Bolt's `respond(...)`.
   `chat.postEphemeral` requires the bot to be a member of the channel and fails
   with `channel_not_found` otherwise — including in a DM with the bot. Exactly
   one `chat_postEphemeral` call may remain, on the plain-message-event path
   where there is no `response_url`.

---

## 3. The request lifecycle

There are two ways a request is born and one path it follows afterwards.

```
  /new-purchase  ──► 3-screen interview modal ──┐
  (or App Home button)                          ├──► channel post with buttons
  EPIF PDF dropped in a thread ─────────────────┘         │
                                                          ▼
                         posted ──Approve──► approved ──Claim──► claimed
                                                          │
                     ┌────────────────────────────────────┘
                     ▼
        Mark Processed ──► processed ──Mark Confirmed──► confirmed
                                                          │
                                          Mark Delivered ──► delivered
```

Each state renders **one** next-step button. State, the request payload and the
history lines are serialized into that button's `value`, so the message carries
everything the next click needs.

**Why approval is a keyword and not a pre-existing object.** A purchasing thread
discusses freely — links, quotes, "do we want the 5 mm or the 10 mm" — before
anyone agrees what to order. There is nothing to make a request object *out of*
until Charlie says yes. So `@p-bot approved` (or an Approve button on a request
that was already formalised through the modal) is the moment the object is
created, and the button card appears only after that.

---

## 4. The four stages, and the one word for each

After approval a purchase moves through four stages. **Each has exactly one word,
used everywhere** — in the button label, the action id, the history line, the
help text, the App Home definitions, and the silent `@p-bot` keyword aliases.

| Stage | Means | Excel column |
|---|---|---|
| **approved** | Charlie has agreed to spend the money; the row is written | — |
| **processed** | the request has gone to the purchasing team (Workday / ShopUW) | U, Date Processed |
| **confirmed** | the order is confirmed by the vendor | V, Date Confirmed |
| **delivered** | the package is in the lab | W + X, Date of Delivery / Received By |

**The word is `processed`.** Not "submitted", not "submit", not "ordered". The
code currently says `submitted` in eighteen places and `processed` in one; the
Excel column has always been *Date Processed*. Renaming is part of ticket 05 —
until then, do not add a nineteenth `submitted`, and do not rename them
piecemeal in an unrelated ticket either.

This matters for the same reason ticket status vocabulary matters: a word with
three spellings stops being searchable and stops being teachable.

---

## 5. Where the logic lives

Pure, testable, Slack-free — this is the part that can be checked against a real
EPIF and a real workbook:

| Module | Answers |
|---|---|
| `epif_parser.py` | what is in this EPIF PDF? (AcroForm, 28 named fields — never coordinate scraping) |
| `validators.py` | is this parsed EPIF good enough to log? Returns sentences a grad student can act on |
| `interview.py` | Workday or EPIF path? does this category need asset details? what does the FAQ say? |
| `log_writer.py` | what row does this become, and how is it written without wrecking the workbook? |
| `roster.py` | who is a requester / admin / approver / vendor, and how does an admin change that from Slack? |
| `admin.py` | is this user allowed? plus health, uptime, log tail, git update, restart |
| `queue_worker.py` | the workbook is locked — retry until it isn't, in order, never dropping a write |
| `heartbeat.py` | is the bot alive? dead-man's switch and boot/crash alerts |
| `path_validator.py` | do the OneDrive paths exist at startup, and if not, what do we ask the operator? |
| `config.py` | every lab-specific constant, read off the real blank EPIF and the real workbook |

Keep these Slack-free. A function that takes a Slack client is a handler, not
domain logic, and belongs above this line.

---

## 6. Persistence — what the bot writes

| Path | Written by |
|---|---|
| `Purchasing-Log.xlsx` (OneDrive) | `log_writer` via `queue_worker` — **the only writer** |
| `EPIFs/` | `log_writer.save_epif` |
| `Order-Confirmations/` | `log_writer.save_confirmation` |
| `Quotes/` | `log_writer.save_quote` |
| `roster.json` | `roster.py`, atomic write. Every getter re-reads from disk — **roster changes take effect immediately, no restart** |
| `p_bot.log` | `RotatingFileHandler`, 10 MB × 5 |
| `requests.json` | `store.py` — **nothing calls it.** See invariant 3 |

**Excel is the final reference for the current status of a purchase.** Slack is
where the conversation happens; the workbook is what the lab reads. If the two
disagree, the workbook is what someone acts on.

---

## 7. Conventions to follow

- **Module docstrings explain WHY.** Not what the code does — the reader can see
  that. Record the bug, the constraint, or the lab fact that forced the design.
  `log_writer.py`'s docstring is the model: it explains that openpyxl silently
  destroys the workbook's conditional formatting, which is *why* the file edits
  the zip by hand. Match that style.
- **Every listener acks first.** Slack times out a slash command at 3 seconds.
  `ack()` before any client call, always, no exceptions.
- **Reply with `respond(...)`**, not `chat_postEphemeral`. See invariant 5.
- **Never reimplement a lifecycle operation inside a listener.** If a handler's
  signature does not fit the payload, adapt the payload or extract a shared core.
  See invariant 1.
- **Permission checks name a role, not a person.** `roster.is_buyer(user_id)`,
  `admin.is_approved_reviewer(user_id)`. Approver, admin and buyer are three
  independent roles and must not be conflated: Charlie approves but never buys, a
  grad buyer processes orders but cannot approve, the admin manages the roster.
- **Roles are Slack IDs, not display names.** An ID can be `<@…>` mentioned, is
  stable when someone changes their profile, and cannot collide. A name cannot.
- **Log both ends of every request.** The `log_request` middleware records what
  arrived and what happened; add an explicit success line wherever something
  actually changed — a row appended (row number, requester, item), a file
  archived (path), a modal opened, a stage advanced.
- **Use `logging.getLogger(__name__)`.** Never `print()`.

---

## 8. Testing

- Tests use a **fake Slack client**, not a mock of the function under test. Assert
  on what the bot would have sent — the blocks, the text, the target channel —
  not on internal state.
- **Test behaviour, not shape.** A test that breaks on a rename but not on a wrong
  Excel column is testing the wrong thing. "No slash-command handler calls
  `chat_postEphemeral`" is a good test; "the handler exists" is not.
- Find the real Bolt listener registry when asserting a command is registered.
  Do not monkeypatch something that always passes.
- Nothing in the suite may touch the real `Purchasing-Log.xlsx`, the real
  `roster.json`, or the network. A test once needs to write a workbook: give it a
  temp copy.
- Assert on the *absence* of an action where that is the point — that no DM was
  sent, that `chat_update` was not called, that no alert was posted. A permission
  test that only checks the denial text passes when the action also went through.

---

## 9. Known traps

1. **`src/store.py` is dead.** 184 lines describing itself as the request index
   with multi-item batch mappings and card timestamps, imported by nothing. It
   reads like the store and is not the store. See invariant 3.
2. **`config.GRAD_STUDENT_BUYERS` is a set of display-name strings.** The only
   role in the system that is not a roster concept. It cannot be mentioned and it
   needs a code edit plus a restart to change. Ticket 02.
3. **The dev `roster.json` is not the server's.** It is gitignored, deliberately.
   Never conclude anything about live roles from the local copy.
4. **`chat.postEphemeral` fails in a DM with the bot.** It needs channel
   membership. This produced the `/roster-list` and `/purchasing-help`
   `channel_not_found` failures. Exactly one call site may remain.
5. **The `message` event fires for every message in every channel the bot is in.**
   Log those at DEBUG or skip bot-authored and non-DM messages, or the log file
   becomes unreadable.
6. **`response_url` is good for 30 minutes and 5 uses.** Ample for a reply; not a
   channel for anything long-running.
7. **A buyer needs two roster entries.** Membership in `buyers` gets them past the
   permission check, but the history line ("Claimed by Dylan") comes from
   `resolve_requester()`, which reads `requesters`. A buyer with no `requesters`
   entry falls through to a Slack-profile name guess that silently fails for a
   display name that does not line up.
8. **`master` currently has 16 modified files uncommitted.** Sort that out before
   branching, and check `.gitattributes` is in effect — this repo had no line-ending
   normalisation until now.

---

## 10. Where the prior reasoning is written down

In-repo: `CONTEXT.md` (the glossary), `docs/adr/` (binding decisions),
`docs/agents/multi-tool-setup.md` (why this file exists and what each tool reads),
`docs/MONITORING_AND_QUEUE_SPEC.md`, `docs/SETUP.md`, `docs/BUILD_GUIDE.md`,
`docs/EXECUTABLE_BUILD.md`, `docs/PYTHON_SOURCE_DEPLOYMENT.md`.

In the Claude project "Slack pbot": the running current-state doc and the
lifecycle spec. **That project is not readable by every tool that works this
repo.** Anything an implementer must obey has to be here or in `.scratch/`.

---

## 11. Working agreement for AI sessions

- Read the module docstring before editing the module.
- Run the gate before and after. Tests exist so a refactor can be proved harmless.
- When you change behaviour, update the docstring's reasoning. A stale *why* is
  worse than none.
- New constant → `config.py`. New pure rule → the domain module that owns it. New
  lifecycle operation → a handler, called by both the button and the keyword.
- **Never test against the live workbook, the live roster, or the production server.**

### Fix or escalate — never mute a failing test

Binding rule, from `docs/adr/0001-tests-first-and-no-muted-failures.md` (read it
before touching a failing test): **a failing test is fixed or escalated, never
muted.** That means never marking it `xfail`, never deleting or weakening the
assertion, never loosening a tolerance, and never narrowing its inputs until it
happens to pass. Those are all the same move — making the test stop reporting the
problem instead of fixing the problem.

**When you cannot fix a failing test, stop and escalate. Do not guess at a lab
decision and do not work around it.** The escalation procedure has four steps:

1. **Commit your finished work to the branch.** Whatever is done and correct so
   far is preserved, not lost.
2. **Set the ticket's own `Status:` line to `blocked`.**
3. **Append a comment under the ticket's `## Comments` heading**: what you
   attempted, what failed, and what needs a human decision.
4. **Open the pull request as a draft.** Master is not touched.

The ticket file travels with the branch, so the draft PR plus its failing CI run
*is* the report — a planning session can read the ticket directly off the branch
with no separate handoff. This is also why the report must be written into the
ticket file itself, in `.scratch/`, and **not** anywhere under `.claude/` or in
`Claude outputs/`: those are gitignored, so anything written there never gets
pushed and no reviewer — human or AI — will ever see it.

### Tests-first CI check and documented escape

CI enforces that any pull request or commit modifying application code under
`src/` must also modify tests under `tests/` (`scripts/check_tests_first.py`).
Changes touching only documentation (`docs/`), scripts (`scripts/`), CI
configuration (`.github/`), or tests (`tests/`) pass automatically.

When a change touching `src/` genuinely does not require test additions (a
comment-only clarification, a pure structural move fully covered by existing
tests), declare an explicit and visible escape reason:

- **Commit message or PR text**: include `[no-test-needed: <reason>]`,
  `[tests-exempt: <reason>]`, or `[skip-test-gate]`.
- **PR label**: apply `tests-exempt` or `skip-test-gate`.

The reason is recorded in the PR history and visible during review. Silent
bypassing is not possible.

### Implementing a ticket — the protocol

This repo is worked by more than one agentic tool, and not all of them have slash
commands. Anything an implementer must obey lives here, in this file, because this
file is the only thing every tool reads. A rule that lives only in a command binds
only the tool that has that command.

1. Read the `ACTIVE-PLAN` block below. It names the ticket set and which tickets
   are unblocked. Read the ticket file, and read every ADR it references.
2. **Work the frontier.** Never start a ticket whose `Blocked by:` line names an
   unfinished ticket. If everything unblocked is a human task (a Slack action, a
   server deploy), say so and stop — do not claim it and do not invent work
   around it.
3. Set the ticket's `Status:` line to `in-progress` before you start, and to
   `done` when it lands. Use exactly those words. The status vocabulary is
   `ready-for-agent` / `in-progress` / `done` / `blocked` / `human-task`, and
   nothing else — three spellings of "finished" make the frontier unreadable.
4. One ticket per branch. One pull request per ticket. Never commit to `master`.
5. Run the full gate before you start and before you open the PR:
   `ruff check .`, `python scripts/check_tests_first.py`, `pytest -q`.
   **Zero failures before you push.** Not "the failures look unrelated" — zero.
6. **A failing test is fixed or escalated, never muted.** No `xfail`, no deleted
   or weakened assertions, no loosened tolerances, no narrowed inputs.
   `docs/adr/0001-tests-first-and-no-muted-failures.md` is binding.
7. When you cannot fix a failing test, escalate in four steps: commit the finished
   work to the branch; set `Status:` to `blocked`; append what you attempted, what
   failed, and what needs a human decision under `## Comments`; open the pull
   request as a **draft**.
8. **The escalation report goes in the ticket file, under `.scratch/`.** Never
   under `.claude/` or `Claude outputs/` — both are gitignored.
9. Update the module docstring's reasoning when you change behaviour.
10. **Never touch the production server.** Deploying is a human step: Isaac merges,
    then runs `@p-bot update`. Do not add anything to a ticket that assumes it.
11. **After pushing, watch CI and fix what it finds** — up to two fix-and-push
    cycles, then escalate. See the section directly below; it is binding.

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

<!-- ACTIVE-PLAN:START -->
## Active implementation plan

_Written by the planning model on 2026-09-16. Implement this. If something in it is wrong, say so before changing course._

# Active work: assignment replaces claim

This is a **pointer**, not the work. The work is a ticket set.

- Spec: `.scratch/lifecycle-and-buyers/spec.md` (lifecycle rebuild; its claim
  sections are superseded by ADR 0004)
- Binding on all test work: `docs/adr/0001-tests-first-and-no-muted-failures.md`
- Read before any lifecycle ticket: `docs/adr/0002-request-lifecycle-and-surfaces.md`
- **Read before ticket 08: `docs/adr/0004-assignment-replaces-claim.md`** — it
  supersedes 0002 decision 6
- Glossary: `CONTEXT.md`
- Tickets: `.scratch/lifecycle-and-buyers/issues/01…11`
- Tracker conventions: `docs/agents/issue-tracker.md`

**Tickets 01 through 09 are all `done`.** The lifecycle rebuild shipped: layers
split, buyers on the roster, claim, buttons on the PDF-drop path, decline/cancel
plus the `processed` rename, regression guards, lint gate — then assignment
replaced claim, and App Home and the help text were refreshed from one source.

## Next up — ticket 11

**11 — Mirror the roster into the workbook.** `roster.json` becomes the source of
truth for the `Requester Name` and `Grad Student` lists on the workbook's
`Roles & Lists` tab; adding a requester or a buyer appends them to the sheet, so
the Order Log dropdown stops drifting away from the roster. Append-only, through
`log_writer` and the queue — invariant 2, no exceptions.

The two lists were reconciled by hand and the tab was given room to grow on
2026-09-16. The ticket's **"Starting state"** section records exactly what the
sheet looks like now — the table refs, which rows already exist with their
styles, and the row-50 floor. Build against it; do not redo it.

It also closes a second copy of the same drift: `/roster-set-name` validates
against `config.VALID_REQUESTERS`, a hardcoded set that still lists `Charlie H.`
and `Copeland` and is missing `Hansel` and `Zehui` — two people already in
`roster.json` whom the registration modal currently refuses.

**10 is a `human-task`:** seeding the buyers roster. An agent must not claim it.
Note `roster.json` currently holds three buyers (Isaac, Smeet, Dylan), not the
four ticket 10 names — **Finn is still missing**, which is also why he is no
longer in the sheet's Grad Student list.

## Dependency order

```
01…09 (done) ── 11
             └─ 10 (human-task, after deploy)
```

## Rules for working this set

- Do not start a ticket whose `Blocked by:` line names an unfinished ticket.
- A failing test is fixed or escalated, never muted. The escalation path — commit
  to branch, ticket `Status: blocked`, comment on the ticket, draft PR — is ADR
  0001 decision 3, and the report goes in the ticket file under `.scratch/`.

## Five requirements that will be quietly violated if read as preferences

1. **A refused assignment never refuses the approval.** If Charlie names nobody,
   names two people, names a non-buyer, or names someone with no `requesters`
   entry, the rows are still written, the EPIFs still archived, the card still
   posted. The request simply stays unassigned. Approval is the money decision;
   a missing mention must never cost one.
2. **Never take the first of several mentions.** Two names is a question to ask,
   not a tie to break.
3. **A button handler never reimplements a lifecycle operation.** It acks,
   extracts, permission-checks, and calls the same handler the keyword branch
   calls. If a signature does not fit, adapt the payload or extract a shared core
   — never write a second copy.
4. **Roles are Slack IDs.** `is_buyer` takes an ID. Do not add a name-based
   variant "for convenience".
5. **Mentions are stripped before keywords are matched.** A lowercased Slack ID is
   alphanumeric and can contain `log`, `take` or `submit`. Match on the stripped
   text, always.

## One thing this set deliberately does not do

It does not teach the bot the purchasing rotation. The bot models **a name chosen
by a person who knows the rotation** — not the rotation itself, not a default
buyer, not a round-robin. If that turns out to be wrong, it is a new ADR, not a
constant added to `config`.
<!-- ACTIVE-PLAN:END -->
