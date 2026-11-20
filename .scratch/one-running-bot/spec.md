# Spec — One running bot

**Status:** ready-for-agent
**Binding:** ADR 0022 (one running bot, one launcher), ADR 0010 decision 7 (failures are
reported in the **Alert channel**), ADR 0001 (tests first, no muted failures)
**Glossary:** `CONTEXT.md` — new: **The server**, **Pluto**. Uses **Alert channel**,
**Nudge**, **The lock queue**, **The request log**.

## Problem Statement

Lab members received every nudge twice. On 16 November the delivered nudge for one
request was posted twice in its thread, and the approver had to click "Not yet — set
expected date" on both copies. On 17 and 18 November every nudge went out twice.

The cause is that two copies of the Purchasing bot were running on **the server** at the
same time. `scripts/setup_autostart.py` deliberately installs two launchers — a Task
Scheduler task called `P-Bot` and a `P-Bot.lnk` shortcut in the Windows Startup folder,
described as a "backup" — so every reboot of the server starts the bot twice, about two
and a half minutes apart. The production log shows this after the reboots of 26 October
(11:26:29 and 11:28:53) and 19 November (17:21:48 and 17:24:24), with no `restart` or
`update` between them.

Nothing in the bot checks whether another copy is already running. Two copies cause
more than duplicate nudges:

- **Nudges.** Each copy runs its own 9:00 weekday timer. Each reads `nudge_run.json`,
  sends its nudges and only then records the day as done, so when the two timers fire
  within the same second or two, both send. Which days doubled depended on how far apart
  the two timers had drifted.
- **`update` and `restart` reach one copy.** Slack hands each event to one of the open
  connections. `@Purchasing update` therefore restarts one copy on new code and leaves
  the other running the old code. After the 3 November update, one copy most likely ran
  the 20 October code until the 19 November reboot, so some clicks were handled by old
  code.
- **Two workbook writers.** **The lock queue** exists so that exactly one thing writes to
  **the Purchasing Log** at a time. Two copies means two queues; two approvals arriving
  at different copies in the same moment could both pick the same first empty row.

## Solution

Exactly one Purchasing bot runs on **the server**. When the bot starts it claims a lock
that Windows holds for as long as that process is alive and releases the moment it dies,
however it dies — a clean exit, a crash or a power cut. A second copy started while the
first is running waits briefly, then gives up: it says so in the **Alert channel** —
"A second Purchasing bot tried to start on <host> and stopped — one is already running." —
writes the same to `p_bot.log`, and exits without ever connecting to Slack's events,
starting the write queue, the heartbeat or the nudge timer. Its console window stays open
on the server (`run_bot.bat` already ends in `pause`) so whoever is at the bench can see
why.

The brief wait is what keeps `@Purchasing restart` and `@Purchasing update` working:
both start the new copy a moment before the old one exits, so the new copy waits for the
old one's lock instead of being refused.

`setup_autostart.py` installs exactly one launcher, the Task Scheduler task `P-Bot`. It
no longer creates the Startup-folder shortcut, and it removes one it finds, along with
any Task Scheduler task left over under the old name `Purchasing-Bot`. `docs/SETUP.md`
names the task correctly and explains the refusal alert.

## User Stories

