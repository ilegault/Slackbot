# Domain docs

How engineering skills should consume this repo's domain documentation.

## Before exploring, read these

- **`CONTEXT.md`** at the repo root — the vocabulary of P-Bot: the three roles, the
  four stages, decline vs cancel, the surfaces. If a term here and the code
  disagree, flag it; do not silently pick a side. The code currently disagrees with
  the glossary in two known places (`submitted` vs `processed`, and `store.py`), and
  both are recorded rather than hidden.
- **`docs/adr/`** — read the ADRs that touch the area you are about to work in.
  They are binding, not background.

If any of these files do not exist, proceed silently.

## File structure

```
/
├── AGENTS.md          conventions + the ACTIVE-PLAN pointer
├── CLAUDE.md          one line: @AGENTS.md
├── CONTEXT.md         the glossary
├── docs/adr/          binding decisions
├── docs/agents/       how agents work this repo
├── .scratch/          specs and tickets, tracked in git
└── src/
```

## Use the glossary's vocabulary

When your output names a domain concept, use the term as `CONTEXT.md` defines it.
Do not drift to a synonym the glossary explicitly avoids — most of all, never write
*submitted* where the stage is **processed**.

If a concept is not in the glossary: either you are inventing language the lab does
not use (reconsider), or there is a real gap (note it).

## Flag ADR conflicts

If your output contradicts an ADR, surface it explicitly rather than silently
overriding:

> _Contradicts ADR 0003 decision 4 (cancel blanks the row), but worth reopening because…_
