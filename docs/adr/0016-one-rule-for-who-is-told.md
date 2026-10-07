# ADR 0016 — One rule for who is told, and a declined request is told

**Status:** accepted
**Date:** 2026-10-07
**Amends:** ADR 0003 decision 3 (decline now sends one DM; still no row, no log entry,
no reason).

## Context

When an approval failed on 2026-10-05 the error DM went to the bot itself, because
`handle_epif_processing` DMs "whoever posted the PDF", and the bot had posted it. Each of
the bot's request-related DMs picks its recipient its own way (`slack_io.tell` is called
directly from several places in `lifecycle.py`), so the same mistake can recur anywhere.
Separately, a declined requester hears nothing: ADR 0003 decision 3 kept decline silent.

## Decision

### 1. One function sends every request-related notice

A new function in `slack_io` is the only way a request's error, refusal or decline
notice reaches a person by DM. Every direct `slack_io.tell` that reports a problem with a
request moves to it. DMs that are not about a request (roster and admin confirmations)
are unchanged.

### 2. Who gets the DM

- **The person who acted** — clicked the button, typed the keyword, submitted the form,
  dropped the file.
- **The requester too**, when the fix is theirs: a flattened EPIF, missing or bad fields,
  a P-card at $5,000 or more (ADR 0017), a quote that failed to attach.
  When the fix is the approver's or the bot's, the requester is not DM'd.
- **Never a bot.** A recipient equal to the bot's own user id, or any id that is not a
  person, is dropped. If that leaves no one, the person who acted is used.
- The same person is never DM'd twice for one event.

### 3. What every notice carries

A link to the thread (`chat.getPermalink` on the thread's parent message). A failure
that already posts a thread reply keeps it; the DM does not replace it.

### 4. A decline DMs the requester

> Your request for *{item}* ({vendor}, ${total}) was declined by {approver name}.
> Any discussion is in the thread: {link}

Decline still takes no reason, writes no row and creates no log entry (ADR 0003
decisions 2–3). The card update is unchanged.

## Consequences

- The bot's own user id is needed below the listener layer. `slack_io` gains the cached
  `auth.test` lookup that `app.get_bot_user_id` does today, and `app` calls it.
- `CONTEXT.md` **Decline** is updated.
