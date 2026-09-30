# ADR 0010 — Every approval leaves a card; the buyer's DM carries a linked card; a DM the bot cannot read gets help

**Status:** accepted
**Date:** 2026-09-29
**Amends:** ADR 0002 decision 8 (notifications are DMs — still true, a DM may now carry a
button); ADR 0009 decision 3 (the no-close-match reply is the help text itself, in DMs
only). ADR 0002 decision 3 (the message is the store) stands and is relied on below.

## Context

Production, 2026-09-29. A lab member dropped a filled EPIF PDF in a purchasing thread.
The approver approved it with `@Smeet @Purchasing Approved`. The bot wrote row 21 and
DM'd the buyer the email draft — and **no card appeared in the thread at all**: not
the Approve card when the PDF was dropped, not the Approved card afterwards. The buyer
had no Mark Processed button to click and typed "Sent" in the thread instead, which
the bot cannot act on.

`finalize_purchase_request` updates the thread card `if target_card_ts:` and otherwise
does nothing. A request the bot logged can therefore exist with no card and no button
anywhere. The same day, a member's first DM to the bot was a natural sentence with a
link; it crashed the bot (ticket 51), and Slack's own link-unfurl edit event, which has
no user and no text, was handled as if a person had sent it.

## Decision

### 1. Every approval leaves a card in the thread

If approval finds no card in the thread, the bot posts one, already in the `approved`
state, with the same History and buttons as any other approved card. A request in the
workbook always has a card. Updating an existing card in place is unchanged.

### 2. The buyer's DM carries a second card, and it is only a view

When a buyer is assigned, their DM gets a **DM card**: a short summary, a link to the
thread card, and the one next-step button for the current stage. **The thread card
remains the store** (ADR 0002 decision 3). The DM card carries only a pointer to the
thread card and holds no request state of its own; every click reads the thread card
to learn the true state. If the two ever disagree, the thread card wins.

### 3. Two cards, one state

A stage click on either card advances the request through the one lifecycle handler
(invariant 1), and both cards are updated to the new stage and the new next-step
button, until delivered. The DM card has no Cancel button — cancelling stays an
approver/admin action on the thread card. A cancel retires the DM card (no buttons, one
line saying so). A reassignment retires the old buyer's DM card and gives the new buyer
a fresh one. A click on a DM card whose stage is already behind the thread card is
refused privately ("already <stage>") and the DM card is refreshed.

### 4. Who may click a stage button

The same rule on both cards, for Mark Processed, Mark Confirmed and Mark Delivered:
**the assigned buyer, any admin, or any approver.** Any other person — including a
different buyer — is refused privately, naming the assignee, and nothing is written. An
unassigned request refuses the stage buttons until a buyer is assigned. This adds the
approver to the earlier rule (assigned buyer or admin); ADR 0004's protection of an
assigned buyer's order from another *buyer* is unchanged.

### 5. The bot answers only when addressed, and never guesses

The bot does not read thread chatter to infer what a reply means ("Sent", "ordered
it"). Progress is recorded by a button, or by an explicit `@Purchasing` keyword. In a
DM, a message that is not a keyword gets: "did you mean …?" when it is close to one,
otherwise the actual help text with a **Start a purchase request** button. The button
opens the ordinary blank interview; **nothing from the DM is carried into it** — no
link or text is scraped. Parsing free text into a request is rejected as fragile: a
wrong guess becomes a wrong purchase.

### 6. Slack's own events are not messages from people

A `message` event with no user, or with a subtype other than a plain message or a file
share (edits, link unfurls, deletions), is ignored. It never reaches the dispatcher.

### 7. A failed card or drop is loud, in the admin alert channel

Where a step that should have produced a card fails or is skipped — the dropped PDF
could not be parsed, the card could not be posted or updated — the bot says so in the
**admin alert channel** with what happened: the thread, the file name, the step and the
error. It does not stay quiet in a log file. A failure to alert never blocks the
approval.

## Consequences

- `CONTEXT.md` gains **DM card**, and its **card**, **DM**, **Alert channel** and
  **Keyword** entries change.
- The thread card's payload records where the DM card lives (its channel and
  timestamp). Every card rebuild carries that reference forward.
- One new permission predicate replaces three near-identical inline checks in the stage
  button listeners.
- The stage handlers gain one shared step that refreshes the DM card; the lifecycle
  keyword aliases (`@Purchasing processed`) refresh it too, because they call the same
  handlers.
- Reading the drop failure at all depends on the Slack app being subscribed to channel
  message events. That is app configuration, not code; it is a human task in the set.
