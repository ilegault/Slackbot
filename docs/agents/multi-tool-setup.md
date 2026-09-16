# Running the same procedure from Claude Code and Google Antigravity

## The problem

P-Bot is planned in one tool and implemented in another. Planning happens in
Cowork / Claude Code with a strong model; implementation is handed to a cheaper,
faster agent — Claude Code remote, or Antigravity.

That only works if the implementing agent can *see* the procedure. Before this
setup, it could not. The working procedure lived in three places, and Antigravity
read none of them:

1. The conventions — which existed only in a planning conversation.
2. Claude Code skills — procedure encoded as commands, which Antigravity cannot run.
3. The tickets — which lived in `Claude outputs/`, untracked, and in the Cowork
   project, which no coding tool can read at all.

Point Antigravity at this repo in that state and it sees 5 500 lines of Python and
nothing else. Every rule is invisible to it, including *a failing test is fixed or
escalated, never muted*.

## What each tool actually reads

| | Claude Code | Antigravity |
|---|---|---|
| `CLAUDE.md` | yes | **no** |
| `AGENTS.md` | **no** (but see below) | yes |
| `GEMINI.md` | no | yes, and it **overrides** `AGENTS.md` |
| `.agent/rules/` | no | yes, as a supplement |
| Nested `AGENTS.md` in subfolders | n/a | yes, if enabled in Settings → Agent |
| The Cowork project | no | no |

Claude Code does not read `AGENTS.md` directly, but it supports an **import**
syntax: a line reading `@AGENTS.md` in `CLAUDE.md` pulls that file's contents in.
That import is the hinge this whole setup turns on.

> Sourcing note: the Claude Code side is documented behaviour. The Antigravity
> specifics come from community documentation rather than a first-party reference,
> so verify the nested-file setting and the `GEMINI.md` precedence on your install
> before relying on either.

## The setup

**One authored file, read by both tools. No copies, no generation step.**

- **`AGENTS.md`** is the canonical conventions file. It holds the layering rule,
  the invariants, the traps, the implementation protocol, and the `ACTIVE-PLAN`
  block naming the current ticket set.
- **`CLAUDE.md`** contains exactly one line: `@AGENTS.md`. Nothing else belongs in
  it. Any second line is a line Antigravity cannot see.
- **`.scratch/`** holds the tickets and is **tracked in git**, so a ticket file
  travels with its branch and a draft PR is a complete handoff.
- **`.agents/skills/pbot-ticket/SKILL.md`** is the implement-one-ticket procedure
  for tools that load skills. Everything binding in it is *also* in `AGENTS.md`,
  because a rule that lives only in a skill binds only the tool that runs skills.
- **`.claude/scripts/set_plan.py`** writes the `ACTIVE-PLAN` block into
  `AGENTS.md` and archives the plan under `.claude/plans/`.

### The division of labour

- **Planning — Cowork / Claude Code.** Grill the design, write the spec, break it
  into tickets, set the `ACTIVE-PLAN` pointer, write the ADR.
- **Implementation — either tool.** Both read `AGENTS.md`, both can read a ticket
  file, both can run `pytest`.
- **Review — either tool**, since the review checklist is in `AGENTS.md` and in
  the skill rather than only in a slash command.

The consequence, and the rule that follows from it: **anything an implementing
agent must obey has to be in `AGENTS.md`, not in a skill.** When you add a rule,
add it there first.

## Traps

**Do not create a `GEMINI.md`.** It takes priority over `AGENTS.md` in Antigravity
and is invisible to Claude Code. A `GEMINI.md` with real content recreates exactly
the split this setup removes, and it wins silently.

**Do not put anything in `CLAUDE.md` except the import line.** The moment a second
line appears, the two tools are reading different instructions again.

**Do not write a plan or a ticket into `Claude outputs/` or `.claude/`.** Both are
gitignored. Anything there is invisible to the implementing agent, invisible to
CI, and invisible to every reviewer. This is the failure the whole setup exists to
fix, and it is easy to recreate by habit.

**Do not treat the Cowork project as the source of truth for implementation.** It
is an excellent place to think and a useless place to instruct from. The repo is
what the implementing agent sees.

**Nested `AGENTS.md` files are off by default.** If you add one under `src/`, turn
on Settings → Agent → Load nested AGENTS.md files, and remember Claude Code will
not see it at all unless it is also imported.

**Keep the ticket status vocabulary to the five words** in
`docs/agents/issue-tracker.md`. Three spellings of "finished" make the frontier
unreadable by whichever tool opens the repo next.

## Verifying it worked

1. Start a Claude Code session and ask what the active plan is. It should name the
   `lifecycle-and-buyers` set and ticket 01. If it does not, the `@AGENTS.md`
   import is not resolving.
2. Start an Antigravity session and ask the same question. Same answer expected.
3. Ask both: "what happens when a test fails and you cannot fix it?" Both should
   describe the four-step escalation — commit, `Status: blocked`, comment on the
   ticket, draft PR. If Antigravity does not, the implementation protocol in
   `AGENTS.md` §11 is missing or buried too deep.
4. Ask both: "what is the word for the stage after approved?" Both should say
   **processed**, not *submitted*.
5. Run `set_plan.py` once and confirm it wrote into `AGENTS.md` between the
   `ACTIVE-PLAN` markers and archived a copy under `.claude/plans/`.
