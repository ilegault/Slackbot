# Spec — Buyers hand off requests, a request log, and the nudge

**Status:** ready-for-agent
**Binding:** `docs/adr/0011-buyers-hand-off-requests-and-the-request-log.md`,
`docs/adr/0010-linked-cards-and-direct-message-help.md`,
`docs/adr/0004-assignment-replaces-claim.md` (decision 3 amended by 0011),
`docs/adr/0001-tests-first-and-no-muted-failures.md`
**Glossary:** `CONTEXT.md` — **Buyer**, **Unassigned** (updated), **Nudge**,
**The request log** (new; replaces the old "The store" entry)
**Builds on:** `.scratch/dm-help-and-linked-cards/` (DM card, both cards move together).

## Problem Statement

Once the approver names a buyer, the approved card shows only Mark Processed and
Cancel. The buyer is effectively locked in. Reassigning exists only as a typed
keyword nobody is taught, and only the assignee, an approver or an admin may use it.
When a grad student goes on vacation holding assigned orders, another buyer who could
place them has no way to take them over without chasing the approver.

Separately, orders stall silently. The bot acts only when someone pokes it, so an
approved request that nobody processes sits there with no reminder to anyone. The bot
cannot even find these on its own: the workbook knows a row is unprocessed and how old
it is, but not who the buyer is or which thread the request lives in. That is known
only to the Slack card.

## Solution

- **Hand-off.** Every approved card, both the thread card and the assigned buyer's DM
  card, carries a buyer picker until the request is **Processed**. Any buyer, approver
  or admin can use it to assign or move the request. The old buyer is told by DM who
  has it now and who moved it. The new buyer gets the email draft and a fresh DM card as
  today. After Processed the picker is gone and a typed `assign` is refused.
- **Request log.** A new file, `requests.json`, next to the roster, records every
  approved request: its thread, its card, its current buyer and a history line for every
  event. Cards keep working exactly as they do now; the log sits beside them.
- **Nudge.** Every weekday at 9:00 Central the bot looks through the log for requests not
  yet Processed and reminds people on a fixed schedule counted in working days:
  - **Assigned:** day 3 a private DM to the buyer; day 6 a DM plus one reply sent to the
    channel; then a DM every 3 working days.
  - **Unassigned:** day 3 a thread line to all buyers; day 6 the same line sent to the
    channel; then nothing.

## User Stories

### Hand-off

1. As a buyer about to leave on vacation, I want to move my assigned request to another buyer from my DM card, so that the order still gets placed while I'm away.
2. As a buyer, I want to move a request assigned to someone else onto myself, so that I can place an order a colleague can't get to.
3. As a buyer, I want to move a request from one buyer to a third buyer, so that the right person handles it even if neither of us is the original assignee.
4. As the approver, I want a buyer picker on the approved thread card, so that I can change who handles a request without learning a keyword.
5. As an admin, I want the same picker to work for me, so that I can fix assignments when nobody else is around.
6. As the approver, I want an approved request with nobody assigned to show a picker labelled "Assign a buyer", so that anyone can pick it up from the card.
7. As any viewer, I want the picker on an assigned request to show the current buyer, so that I can see at a glance who has it.
8. As the old buyer, I want a DM telling me the request was moved, who has it now and who moved it, so that I know I no longer need to act.
9. As the new buyer, I want the email draft and a DM card with the next-stage button, so that I have everything I need to place the order.
10. As the old buyer, I want my old DM card retired with no buttons, so that I can't accidentally advance a request that's no longer mine.
11. As anyone reading the thread, I want one history line and one thread line saying who reassigned it to whom, so that the thread records the hand-off.
12. As a buyer, I want the thread card and my DM card to show the same buyer after any change from either card, so that the two never disagree.
13. As the approver, I want the picker to disappear once a request is Processed, so that nobody moves an order that's already gone to purchasing.
14. As someone who types `@Purchasing assign @buyer` on a Processed request, I want a clear refusal naming who processed it, so that I know why nothing changed.
15. As any user, I want picking a person who isn't on the buyers list to be refused with the existing "isn't on the buyers list" message, so that only buyers get orders.
16. As a lab member who isn't a buyer, approver or admin, I want my picker selection refused privately, so that only people with purchasing duty can move orders.
17. As a buyer, I want moving a request to still NOT let me click Mark Processed on a request assigned to someone else, so that stage marking stays with the assignee, approver or admin.
18. As a user, I want picking the person who is already assigned to do nothing and send no DMs, so that a mis-click doesn't spam anyone.

### Request log

19. As the bot operator, I want every approval to create an entry in `requests.json` with the thread, card, buyer (if any) and an "approved" history line, so that the bot can find the request later without a person pointing at it.
20. As the bot operator, I want every assign and reassign to update the entry's current buyer, record when the buyer was set, and append a history line, so that the log knows who has it now.
21. As the bot operator, I want every Processed, Confirmed, Delivered and Cancel to append a history line, so that the log is a full history of each request.
22. As the bot operator, I want the log file separate from `roster.json`, so that the roster doesn't grow with every order.
23. As the bot operator, I want finished (delivered or cancelled) requests kept in the log, so that the history survives.
24. As the bot operator, I want the log never to hold a stage, so that the workbook stays the one source for what stage a request is at.
25. As the bot operator, I want a failure to write the log to be logged and alerted to the admin channel without breaking the approval, button or DM, so that a log problem never stops a purchase.
26. As the bot operator, I want a corrupt log file to be kept aside as `.bad` and alerted, not silently discarded, so that no request history is lost.

