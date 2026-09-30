# 70: Developer — confirm the Slack app hears channel messages; drop a test EPIF

**Status:** ready-for-developer

**Runner:** developer

**Auto-merge:** no

**Blocked by:** None (can start immediately)

**Spec:** `.scratch/dm-help-and-linked-cards/spec.md`
**Binding:** `docs/adr/0010-linked-cards-and-direct-message-help.md` decision 7

## What to build

A person at the Slack app settings and the purchasing channel. **An agent must not claim this
ticket.** In production a dropped EPIF PDF produced no approval card at all. One possible cause is
that the app is not subscribed to channel message events, so the drop handler never runs. This is
configuration, not code, and it should be known before ticket 65's alert reports it.

## Acceptance criteria

- [ ] In the Slack app's **Event Subscriptions → Subscribe to bot events**: `app_mention`,
  `message.channels` (and `message.groups` if the purchasing channel is private), `message.im` and
  `app_home_opened` are all listed. If any was missing, add it and reinstall the app to the workspace.
- [ ] In **OAuth & Permissions → Bot Token Scopes**: `channels:history` (and `groups:history` if
  private), `im:history`, `files:read`, `files:write`, `chat:write`, `users:read`.
- [ ] The Purchasing bot is a member of the purchasing channel (`/invite @Purchasing`).
- [ ] As a lab member with no special role, drop a filled EPIF PDF in a **new thread** in the
  purchasing channel: within about ten seconds the bot posts the *New Purchase Request* card with an
  Approve button. If it does not, run `@Purchasing logs 100` in the alert channel, find the lines around
  the drop, and record under Comments what they say (no `[message]` event at all points at the
  subscription; an exception points at the code).

## Comments
