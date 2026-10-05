# Spec — A nudge for every stage, set from App Home, and an expected delivery date

**Status:** ready-for-agent
**Binding:** `docs/adr/0013-nudge-settings-per-stage-and-expected-delivery.md`,
`docs/adr/0011-buyers-hand-off-requests-and-the-request-log.md` (decisions 3 and 4 amended
by 0013), `docs/adr/0010-linked-cards-and-direct-message-help.md` (decision 4 amended by
0013), `docs/adr/0001-tests-first-and-no-muted-failures.md`
**Glossary:** `CONTEXT.md` — **Nudge** (rewritten), **Nudge card** (new), **Expected
delivery** (new), **The request log** (now starts at posting), **DM card**, **Posted**,
**Unassigned**
**Builds on:** `.scratch/buyer-handoff-and-nudge/` (request log, the processed nudge, the
9:00 weekday timer).

## Problem Statement

The bot nudges about exactly one wait: approved but not processed. It does so on a schedule
hardcoded in code (3, 6, then every 3 working days), and nothing on App Home explains it.
Nothing reminds anyone once an order is processed, so a request can sit unconfirmed or
undelivered indefinitely, and the lab loses track of what has actually shown up. Nothing
reminds the approver about a posted request either.

The stages wait very different lengths of time. A reminder every 3 days is right for
processing and pure noise for a delivery that takes months. Changing the schedule today
means a code change, and the server's settings need someone physically at the machine.
When an order is known to take six weeks, there is no way to tell the bot "check back then".

## Solution

There are four nudges, each named for the stage it is waiting on: **approved** (a posted
card nobody has approved), **processed**, **confirmed** and **delivered**. Each nudge has
one setting: on or off, every N working days from when the request entered its current
stage, sent by DM, by a thread reply also sent to the channel, or both. Admins change the
settings from a button on App Home. Everyone sees a **Nudges** section on App Home (and in
`/purchasing-help`) built from the live settings.

The delivered nudge goes to both the buyer and the requester, and comes as a small **nudge
card** with two buttons: **Delivered**, and **Not yet — set expected date**. Picking a date
pauses delivered nudges until that day, then they resume every N. A Confirmed card can also
take an expected date up front. The requester, who usually sees the package arrive, may
now mark Delivered.

## User Stories

