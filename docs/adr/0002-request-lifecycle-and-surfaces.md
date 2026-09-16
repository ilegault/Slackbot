# ADR 0002 — The request lifecycle, its surfaces, and the three roles

**Status:** accepted
**Date:** 2026-09-16
**Supersedes:** nothing. This is the first written record of decisions that were
previously only made in conversation.

## Context

P-Bot grew two command surfaces — slash commands and `@p-bot` keywords — with
nothing telling a user which to use, and with lifecycle logic reachable from both.
Meanwhile new lab members found the purchase form unintuitive, buyers could not be
mentioned, and a buyer's own request skipped the claim step entirely.

The decisions below were made across several planning sessions. They are recorded
here because a decision that lives only in a chat log is re-litigated by every
session that follows, differently each time.

## Decision

### 1. Approval is the moment a request comes into existence

A purchasing thread discusses freely before anyone agrees what to order — links,
quotes, "the 5 mm or the 10 mm". There is nothing to build a request object out of
until Charlie says yes. So approval stays a text keyword (`@p-bot approved`) or an
Approve button on a request already formalised through the interview modal, and
**the button card appears only after approval.** The bot does not try to detect a
request forming in conversation.

### 2. The interface rule

> **If the action needs a target, it is a button on that target.
> If it does not, it is a slash command.**

Slash command payloads carry `channel_id` but no `thread_ts`, so a slash command
cannot act on a specific request. Block Kit button clicks carry `channel.id`,
`container.message_ts` and `container.thread_ts`.

| Action | Surface |
|---|---|
| Start a purchase | `/new-purchase` + App Home button |
| Help, blank EPIF, set name, list roster | the other four slash commands |
| Approve, Decline, Claim, Mark Processed, Mark Confirmed, Mark Delivered, Cancel | buttons on the request message |
| Attach a quote or confirmation | drop the file in the thread |
| restart, logs, update, health, queue, roster management | `@p-bot <keyword>`, admin only, kept off the `/` list |

**Lifecycle keywords keep working as undocumented aliases** so Charlie's habits do
not break. They stop being taught anywhere — not in help, not on App Home, not in
the channel post.

**Roster management stays on `@p-bot` keyword pairs** (`add-buyer` / `remove-buyer`,
matching the existing `add-approver` / `remove-approver`) rather than moving to a
Block Kit user-picker panel. Consistency with the pair that already exists beats a
nicer widget for one of them.

### 3. The message is the store

A request's state, payload and history are serialized into the next-step button's
`value`. The message carries everything the next click needs, so a bot restart
cannot lose a request's position and there is no server-side state to reconcile.

`src/store.py` is **not** the store. It is not imported by anything. Building on it
requires a new ADR superseding this decision, not a judgement call inside a ticket.

### 4. One standardized word per action, everywhere

Including in the silent keyword aliases. The four post-approval stages are
**approved → processed → confirmed → delivered**, and *processed* means the request
has gone to the purchasing team.

The word is `processed`, not *submitted*: the Excel column has always been *Date
Processed*, and a word with two spellings stops being searchable and stops being
teachable. The rename happens once, across every surface at the same time — see
ADR 0003 and ticket 05.

### 5. Three roles, never conflated

**Approver** (Charlie) approves and never buys. **Admin** (Isaac) manages the bot
and the roster. **Buyer** (Isaac, Finn, Smeet, Dylan) claims and processes orders.
None of the three implies another.

Roles are **Slack IDs, not display names**: an ID can be `<@…>` mentioned, survives
a profile change, and cannot collide. `config.GRAD_STUDENT_BUYERS` — a hardcoded
set of name strings — is the violation this decision exists to remove.

**Buyers are admin-editable from Slack**, like every other roster list. Adding a
grad student should not be a code edit plus a restart.

### 6. Every approved request waits for a claim

Including a request from a buyer themselves. There is no auto-assign shortcut,
because purchasing duty rotates between grad students (Charlie's arrangement,
Dylan first) and the person who asked is not necessarily the person whose turn it
is. The claim broadcast @-mentions all buyers in the channel.

**The Claim button is restricted to buyers.** A non-buyer clicking it gets an
ephemeral denial, the message is not updated, and nothing is written.

The email draft moves from approval to claim, addressed to and DM'd to the
**claimer** — they are the one emailing purchasing, so a draft signed by the
requester is wrong.

### 7. A batch is one request

Big orders often carry multiple EPIFs in one thread, plus quotes. The bot handles
all of them, not just the first. A batch is **approved together and cancelled
together** — no per-item control.

### 8. Notifications are DMs

Bot notifications stay DMs across the whole flow rather than moving to the alert
channel, and are consistent about it. The alert channel is for things an admin has
to decide — a new requester, a new vendor, a pending name confirmation.

### 9. App Home carries the definitions, and no link to the log

App Home states the four stages plainly, so a new lab member can read what
"processed" means without asking. It does **not** link the Purchasing Log.

## Consequences

- Lifecycle logic has exactly one implementation per operation, reachable from both
  the button and the keyword. Two copies of "mark delivered" is the failure mode
  this rules out.
- Adding a buyer becomes a Slack action. Removing `GRAD_STUDENT_BUYERS` also fixes
  the claim broadcast, which currently prints plain names nobody is notified about.
- Every user-facing string that teaches a lifecycle keyword has to change. Help,
  App Home, and the channel post's "Reply with `@p-bot approved` in this thread".
- The bot does not know whose turn it is on the purchasing rotation, and is not
  going to. That stays a human arrangement.
