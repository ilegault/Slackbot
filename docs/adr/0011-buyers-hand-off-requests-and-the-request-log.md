# ADR 0011 — Any buyer can hand off a request until it is processed; a request log lets the bot nudge

**Status:** accepted
**Date:** 2026-09-30
**Amends:** ADR 0004 decision 3 (who may change the assignee). ADR 0002 decision 3
(the message is the store) and ADR 0010 decisions 2–4 stand: the thread card is still
authoritative for a request's live state.

## Context

Charlie names a buyer at approval, and after that the buyer is effectively cemented:
the approved card shows only Mark Processed and Cancel. Reassigning exists, but only as
a typed `@Purchasing assign @buyer` that nobody is taught, and only the assignee, an
approver or an admin may do it. Dylan raised the real case: a grad student leaves on
vacation holding assigned orders, another buyer could place them, and nothing lets
that happen without chasing Charlie.

Separately, orders stall silently. The bot only acts when poked, so nothing notices
an approved request that no one has processed. A timer cannot fix this on its own: the
workbook knows a row is unprocessed and how old it is, but not who the buyer is or
which thread the request lives in — that lives only on the Slack card.

## Decision

### 1. Any buyer may move a request between buyers, until it is Processed

Replaces the table in ADR 0004 decision 3. Before Processed, **any buyer, approver or
admin** may set or change the assignee, including a buyer naming themselves. From
Processed on, the assignee is fixed and a change is refused in-thread, naming who
processed it. The stage-button rule (ADR 0010 decision 4) is unchanged: moving a request
is open to buyers; marking stages on someone else's request is not.

The protection ADR 0004 wanted — no *quiet* takeover — is kept by notification rather
than permission: every change DMs the old buyer who has it now and who moved it, and
the new buyer gets the email draft and a fresh DM card as today.

### 2. The buyer picker lives on the approved card and on the DM card

Both show a buyer picker until Processed ("Assign a buyer" when unassigned, the current
buyer otherwise). Both go through the one assignment function and keep the two cards in
sync (ADR 0010 decision 3). The typed keyword keeps working.

### 3. A request log beside the cards

`requests.json`, next to `roster.json` and gitignored, kept by `src/store.py`. At every
event — approve, assign, reassign, processed, confirmed, delivered, cancel — the bot
appends a history line and keeps the request's thread, card and current buyer. It never
holds a stage: stage still comes from the workbook. Cards do **not** read from it; it
sits beside them. Finished requests are kept as history. Requests approved before this
ships are not backfilled.

Rejected: an Assigned Buyer workbook column (reopens a settled decision and edits a
workbook whose columns A and Z are formulas); keeping the buyer inside `roster.json`
(the roster would grow forever); rendering cards from the log (rewrites every handler).

### 4. The nudge

Weekdays at 9:00 Central, the bot checks every logged request not yet Processed. The
clock starts at approval and restarts on a reassignment; it counts working days
(Mon–Fri).

| Working days | Assigned | Unassigned |
|---|---|---|
| 3 | private DM to the buyer | thread line @-mentioning all buyers |
| 6 | DM, plus a thread reply also sent to the channel @-mentioning the buyer | the same line, also sent to the channel |
| 9, 12, … | DM only | nothing further |

The DM carries Mark Processed and the buyer picker. A missed 9:00 (server down) runs
once on the next start-up that day.

## Consequences

- An order no longer depends on one person being around, and a stalled one surfaces on
  its own.
- Two histories exist — the card's and the log's — written at the same events. The card
  is what people see; the log is what the timer reads. If they ever differ, the card is
  right about the request and the workbook is right about the stage.