1. As an admin, I want an **Edit nudge settings** button on App Home that only admins see, so that I can tune nudges without touching the server.
2. As an admin, I want to turn each of the four nudges on or off, so that stages that don't need chasing stay quiet.
3. As an admin, I want to set "every N working days" separately for each nudge, so that a delivery can wait weeks while processing is chased in days.
4. As an admin, I want to choose DM, channel or both for each nudge, so that a slow-moving stage can be called out publicly.
5. As an admin, I want the form to refuse a nudge that is on with neither DM nor channel ticked, so that a nudge can't be on but silent.
6. As an admin, I want the form to refuse N below 1 or not a whole number, so that the schedule always makes sense.
7. As an admin, I want a settings change to apply to open requests from the next 9:00 run, so that I don't have to touch individual requests.
8. As an admin, I want the settings kept in their own file beside the roster, so that the roster and the request log stay uncluttered.
9. As an admin, I want a missing settings file to mean the shipped defaults, so that a fresh install works.
10. As an admin, I want a corrupt settings file to fall back to the defaults and alert the admin channel, so that a bad edit is loud, not silent.
11. As a non-admin who somehow submits the settings form, I want to be refused, so that only admins change nudges.
12. As a lab member, I want App Home to show a **Nudges** section describing each nudge from the live settings, so that I know when the bot will chase me.
13. As a lab member, I want `/purchasing-help` to show the same Nudges text, so that the two surfaces never disagree.
14. As an approver, when the approved nudge is on, I want a DM after N working days about a posted card nobody has approved, with a link to its thread card, so that requests don't sit unseen.
15. As an approver, I want the approved nudge to stop once the card is approved, declined or superseded, so that I'm not chased about finished business.
16. As a buyer, I want the processed nudge to keep re-posting my DM card with Mark Processed and the buyer picker, as today, so that the button is right in front of me.
17. As a buyer, when the processed nudge's channel option is on, I want a thread reply also sent to the channel @-mentioning me, so that a stalled order is visible.
18. As the buyers, when a request is unassigned, I want one thread line @-mentioning all of us every N working days until someone is assigned, so that it gets picked up.
19. As the buyers, when the processed nudge's channel option is on, I want that unassigned line also sent to the channel, so that the lab sees it.
20. As a buyer, I want a confirmed nudge every N working days after Date Processed, re-posting my DM card with Mark Confirmed, so that I chase purchasing or the vendor.
21. As a buyer and as a requester, I want the delivered nudge N working days after Date Confirmed, @-mentioning both of us and asking "Has this been delivered?", so that whoever sees the package can answer.
22. As a buyer or requester, I want the delivered nudge to carry a **Delivered** button, so that I can close it right there.
23. As a buyer or requester, I want **Delivered** on a nudge card to move the thread card and the DM card exactly like Mark Delivered, so that every surface agrees.
24. As a buyer or requester, I want the nudge card to show it's done after Delivered is pressed, so that nobody presses it twice.
25. As anyone in the thread, I want an older nudge card retired ("Replaced by a newer reminder") when a new one posts, so that only one live nudge card exists.
26. As a buyer or requester, I want **Not yet — set expected date** to open a form with one date picker, so that I can say when it's due.
27. As a buyer or requester, I want a past date refused, so that a typo can't silence nudges.
28. As anyone in the thread, after a date is set, I want "Expected delivery <date> — I'll check back then.", so that everyone knows the plan.
29. As a buyer or requester, I want delivered nudges paused until the expected date, then a nudge on that date (or the next weekday at 9:00), then every N, so that a six-week order isn't nagged.
30. As a buyer or requester, I want to push the date back any number of times, each change posting a thread line and a history line, so that slips are recorded.
31. As a buyer, I want an optional **Set expected delivery** button on a Confirmed card (thread and DM), so that I can enter the vendor's date before the first nudge.
32. As anyone, I want the thread card and DM card to show "Expected delivery: <date>" once set, so that the date is visible where people look.
33. As an approver or admin, I want to be able to set the expected date and press Delivered too, so that I can close things out.
34. As a requester, I want to press Delivered (and only Delivered) on the thread card, so that I can record arrival without waiting for the buyer.
35. As a requester, I want Mark Processed and Mark Confirmed still refused to me with the existing refusal message, so that the other stages stay with the buyer.
36. As a requester with no Slack ID on record (an old request), I want the delivered nudge simply to @-mention the buyer, so that a missing ID never breaks the nudge.
37. As an admin, I want a request posted after this ships to enter the request log when its card is posted, so that the approved nudge can find it.
38. As an admin, I want approval to update that entry rather than create a second one, so that each request has one history.
39. As an admin, I want requests posted before this ships left alone (not backfilled), so that the change is safe to deploy.
40. As an admin, I want one request's nudge failing to leave the rest unaffected and the failure logged, as today, so that one bad thread doesn't stop the run.
41. As an admin, I want the shipped defaults to be approved off; processed every 3, DM; confirmed every 5, DM; delivered every 10, channel, so that behaviour is sensible before I touch anything.

## Implementation Decisions

- **Settings module.** A small module owns the nudge settings: load (missing file →
  defaults; unreadable → defaults plus an admin alert through the existing alert helper),
  validate, and save atomically (temp file + replace, as the request log and the nudge
  run-file already do). File `nudge_settings.json` beside `roster.json`, gitignored.
  Shape (one key per nudge, nothing else):

  ```json
  {
    "approved":  {"enabled": false, "every": 3,  "dm": true,  "channel": false},
    "processed": {"enabled": true,  "every": 3,  "dm": true,  "channel": false},
    "confirmed": {"enabled": true,  "every": 5,  "dm": true,  "channel": false},
    "delivered": {"enabled": true,  "every": 10, "dm": false, "channel": true}
  }
  ```

  A file missing a key takes that key's default.