1. As a buyer, I want each nudge once, so that I am not reminded twice about the same request.
2. As an approver, I want one delivered-nudge card per request, so that I answer "Not yet" or "Delivered" once.
3. As a requester, I want the thread to carry one copy of each bot message, so that the thread stays readable.
4. As an admin, I want a second copy of the bot on the server to refuse to start, so that the duplicate problem cannot come back silently.
5. As an admin, I want the refused copy to post in the Alert channel, so that I learn a launcher misfired instead of discovering it from doubled nudges weeks later.
6. As an admin, I want the alert to name the computer it came from, so that I know which machine to look at.
7. As an admin, I want the refused copy's message in `p_bot.log` as well, so that the log tells the same story as Slack.
8. As an admin at the server, I want the refused copy's window to stay open with the reason on screen, so that I can see why a second bot window appeared.
9. As an admin, I want the refused copy to start nothing — no Slack connection, no write queue, no heartbeat, no nudge timer — so that it cannot handle a single click or send a single nudge.
10. As an admin, I want the bot to start normally after a power cut, so that a lab power outage never locks me out of my own bot.
11. As an admin, I want the bot to start normally after a crash, so that a crash never leaves something behind that blocks the next start.
12. As an admin, I want `@Purchasing restart` to keep working, so that restarting the bot from Slack does not take it down.
13. As an admin, I want `@Purchasing update` to keep working, so that deploying from GitHub stays a Slack keyword.
14. As an admin, I want a copy started while the old one is still shutting down to wait a few seconds rather than fail, so that a slow exit does not leave the lab without a bot.
15. As an admin, I want a genuinely second launcher — one that starts minutes later — still refused, so that the wait does not reopen the hole.
16. As an admin, I want `setup_autostart.py` to install exactly one launcher, so that a reboot starts exactly one bot.
17. As an admin, I want `setup_autostart.py` to remove the Startup-folder shortcut a previous run created, so that rerunning it repairs the server instead of leaving the old launcher behind.
18. As an admin, I want `setup_autostart.py` to remove any old `Purchasing-Bot` task, so that a launcher from an older setup cannot add a third copy.
19. As an admin, I want `docs/SETUP.md` to name the task `P-Bot`, so that the commands it gives me find the task that exists.
20. As an admin, I want `docs/SETUP.md` to explain the refusal alert, so that I know what it means and what to do when I see it.
21. As the developer, I want the lock file to live next to the roster, the request log and the log file, so that it is always on the server's disk and never synced anywhere.
22. As the developer, I want the lock file ignored by git, so that it never shows up as a change or gets pulled onto another machine.
23. As the developer, I want the lock tested against a real second process, so that the test proves what happens on the server rather than what a mock was told to do.
24. As the developer, I want the existing write queue, heartbeat, nudge timer and startup alert unchanged once the lock is held, so that a normal start behaves exactly as it does today.
25. As a future agent, I want ADR 0022 to record why there is only one launcher, so that nobody re-adds a "backup" launcher.

## Implementation Decisions

- **New module for the lock.** A small module in `src/` owns claiming the lock. It
  exposes one function that takes the lock file's path and the number of seconds to
  wait, and returns a held-lock object or `None`. It knows nothing about Slack, logging
  to the Alert channel or the rest of startup, because it must be testable on its own
  against a real second process.
- **The lock is held by the operating system, never inferred from a file's contents.**
  On Windows (the server) it is a byte-range lock on the lock file through `msvcrt`; on
  Linux (CI) it is `fcntl.flock`. The lock file's contents are irrelevant and it is never
  deleted. No process id is written or read. This is what makes a crash or power cut
  harmless: the operating system releases the lock when the process dies.
- **The held lock is kept for the life of the process.** The module keeps a reference to
  the open lock file at module level so it is never closed by garbage collection while
  the bot runs. The file handle must not be inheritable by child processes (Python's
  default), so the copy that `restart` spawns does not inherit the old copy's lock.
- **Waiting.** The claim retries every half second until the wait runs out. Every start
  uses the same wait — there is no "started by restart" flag. The wait is 15 seconds,
  held in `config` beside the lock file's path.
- **Where the lock file lives.** `config` names it: `purchasing_bot.lock` in
  `config.BASE_DIR`, next to `roster.json`, `requests.json` and `p_bot.log`. It is added
  to `.gitignore`.
- **Where startup claims it.** In `main()` in the application module, after logging is
  set up and the startup banner is written, and before anything else runs: before the
  purchasing-channel check, the write queue, the heartbeat, the nudge timer, the startup
  alert and the Socket Mode connection.
- **What a refused start does.** It writes one `ERROR` line to the log, posts the refusal
  to the **Alert channel** through the existing `slack_io.alert_admins` (a Web API post,
  not a Socket Mode connection), and exits with status 1. The alert text is exactly
  `🛑 A second Purchasing bot tried to start on <host> and stopped — one is already running.`
  with `<host>` from `platform.node()`, the same source the startup alert uses. If the
  Alert channel is unset, `alert_admins` already logs and returns; the refused copy still
  exits.
- **`restart` and `update` are unchanged.** They already start the new copy and then end
  the old one with `os._exit(0)`, which releases the lock; the 15-second wait covers the
  gap.
- **The autostart script.** `scripts/setup_autostart.py` stops creating the Startup-folder
  shortcut: the function that creates it is removed, and so is the "Bot will also start via
  Startup folder" output. A new step removes `P-Bot.lnk` and the legacy `EPIF-Bot.lnk` from
  the Startup folder if present, reporting each removal. The PowerShell that registers the
  task also unregisters a task named `Purchasing-Bot`, alongside the `P-Bot` and `EPIF-Bot`
  names it already unregisters. The Startup-folder path is resolved from `%APPDATA%` as
  today, and the removal step takes the folder as an argument so it can be tested against
  a temporary folder.
