# ADR 0005 — Assignment can be a button; the mention is no longer the only way

**Status:** accepted
**Date:** 2026-09-16
**Amends:** ADR 0004 decision 1 (the reasoning, not the rule)

## Context

ADR 0004 decided that the approver names the buyer by `@`-mentioning them in the
approval message, and `CONTEXT.md` recorded the reason as:

> **Assigning is not a button** — a button cannot carry a person, and the mention
> already does.

**The premise is false.** Slack's `users_select` element carries a person. It was
false when 0004 was written; nobody checked, because the thread path — where
Charlie types `@Dylan @Purchasing approved` — genuinely has no surface to put a
picker on, and that path was the one under discussion.

The `/new-purchase` modal path does have a surface. It posts a card with an
Approve button on it, and today that card offers **no way to name a buyer at all**.
Charlie clicks Approve and the request lands unassigned every time, with no hint
that assigning is even possible. The mention rule from 0004 still works there, but
only if he already knows to type it, in a thread the bot posted, under a card whose
only affordance is a button.

Two paths, two different right answers. 0004 generalised from one of them.

## Decision

### 1. The posted card carries a buyer picker

`build_request_blocks("posted", …)` renders a `users_select` beside Approve. The
selection rides in the approval payload and becomes the assignee, on exactly the
same terms as a mention: the person must already be on the buyers roster, and a
refused assignment never refuses the approval (ADR 0004 decision 2 is unchanged and
binding).

### 2. Picking is optional, and skipping it is not an error

No selection means the request is approved and **unassigned** — a real state, not a
failure. The bot posts the same thread line it posts today asking for a buyer, and
`@Purchasing assign @buyer` still works. Nothing about the unassigned state changes.

### 3. The mention rule is unchanged everywhere it already applies

ADR 0004 decision 1 stands verbatim for the thread path and for `assign`. This ADR
adds a second input to the same operation; it does not replace the first. Both
resolve to the one assignment function — invariant 1, no second implementation.

### 4. If both are supplied, the mention wins

Charlie can pick a buyer *and* type a mention. The mention is the more deliberate
act — he typed a name rather than accepting a dropdown — so it takes precedence,
and the bot says which one it used rather than silently choosing.

## Consequences

`CONTEXT.md`'s **Button** entry loses "assigning is not a button" and gains the
real rule: assignment has two inputs, a picker where there is a card and a mention
everywhere. The interface rule in ADR 0002 is untouched — assignment needs a
target, the card *is* the target, and this is the rule being followed rather than
bent.

The general lesson is the one worth keeping: **0004's rule was right and its stated
reason was wrong.** A reason nobody verified became a design constraint that
outlived the situation it was observed in. When an ADR explains a decision by
asserting a platform limit, the limit gets checked.