### Nudge

27. As an assigned buyer, I want a private DM 3 working days after approval if I haven't marked it Processed, so that I'm reminded without being called out.
28. As an assigned buyer, I want that DM to carry Mark Processed and the buyer picker, so that I can either confirm I've done it or hand it off in one click.
29. As an assigned buyer, I want the nudge to re-post my DM card (retiring the old one) rather than add a third card, so that there are still only two cards to keep in sync.
30. As the approver, I want a thread reply that is also sent to the channel at 6 working days, @-mentioning the buyer, so that a stuck order becomes visible to the lab.
31. As an assigned buyer, I want DMs every 3 working days after that (9, 12, …) but no more channel posts, so that the reminder continues without public repetition.
32. As a buyer who just received a reassigned request, I want the clock to restart from the reassignment, so that I'm not nudged the next morning for someone else's delay.
33. As a buyer, I want nudges to stop once a request is Processed, cancelled or reassigned away from me, so that I'm never reminded about something that's done or no longer mine.
34. As the lab, I want an unassigned request that is 3 working days old to get a thread line @-mentioning all buyers, so that someone picks it up.
35. As the lab, I want the same unassigned line sent to the channel at day 6 and then nothing further, so that an orphaned request surfaces once without endless pings.
36. As a buyer, I want weekends not to count and no nudges sent on Saturday or Sunday, so that the timing matches working days.
37. As the bot operator, I want Processed to be read from the workbook's Date Processed column at nudge time, so that a date typed into Excel by hand stops the nudges too.
38. As the bot operator, I want requests approved before this update to be ignored by the nudge, so that nobody gets pinged about old orders the log can't place.
39. As the bot operator, I want a missed 9:00 run (server down) to run once on the next start-up that day and never twice on the same day, so that a reboot neither skips nor doubles a nudge.
40. As the bot operator, I want each request to get at most one nudge per day, so that a restart or a double run never repeats a message.
41. As the bot operator, I want a nudge that fails to send (e.g. DM refused) to be logged and not to stop the other requests' nudges, so that one bad request can't block the rest.

## Implementation Decisions

### Assignment (the one function)

- All three inputs — the thread card picker, the DM card picker and the typed
  `assign` keyword — go through the existing lifecycle assignment function. There is
  no second assignment implementation.
- **Permission** replaces ADR 0004 decision 3's table. Before Processed, any buyer,
  approver or admin may set or change the assignee, whether or not the request is
  already assigned. Anyone else is refused privately; nothing changes.
- **Stage cutoff.** Assignment is allowed while the request is `approved` (and on a
  `posted` card, as today). From `processed` on, it is refused with a public in-thread
  line naming who processed it and when, e.g.
  `🔒 Already Processed by Dylan on 09/24/26 — the buyer can't change after this point.`
  The request's stage is read the way the stage buttons read it today.
- **Same buyer.** Selecting the current assignee is a no-op: no DM, no history line, no
  thread line.
- **Old buyer DM.** On a reassignment the old buyer receives a new DM message (not just
  a card edit — Slack does not notify on edits):
  `↪️ <item> was moved to <new buyer> by <actor>. You don't need to do anything on it.`
  This is sent in addition to retiring the old DM card, which already happens.
- Everything the reassignment already does today (history line, thread line, email
  draft and fresh DM card to the new buyer, old DM card retired) is unchanged.

### The picker on approved cards

- The card builder currently adds the `users_select` buyer picker only in the `posted`
  state. It is added in the `approved` state too, on both the thread card and the DM
  card, with placeholder "Assign a buyer" and `initial_user` set to the current
  assignee when there is one. It is absent in `processed`, `confirmed`, `delivered`
  and every retired state.
- The existing picker action handler recovers the request from the sibling Approve
  button, which an approved card does not have. It must also recover the request from
  an approved card's stage button value, and a DM-card picker must resolve to the
  thread card the same way a DM-card stage click does today (the DM card holds a
  pointer, not state). The thread card stays authoritative (ADR 0010 decision 2).
- A separate action ID is used for the DM-card picker if Slack's routing or the
  existing DM-card handlers require it; both route into the one assignment function.

### The request log

- `requests.json` at the bot's base directory beside `roster.json`, already in
  `.gitignore`. Kept by the existing `store` module, reusing its API
  (`create`, `get`, `get_by_thread`, `update`, `append_history`) and its atomic write
  and corrupt-file handling. The module's docstring and the glossary entry are updated
  to say it is the request log, not the request's live state.
- An entry holds: channel, thread timestamp, card timestamp, requester, current buyer
  (name and Slack ID), rows, the approval time, the time the current buyer was set,
  a history list, and the nudge bookkeeping below. It holds **no stage field**.
