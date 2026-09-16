# ADR 0004 — The approver names the buyer; assignment replaces claim

**Status:** accepted
**Date:** 2026-09-16
**Supersedes:** ADR 0002 decision 6 (every approved request waits for a claim)

## Context

ADR 0002 decision 6 made every approved request wait for a **claim**: the bot
broadcast to all buyers and a buyer took the order by clicking a button. The
reasoning was that purchasing duty rotates between grad students and *the bot does
not know whose turn it is*, so it must not auto-assign.

That reasoning was sound and the conclusion was wrong, for one reason that was not
on the table when 0002 was written: **the approver knows whose turn it is.**
Charlie set the rotation up. Asking the bot to stay ignorant of it, and then asking
four grad students to watch a channel and race for a button, moves work that one
person already knows how to do onto four people who have to coordinate to do it.

Charlie asked for this directly, and he already types it by hand:

```
@Dylan Kohler @Purchasing Approved
@Purchasing Approved @Dylan Kohler
```

Nothing is lost in the switch. Claim shipped in ticket 03 but has never worked in
production: `roster.json` ships `"buyers": []`, so the gate refused everyone, and
the deploy that would have carried it never landed. There are no live cards with a
Claim button on them and nothing to migrate.

## Decision

### 1. The approver names the buyer in the approval message

One rule, stated once: **strip the bot's own user ID from the message text, then
count the remaining `<@U…>` mentions.**

| Remaining mentions | Meaning |
|---|---|
| exactly one | that person is the assignee |
| zero | the request is approved and **unassigned** |
| two or more | refuse the assignment, ask which one — never pick the first |
| a user group (`<!subteam^…>`) | refuse: name a person, not a group |

Position is not part of the rule. Charlie writes the mention before or after the
keyword depending on the sentence, and both of his examples are correct input.

### 2. A missing name never costs an approval

Approval is the money decision and the Excel write. If Charlie names nobody, the
rows are written, the EPIFs are archived, the card is posted, and the request sits
in the **unassigned** state with a thread line asking him to @ a buyer.

Refusing to log a valid, approved EPIF because of a missing mention would recreate
in a new place exactly the class of failure this rebuild exists to remove: a
correct purchase that silently does not reach the workbook.

### 3. Who may assign depends on whether it is already assigned

| State | Who may set the assignee |
|---|---|
| unassigned | any buyer, an approver, or an admin — including a buyer naming themselves |
| assigned | an approver, an admin, or the current assignee |

The first row is what keeps Charlie from being a bottleneck: he approves, forgets
to name anyone, and flies to a conference, and the order still moves. The second
stops a buyer quietly taking an order that is already someone's job — a handoff is
a thing the two of them, or Charlie, do on purpose.

### 4. The named person must be on the buyers roster

A name that is not on `roster.get_buyers()` is **refused, and the approval stands**
— the request stays unassigned and the thread says who to add and how.

This gate is not about security. It is about `resolve_requester()`: the history
line, the email-draft signature and the delivered-by column all read the
`requesters` map, and a person who is not in it falls through to a Slack-profile
name guess that writes a subtly wrong name into the workbook. Gating on the roster
answers "is this person set up" once, when an admin adds them, instead of silently
at every approval.

**Consequence: seeding the buyers list is a deploy blocker**, not a follow-up.

### 5. The word is `assigned`, and `claim` is deleted

`assigned` / `assignee` / `unassigned`, everywhere: the keyword, the history line,
the card, the help text, the App Home definitions, the log lines. `claim`,
`claimed`, `claiming`, `take`, `i will order` and `i'll order` join the deleted
aliases in ADR 0002 decision 4. An approver cannot *claim* something on someone
else's behalf; the word only ever described self-selection, which is no longer the
mechanism.

### 6. The email draft goes to the assignee, at assignment

Unchanged in substance from ADR 0002 decision 6 — the draft is signed by whoever
emails purchasing, so it is addressed to the assignee, not the requester. What
changes is *when*: normally at approval, because that is when the name arrives.
A reassignment re-sends it to the new assignee. An unassigned request sends no
draft until someone is named.

### 7. Assignment is not recorded in the workbook

No new column. The workbook records the four stages; responsibility lives on the
card and in the thread. Adding a column moves every formula range and every
`build_row` offset in a file that is open on somebody's desktop most of the day,
for a fact that is one glance away in Slack. If Charlie later wants owners visible
in the log, that is a deliberate schema change and its own ADR.

### 8. Mentions are stripped before keyword dispatch

`dispatch_command` matches keywords by substring against the whole message text.
Now that user mentions are meaningful input, the raw `<@U…>` token must be removed
*before* matching, not after: a Slack ID is alphanumeric, and a lowercased ID
containing `log`, `take` or `submit` would otherwise route an assignment into the
ops handlers. Strip mentions first, match on what is left.

## Consequences

- `req_claim`, `CLAIM_KEYWORDS`, `handle_claim` and the `claimed` card state are
  deleted outright. No shim, no compatibility handler — there is no live card
  carrying that button.
- The `claimed` state disappears from `build_request_blocks`. `approved` now
  carries `Mark Processed` directly, and the card text names the assignee or says
  the request is unassigned.
- `roster.buyers` keeps its meaning but changes its job: it is the set of people
  who may be *named*, not the set of people who may grab.
- Charlie now has one more thing to remember at approval time. Decision 2 and
  decision 3 are the two independent ways that forgetting it stays cheap.
- The bot still does not model the rotation. It models a name chosen by a person
  who knows the rotation — which is the part ADR 0002 got right and this ADR keeps.
