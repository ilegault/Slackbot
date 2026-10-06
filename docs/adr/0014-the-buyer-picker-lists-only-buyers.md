# ADR 0014 — The buyer picker lists only buyers

**Status:** accepted
**Date:** 2026-10-05
**Amends:** ADR 0005 decision 1 and ADR 0011 decision 2 (the kind of dropdown, not where it
appears or what picking does).

## Context

The buyer picker on the posted card, the approved card and the DM card is a Slack
`users_select`. That element always lists every person in the workspace and cannot be
filtered. Picking anyone who is not a buyer is refused after the fact (ADR 0005 decision 1),
so the dropdown offers dozens of names that can only produce a refusal, and the four people
who can actually be picked are buried among them.

## Decision

### 1. The picker is a dropdown the bot fills with buyers

Each picker becomes a `static_select`. Its options are the people on the roster's `buyers`
list **who also have a roster name** — a buyer with no name is refused by the assignment
function anyway, so offering them only leads to a refusal. Each option shows the roster name
and carries the Slack ID as its value. Options are sorted by name, ignoring case. The
`action_id`s and placeholder texts do not change.

### 2. The list is filled when the card is drawn

The options are read from the roster every time the bot posts or redraws a card. There is no
live lookup when someone opens the dropdown (Slack's `external_select`), because that needs a
Slack app setting changed and a new handler for a list of a handful of people.

Accepted cost: a buyer added after a card was drawn does not appear on that card until it is
next redrawn (any button press or assignment on it redraws it). The typed keyword
`@Purchasing assign @buyer` covers the gap.

### 3. The current buyer is pre-selected only if they are still in the list

When the request has an assignee who is in the options, that option is pre-selected. When the
assignee has since left the buyers list (or lost their name), nothing is pre-selected and the
placeholder shows — Slack rejects a whole message whose pre-selected option is not one of the
options.

### 4. No buyers, no picker

If no buyer has a name, the picker is left off the card. Slack rejects a dropdown with no
options, and a card that fails to post is worse than a card without a picker.

### 5. Cards already in Slack keep working

Cards posted before this change still carry the old person-picker until they are redrawn. The
two selection handlers accept both shapes: the old one's picked person and the new one's
picked option. The roster check in the assignment function stays: it is what refuses an old
card's non-buyer pick and a non-buyer `@`-mention.

## Consequences

`CONTEXT.md`'s **Button** entry names the picker as a buyers-only dropdown, and the glossary
gains **Buyer picker**. Assignment still has two inputs and one assignment function
(ADR 0005 decisions 3–4 unchanged).
