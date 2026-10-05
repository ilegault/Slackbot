# ADR 0013 — A nudge per stage, set from App Home, and an expected delivery date

**Status:** accepted
**Date:** 2026-10-05
**Amends:** ADR 0011 decision 4 (the nudge schedule), ADR 0011 decision 3 (the request
log now starts at posting), ADR 0010 decision 4 (the requester may mark Delivered).

## Context

The nudge covers one wait — approved but not processed — on a hardcoded 3 / 6 / every-3
working-day schedule, and App Home does not mention it. The lab wants every stage
tracked, including whether things have shown up, but the waits are very different:
a processing nudge every 3 days is right, a delivery nudge every 3 days is noise when
parts take months. Changing anything today means editing code, and the server's `.env`
needs someone physically at it.

## Decision

### 1. Four nudges, named for the stage they wait on

| Nudge | Waits on | Goes to |
|---|---|---|
| approved | a posted card nobody has approved | the approvers |
| processed | approved, not processed | the assigned buyer |
| confirmed | processed, not confirmed | the assigned buyer |
| delivered | confirmed, not delivered | the assigned buyer **and** the requester |

### 2. One setting per nudge: on/off, every N working days, by DM and/or channel

The first nudge comes N working days after the request entered its current stage
(posting; approval or reassignment; Date Processed; Date Confirmed), then every N.
"Channel" means a thread reply also sent to the channel. No escalation step, no
"stop after", no snooze — a long N is the answer for slow stages. For an unassigned
request, "DM" is one thread line @-mentioning all buyers, repeating every N until
someone is assigned. The run stays fixed at weekdays 9:00. A settings change applies
to requests already open from the next run.

Shipped defaults: approved **off**; processed every 3, DM; confirmed every 5, DM;
delivered every 10, channel.

### 3. Settings are edited from App Home

Admins see an **Edit nudge settings** button on App Home that opens a form. Settings
live in their own file beside the roster, not in `roster.json` or `requests.json`.
Everyone sees a **Nudges** section on App Home (and in `/purchasing-help`) built from
the live settings, so the text cannot drift from what the bot does.

### 4. What a nudge carries

Processed and confirmed: the buyer's DM card is re-posted with its next-step button
(the processed one also with the buyer picker) and the old one retired, as today.
Approved: a link to the thread card only. Delivered: a **nudge card** with
**Delivered** and **Not yet — set expected date**; a newer nudge card retires the
older one.

### 5. Expected delivery

"Not yet" — or an optional **Set expected delivery** button on a Confirmed card —
opens a form with one date picker. Past dates are refused. The bot posts "Expected
delivery <date> — I'll check back then", pauses delivered nudges until that date (next
weekday 9:00 if it falls on a weekend), then resumes every N. The buyer, requester, an
admin or an approver may set it, any number of times; each change is a thread line and
a history line. It is shown on the thread and DM cards and kept in the request log,
with no workbook column.

### 6. The requester may mark Delivered

The person who sees the package arrive is usually the requester. They may press
Delivered — and only Delivered — on the thread card or the nudge card.

### 7. Posted cards enter the request log

So the approved nudge can find them. An entry ends being nudged when its card is
approved, declined or superseded. Requests posted before this ships are not backfilled.

## Consequences

- Today's day-6 channel escalation for the processed nudge goes away unless an admin
  turns "channel" on.
- The request log holds unapproved requests too; anything reading it must not assume
  every entry was approved.
