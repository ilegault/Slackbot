# 10: Seed the buyers roster with real Slack member IDs

**What to build:** Nothing. A person has to do this in Slack.

**Blocked by:** 08 (deploy it first, then seed)

**Status:** human-task done

## Why

`roster.json` ships with `"buyers": []`. After ticket 08, the buyers list is the
gate on **who Charlie is allowed to name** (ADR 0004 decision 4) — so on an empty
list, every assignment Charlie tries is refused and every approved request lands
unassigned. Ticket 08 is not usable in production until this is done.

Each buyer needs **two** roster entries, for the reason recorded in ADR 0004
decision 4: `buyers` gets them past the gate, and `requesters` is where the name on
the card, the email-draft signature and the delivered-by column come from. A buyer
missing from `requesters` is refused with the `/roster-set-name` message.

## Steps

1. Collect the Slack member IDs for Finn, Smeet and Dylan (Slack profile → More →
   Copy member ID). Isaac is already in `requesters`.
2. In the purchasing channel, as an admin:
   `@Purchasing add-buyer @Finn`, `@Purchasing add-buyer @Smeet`,
   `@Purchasing add-buyer @Dylan`, `@Purchasing add-buyer @Isaac`
3. Have each of them run `/roster-set-name` so their `requesters` name matches the
   workbook's dropdown exactly.
4. Verify with `/roster-list`, then approve one real request naming a buyer and
   confirm they get the email-draft DM.

## Acceptance criteria

- [ ] All four buyers appear in `roster.json` `buyers`
- [ ] All four appear in `requesters` with a name that matches the Purchasing Log's
      Requester dropdown exactly
- [ ] One end-to-end approval names a buyer and that buyer receives the draft DM