- **Docs.** `docs/SETUP.md`'s auto-start section says the script installs one Task
  Scheduler task named `P-Bot` (every `Purchasing-Bot` in its commands becomes `P-Bot`),
  drops the "backup startup folder shortcut" lines, and gains a troubleshooting entry for
  the refusal alert: it means a second copy tried to start on that computer; check for a
  second launcher (`Get-ScheduledTask`, the Startup folder) and rerun the script.
- **Rollout is two developer tickets.** One can be done today, before any code lands:
  stop one of the two running copies and delete the Startup-folder shortcut. The other
  follows the merge: `@Purchasing update`, rerun `setup_autostart.py` at the server,
  reboot, and check that exactly one startup alert and no refusal alert appear.

## Testing Decisions

- Test what an admin would observe, not how the code is arranged: whether a second start
  is refused, what the Alert channel receives, what did or did not start, and what is on
  disk in the Startup folder afterwards. A test that passes with the lock never taken is
  the wrong test.
- **The lock** is tested against a real second process. The test starts a child Python
  process (`sys.executable`) that claims the lock on a file under `tmp_path` and then
  waits; the test claims the same file in-process. Three behaviours:
  - while the child holds it, a claim with a short wait (about 1 second) returns `None`
    and takes at least that long;
  - after the child is killed (`kill()`, not a clean exit — this is the power-cut case),
    a claim returns a held lock straight away;
  - when the child is told to exit partway through the wait, a claim with a longer wait
    returns a held lock (the `restart` case).
  These tests fake nothing. There is no prior art for a child process in this suite; keep
  the child's script inline and its run short.
- **Startup (`main()`)** is tested with the lock already held by a child process, the lock
  path and wait in `config` monkeypatched to `tmp_path` and about 1 second, and every
  start function (`queue_worker.start_queue_worker`, `heartbeat.start_heartbeat`,
  `nudge.start_nudge_scheduler`, `heartbeat.send_startup_alert`,
  `path_validator.check_purchasing_channel`, `SocketModeHandler`) replaced with a recorder.
  `slack_io.alert_admins` is recorded too, since it is the Slack call. Assert `SystemExit`
  with code 1, exactly one alert whose text contains `A second Purchasing bot tried to start`
  and `one is already running`, an `ERROR` record saying the same, and none of the start
  functions called. A second test with the lock free asserts they are all called, so the
  happy path is unchanged. Prior art for config monkeypatching and the startup alert:
  `tests/test_24_startup_storage_check.py`.
- **The autostart script** is tested with `subprocess.run` replaced by a recorder (no
  PowerShell on CI) and the Startup folder pointed at `tmp_path` through `APPDATA`:
  running `main()` leaves no `P-Bot.lnk` in it, removes a `P-Bot.lnk` and an `EPIF-Bot.lnk`
  placed there beforehand, and the recorded PowerShell that registers the task unregisters
  `Purchasing-Bot`. No recorded PowerShell creates a shortcut.
- **Docs** are checked by text: `docs/SETUP.md` contains no `Purchasing-Bot` and mentions
  the refusal alert. Prior art: `tests/test_59_readme_and_docs.py`.

## Out of Scope

- A second copy on another machine. The lock is per machine. **Pluto** holding the lab's
  Slack tokens is handled by the developer not running the bot there while the server
  does (see `CONTEXT.md`), not by code.
- Making the nudge timer itself safe against two copies (an atomic read-and-record of the
  day's run). With one copy guaranteed, it is not needed.
- Showing the process, host or start time on the health screen.
- Changing how `restart` and `update` start the new copy.
- Running the bot as a Windows service instead of a Task Scheduler task.
- Cleaning up nudge cards already posted twice.

## Further Notes

- The developer can blank `SLACK_BOT_TOKEN` and `SLACK_APP_TOKEN` in pluto's `.env` so a
  mistaken `python app.py` there fails at once instead of quietly becoming a second bot.
  Tests and CI do not need real tokens. This is a one-line change on pluto, not part of
  any ticket.
- The 12 November traceback in `bom.build_bom_workbook` (`StopIteration`) in the same
  production log is unrelated to this effort.