- **Which nudge applies.** The request's stage decides, read the way the processed nudge
  reads it today: the thread card's state for **posted** (approved nudge); otherwise the
  workbook row's Date Processed / Date Confirmed / Date Delivered for the request's first
  row (a batch moves together). Delivered → nothing. Cancelled → nothing. The request log
  still never holds a stage.
- **When.** `n` = working days from the stage-entry date to today, using the existing
  working-day function: posting date (approved), buyer-set date or approval date as today
  (processed), Date Processed (confirmed), Date Confirmed (delivered). Nudge when
  `n >= every and n % every == 0`. With an expected delivery date `E`: no delivered nudge
  before `E`; nudge on the first weekday on or after `E`; then every `every` working days
  counted from `E`. The existing once-per-day guard (`last_nudged`) stays. Workbook dates
  may be stored as dates, date strings or Excel serial numbers; all three must parse; an
  unparseable date skips that request with a warning.
- **How, per nudge.**
  - *approved* — DM: each approver gets a DM with the item, requester and a link to the
    thread card (no buttons). Channel: a thread reply with `reply_broadcast` @-mentioning
    the approvers.
  - *processed, assigned* — DM: today's behaviour (retire DM card, post a fresh one with
    Mark Processed and the picker, update the thread card's DM pointers). Channel: a
    thread reply with `reply_broadcast` @-mentioning the buyer.
  - *processed, unassigned* — DM: one thread line @-mentioning every buyer. Channel: the
    same line with `reply_broadcast`. Both on → one line with `reply_broadcast`. Repeats
    every N until assigned (the old "day 3 and 6 only" rule is removed).
  - *confirmed* — same as processed-assigned, with the Confirmed DM card (Mark Confirmed).
  - *delivered* — a **nudge card**: text "Has this been delivered?" @-mentioning the buyer
    and the requester, with **Delivered** and **Not yet — set expected date**. Channel:
    posted as a thread reply with `reply_broadcast`. DM: posted to the buyer's DM and the
    requester's DM. The bot keeps the channel/ts of every nudge card it posts for the
    request in the request log, and retires the previous ones ("Replaced by a newer
    reminder", buttons removed) when posting new ones.
- **Nudge card is a view.** Its buttons carry only the thread card's coordinates. Pressing
  Delivered runs the same delivery handler as Mark Delivered (thread card and DM card move
  together), then updates every live nudge card for the request to "✅ Delivered by <@user>"
  with no buttons. A press on a request already delivered or cancelled updates the nudge
  card to say so and changes nothing else.
- **Who may press.** The existing stage-permission check gains one exception: the
  requester (the request's requester Slack ID, from the card payload or the request log)
  may mark **Delivered** only. The same rule covers the thread card, the DM card and the
  nudge card. Set expected delivery: buyer, requester, admin, approver. Refusals reuse the
  existing ephemeral refusal message.
- **Expected delivery form.** A modal with one `datepicker` (initial date: today + every
  working days for the delivered nudge, if none set; otherwise the current date), the
  thread card's coordinates in `private_metadata`. Submit: date before today → field error
  "Pick today or a later date." Otherwise: store `expected_delivery` (ISO date) in the
  card payload (so a card rebuild keeps showing it) and the request log; append a history
  line to both; post the thread line from story 28; update the thread card and DM card to
  show "Expected delivery: <Mon D>". Opened from the nudge card's Not yet button and from a
  **Set expected delivery** button on the Confirmed thread card and Confirmed DM card.
  Optional — never required to mark anything.
- **Request log at posting.** A card posted through `/new-purchase` or from a dropped
  EPIF creates its request-log entry at posting (with `posted_at`, `card_ts`,
  `requester_id`). Approval updates the entry for that `card_ts` (adding `approved_at`,
  buyer and rows) instead of creating a new one; approval with no entry (bare-thread, or
  posted before this ships) creates one as today. Decline and supersede set `declined` /
  `superseded` on the entry so the approved nudge skips it without reading Slack. Entries
  are matched by `card_ts`, never by thread alone, because one thread can hold several
  posted cards.
- **Settings form.** App Home shows an **Edit nudge settings** button only when the viewer
  is an admin. It opens a modal with, per nudge: an on/off checkbox, a number input for
  every N (whole number, min 1), and checkboxes DM / Channel; pre-filled from the current
  settings. Submit re-checks admin, validates (stories 5–6, errors on the offending
  block), saves, and re-publishes the admin's App Home.
- **Nudges text.** One function renders the Nudges section from the current settings
  (e.g. "*Processed* — every 3 working days after approval, by DM to the buyer"; "off" for
  disabled ones; the delivered line mentions expected delivery). Both `build_app_home_view`
  and `get_help_message` call it, keeping the rule that the two surfaces cannot drift. The
  Stage definitions text also says the requester may mark Delivered.
- **Timer unchanged.** Weekdays 9:00, catch-up on a late start, `nudge_run.json` — all as
  built in ticket 80.

## Testing Decisions

- Tests check what a person would see: who got a DM and its text, which thread posts were
  made and whether `reply_broadcast` was set, which buttons a card or nudge card carries,
  which nudge cards were retired, the App Home blocks, the settings file's contents, the
  request log's contents, form error texts, and what was **not** sent. A test that only
  asserts a mock was called is not enough. ADR 0001 applies: tests first, no muted failures.
- May fake: the Slack client, the date (the nudge function takes it), the workbook row
  reader where the test is about timing. Must be real: the settings module on a temporary
  `nudge_settings.json`, the request log on a temporary `requests.json`, the card
  builders, the stage-permission check, the delivery handler.
- **Seam 1 — the nudge run.** Call the existing nudge function for chosen dates against a
  temporary log, a temporary settings file and a faked row reader. Cover: each nudge on
  its N and not the day before; off → nothing; DM only / channel only / both; unassigned
  repeats every N until assigned; confirmed counts from Date Processed; delivered counts
  from Date Confirmed; expected delivery pauses then resumes on the date and every N after;
  a weekend expected date fires the next Monday; a new delivered nudge retires the old
  nudge card; approved nudge for a posted entry, skipped once declined/superseded/approved;
  Excel-serial and string dates both parse; one failure doesn't stop the rest; settings
  changed between two runs take effect on the second. Prior art:
  `tests/test_78_nudge_assigned.py`, `tests/test_79_nudge_unassigned.py`.
- **Seam 2 — the action and view handlers.** Drive through the app's handlers with a fake
  client: nudge-card Delivered by buyer, by requester, by a stranger (refused); requester
  pressing Mark Processed (refused) and Mark Delivered on the thread card (allowed);
  expected-date form with a past date (error) and a valid date (thread line, both cards
  show it, log updated); Set expected delivery from a Confirmed card; settings form by an
  admin (saved, App Home re-published) and by a non-admin (refused); settings validation
  errors; posting a card creates a log entry and approval updates it. Prior art:
  `tests/test_66_stage_permissions.py`, `tests/test_68_dm_click.py`,
  `tests/test_69_cards_move_together.py`, `tests/test_76_request_log_approval_and_assign.py`.
- **Seam 3 — App Home and help.** Call `build_app_home_view` for an admin and a non-admin
  with a temporary settings file: only the admin sees the button; both see the Nudges
  section matching the settings; `/purchasing-help` contains the same Nudges text. Prior
  art: `tests/test_09_app_home_help.py`, `tests/test_22_live_roster_panel.py`.
- Existing nudge tests that encode the old 3/6/every-3 schedule are rewritten in place
  under the same names to the new rule; no test is deleted.

## Out of Scope

- Snooze, "stop after X nudges", or escalation steps for any nudge.
- An expected date for any stage other than delivered.
- A configurable run time (stays weekdays 9:00), holiday calendars.
- A workbook column for expected delivery.
- A DM card for the requester; a one-time "your package is in" notification.
- Backfilling posted or approved requests from before this ships.
- Nudging loose threads that have no posted card.

## Further Notes

- Turning the processed nudge's channel option off reproduces today's DM-only cadence
  except for the old day-6 channel escalation, which is gone by design.
- The approved nudge ships off; turn it on from App Home once the approver agrees.
