# ADR 0021 — App Home and help link the Purchasing Log

**Status:** accepted
**Date:** 2026-11-06
**Supersedes:** ADR 0002 decision 9, the half that says App Home "does **not** link the
Purchasing Log". App Home still carries the four stage definitions.

## Context

ADR 0002 ruled out a link to the Purchasing Log on App Home, and ticket 22 repeated it,
without recording why. The developer now wants lab members to reach the workbook from
Slack: the log is what the lab reads and acts on, and getting to it by browsing OneDrive
shortcuts is the friction. The lab's file hosting is expected to move to a different
cloud soon, so the link is a stop-gap and must survive that move without a code change.

Slack rejects an entire `views.publish` call when a button's `url` is malformed, so a bad
value would blank everyone's Home tab, not just drop the button.

## Decision

1. **App Home and `/purchasing-help` both show the Log link**, to everyone. App Home: an
   **Open Purchasing Log** button on the Welcome section. Help: one clickable line near
   the top. Both render from one shared constant, like the stage definitions.
2. **The URL comes from one `.env` setting, `PURCHASING_LOG_URL`.** No default. It is
   host-neutral: any `http://` or `https://` address is accepted, nothing is parsed out
   of it, and no label names SharePoint or OneDrive. Moving clouds is one `.env` line and
   a restart.
3. **It is a plain link.** The bot never reads, writes or checks access through it;
   Microsoft's sign-in decides who gets in. It is not a storage setting and does not join
   the startup path check (ADR 0009's six storage settings stay six).
4. **Missing or malformed is shown, not hidden.** A value that is empty or does not
   start with `http://` / `https://` is treated as not set: App Home and help show
   "The Purchasing Log link isn't set up yet. Ask an admin." in place of the link, the
   bot logs a warning, and `@Purchasing health` shows `Log link: not set` (otherwise
   `Log link: set`). No startup alert.
5. **Only App Home and help.** Thread cards, buyer DMs and nudges do not carry the link.

## Consequences

- A wrong URL can no longer blank App Home; at worst it shows the not-set line.
- Setting or changing the link is a visit to the production server, the same visit a
  cloud move already needs for `PURCHASING_LOG_PATH`.
- A per-request link to the request's own row is left for whatever host replaces this one.