- Written at: approval (create), assign and reassign (buyer, buyer-set time, history),
  Processed, Confirmed, Delivered, Cancel (history). A Cancel keeps the entry and marks
  it cancelled in its history; it is not deleted (overrides the old spec's
  delete-on-cancel).
- A write to the log never blocks the Slack action. On failure: log at ERROR and alert
  the admin channel; the card, workbook and DMs proceed as normal.
- No backfill of requests approved before this ships.

### The nudge

- A new pure-ish function takes today's date (and the Slack client) and does one day's
  nudging: for every log entry whose workbook rows have no Date Processed and which is
  not cancelled, compute working days elapsed (Mon–Fri; holidays not skipped) since
  the later of approval and the last buyer change, and send what the schedule says:

  | Working days | Assigned | Unassigned |
  |---|---|---|
  | 3 | DM card re-posted to the buyer with a nudge line | thread line @-mentioning every buyer |
  | 6 | same DM, plus a thread reply with `reply_broadcast` @-mentioning the buyer | the same line with `reply_broadcast` |
  | 9, 12, … | DM only | nothing |

  Unassigned elapsed time counts from approval only.
- **Stage source.** Processed is read from the workbook's Date Processed column via the
  existing row-info reader at run time, not from the log.
- **Nudge DM.** Retire the buyer's current DM card and post a fresh one, with the text
  `⏰ <item> has been assigned to you for <N> working days and isn't marked Processed yet.`
  above it, carrying Mark Processed and the buyer picker. The request entry's DM
  pointer is updated so the two-card sync keeps working.
- **Unassigned text.** `⏰ Approved <N> working days ago and nobody's assigned yet.`
  followed by the buyer mentions. No "pick yourself" wording.
- **Idempotence.** Each entry records the date of its last nudge; the function sends at
  most one nudge per entry per date and skips an entry already nudged today.
- **Scheduling.** A daemon thread started beside the heartbeat at start-up. On weekdays
  it calls the function once at 9:00 America/Chicago. On start-up, if it is a weekday,
  after 9:00, and today's run has not happened, it runs once. The last-run date is
  persisted (in the request log file, top-level) so a restart can tell. The thread holds
  no logic beyond "is it time" and calling the function.
- One failed send is logged and the loop continues with the next entry.

## Testing Decisions

- Tests exercise behaviour a person would see: DMs sent and to whom, their text, which
  card blocks are present, which thread posts were made (and with `reply_broadcast`),
  what `requests.json` contains, and what was **not** sent. A test that only asserts a
  mock was called is not enough. ADR 0001 applies: tests first, no muted failures.
- May fake: the Slack client, the clock (the nudge function takes the date), the
  workbook row reader where the test is about nudge timing. Must be real: the
  assignment function, the card builder, the `store` module writing a temporary
  `requests.json`, and the roster on a temporary file.
- **Seam 1 — assignment.** Drive it through the app's action handlers with a fake
  client, as `tests/test_69_cards_move_together.py` and `tests/test_66_stage_permissions.py`
  do. Cover: another buyer moves an assigned request; a non-buyer is refused; a picker
  click on a Processed request and a typed `assign` on one are refused with the
  processed-by line; the old buyer gets the moved-to DM; selecting the current assignee
  sends nothing; the approved thread card and DM card both carry the picker and the
  Processed card does not; a DM-card picker click updates the thread card.
- **Seam 2 — the request log.** Extend `tests/test_store.py` style: after approval,
  reassign, each stage and cancel, open the temporary `requests.json` and assert the
  entry's buyer and history lines; a cancelled entry remains; a log write that raises
  does not stop the approval and alerts the admin channel.
- **Seam 3 — the nudge function.** Given a temporary log and a faked row reader, call it
  for chosen dates: day 2 → nothing; day 3 → DM only; day 6 → DM plus a broadcast reply;
  day 9 → DM only; unassigned day 3 → thread line naming every buyer; unassigned day 9
  → nothing; weekend date → nothing; a Date Processed present → nothing; reassigned
  yesterday → nothing; calling twice with the same date → one nudge; one request whose
  DM raises → the others still sent.
- The scheduler thread is not unit-tested beyond "start-up after 9:00 on a weekday with
  no run recorded calls the function once".

## Out of Scope

- An Assigned Buyer column in the Purchasing Log.
- Drawing cards from the request log (the card stays the live store).
- Backfilling requests approved before this update.
- University holidays in the working-day count.
- A snooze / "not yet" button on the nudge.
- Nudging about Confirmed or Delivered; only "not yet Processed" is nudged.
- Changing who may click stage buttons (ADR 0010 decision 4 stands).
- Letting the approver configure the schedule from Slack.

## Further Notes

- The typed keyword `@Purchasing assign @buyer` keeps working and is not taught in new
  places; the App Home command list gains one line saying the buyer can be changed from
  the card until Processed.
- `requests.json` lives on the production server beside `roster.json`; deploying needs
  no `.env` change.
- Nudges reach only requests approved after the deploy, so the first nudge can arrive no
  sooner than 3 working days after the update.
