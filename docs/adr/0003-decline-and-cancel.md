# ADR 0003 — Decline before approval, cancel before processing

**Status:** accepted
**Date:** 2026-09-16
**Extends:** ADR 0002 (the lifecycle and its surfaces)

## Context

There was no way to say no. A request that Charlie did not want sat on the channel
with an Approve button forever, and an approved purchase that turned out to be
wrong stayed in `Purchasing-Log.xlsx` as a live row with nothing marking it dead.
Isaac: *"there should 100% be a decline/remove action for Hirst to use."*

Two different moments need two different actions, and the design question was what
each one does to the workbook.

## Decision

### 1. Decline is pre-approval. Cancel is post-approval.

They are never used interchangeably and never share a code path.

**Decline** is the approver's "no" on a request in the `posted` state. **Cancel**
kills a request that was already approved and written to the workbook.

### 2. Neither takes a reason

One click, no modal, no justification field, no follow-up question. The point is to
reduce friction: an approver who has to explain themselves declines less, and a
request nobody declines sits on the channel misleading people. The thread is where
the reason gets said, if it gets said.

### 3. Decline is not logged

No Excel row (there is none yet — nothing was written before approval), no alert,
no audit entry. The declined message updates to show it was declined and by whom,
and that is the whole record.

### 4. Cancel un-writes the Excel row

It **blanks** the row rather than marking it cancelled or striking it through.

The workbook is a log of live approved purchases and their stage, **nothing else**.
A cancelled purchase is not a live approved purchase, so it does not belong in it —
a "CANCELLED" row is a row somebody has to read past forever, and the lab reads
this file as fact.

**Recycling a blanked row is fine.** The cancellation is visible as text in the
thread, which is the record; the workbook does not need to carry a tombstone to
preserve it.

### 5. Cancel is only allowed before a request is processed

Once the request has gone to the purchasing team, the bot no longer controls what
happens — there is a Workday requisition or a ShopUW cart out in the world, and
blanking a row would hide a purchase that is still going to arrive.

**A cancel attempted after `processed` is refused loudly.** Not silently, not with
a generic error: the bot says clearly in-thread that the request has already been
processed and cannot be cancelled here, so the approver knows to go talk to
purchasing rather than assuming it worked.

### 6. Both approvers and admins can cancel

Approver because it is their money decision to reverse; admin because they are the
one cleaning up when something goes wrong with the bot. Buyers cannot.

### 7. A batch cancels as a batch

A request carrying multiple EPIFs is cancelled in one action, and every row it
wrote is blanked. No per-item cancel — see ADR 0002 decision 7.

## Consequences

- `log_writer` needs a blank-row operation alongside `append_row` and `update_row`,
  going through the same lock queue as every other write.
- The request card needs a second button on two states: Decline alongside Approve
  on `posted`, and Cancel alongside the next-step button on `approved` and
  `claimed`. Cancel disappears at `processed`.
- The stage a request is in has to be readable at cancel time to enforce decision
  5. It is: state lives in the button's `value` (ADR 0002 decision 3).
- Because neither action takes a reason, there is no structured data about *why*
  purchases get declined. That is an accepted loss; if it turns out to matter, it
  is a new ADR, not a quiet modal added to the cancel button.
