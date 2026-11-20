# ADR 0022 — One running bot, one launcher

**Status:** accepted
**Date:** 2026-11-20

## Context

From 26 October to 19 November two copies of the Purchasing bot ran on **the server** at
once. `scripts/setup_autostart.py` installed two launchers on purpose — a Task Scheduler
task and a Startup-folder shortcut "as a backup" — so every reboot started the bot twice.
Nothing in the bot noticed.

Two copies are worse than they look. Each runs its own nudge timer, so lab members got
nudges twice whenever the two timers fired close together. Slack hands each event to one
connection, so `@Purchasing update` updated one copy and left the other on old code. And
each copy has its own write queue, which defeats the single writer that **the lock queue**
exists to guarantee.

## Decision

1. **Exactly one bot runs on a machine.** At startup, before it starts anything else, the
   bot claims a lock that the operating system holds for the life of the process. If
   another copy holds it, the new copy says so in the **Alert channel** and in the log,
   and exits without connecting to Slack's events.
2. **The lock is the operating system's, not a file's contents.** No process id is
   written or read. The operating system releases the lock when the process dies, so a
   crash or a power cut can never leave a stale lock that blocks the next start.
3. **Every start waits up to 15 seconds for the lock.** `restart` and `update` start the
   new copy a moment before the old one exits; the wait lets the handover succeed. A real
   second launcher arrives minutes later and is still refused. There is no "started by
   restart" flag.
4. **One launcher.** The server starts the bot from one Task Scheduler task,
   `Purchasing-Bot`, only.
   No Startup-folder shortcut, no "backup" launcher: the lock would refuse it on every
   reboot, and an alert that fires on every reboot teaches the admin to ignore it.
5. **The lock is per machine.** A copy on another machine with the same tokens is not
   detected. That is kept out by practice (**Pluto** does not run the bot while the
   server does), not by code.

## Consequences

- A refusal alert in the Alert channel always means something is wrong: a second
  launcher, or someone starting the bot by hand while it runs.
- `@Purchasing update` and `restart` reach the only copy there is.
- The nudge timer's read-then-record of the day's run is not safe against two copies on
  its own; it relies on this ADR. Do not remove the lock without fixing that.
- Moving the bot off Windows Task Scheduler (a service, another machine) must keep
  exactly one launcher.
