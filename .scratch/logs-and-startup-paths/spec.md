# Spec — full logs from Slack, and a startup check that names bad storage paths

**Status:** `ready-for-agent`

Written 2026-09-21, after tickets 12–22 landed. Covers ticket set **23 onward**.
Convert to tickets in the order the Implementation Decisions section is written:
Part A is one ticket, Part B is another. They share no code and neither blocks
the other.

Read before implementing anything here:

- `CONTEXT.md` — the glossary. **Admin**, **Keyword**, **Alert channel** and
  **The Purchasing Log** are used exactly as it defines them.
- `docs/adr/0001-tests-first-and-no-muted-failures.md` — binding on all test work.
  One existing test changes expectation **by design** in Part A; see Testing
  Decisions. That is not a licence to weaken any other test.
- `docs/agents/issue-tracker.md` — status words and `.scratch/` conventions.

---

## Problem Statement

**The admin cannot read the bot's logs from Slack when something goes wrong.**
Isaac runs the bot on a production server he has to walk to. His only remote view
of what happened is `@Purchasing logs [n]`, and it lies twice about how much it
shows. It quietly clamps any request above 100 lines down to 100. Then it quietly
cuts the result to the last 2,800 characters, which at this log's line length is
roughly fifteen lines. Asking for `logs 500` returns a reply headed "Last 100
lines" that holds about fifteen. Reading an incident as a stack of thread replies
is slow even when it works. There is also no way to see `rejections.log`
remotely at all.

**A mis-configured storage path is invisible until it destroys a real request.**
On 2026-09-21 the server's `.env` still held the setup template's literal
`C:\Users\USERNAME\OneDrive - …` for all four storage paths. The bot booted,
posted "🟢 P-Bot Online & Ready" to the alert channel, and said nothing more.
The first anyone learned of it was Charlie approving a real purchase request and
the workbook write failing with `FileNotFoundError`. The template in
`docs/SETUP.md` invites the mistake: `USERNAME` reads like something the bot
fills in.

## Solution

**Logs become something the admin asks for in one place and receives whole.**
Every form of the `logs` keyword works only in the alert channel. That is the one
channel where logs, which carry Slack IDs, names and purchase details, may be
posted. Asked anywhere else, the bot says where to ask instead.

- `@Purchasing logs [n]` has no line cap. If the last *n* lines fit in one
  message, they post inline as today. If they don't, the same *n* lines arrive as
  a file in the thread. Nothing is silently dropped.
- `@Purchasing logs all` posts the whole current `p_bot.log` as a file in the
  thread.
- `@Purchasing logs rejections` posts the whole `rejections.log` as a file in the
  thread.

Every file has Slack tokens and webhook URLs masked, exactly as the inline view
does today.

**Startup names what is wrong with storage.** When the bot boots, it checks the
four storage paths (the Purchasing Log workbook, the EPIFs, Order-Confirmations
and Quotes folders). If any path is unset, still holds a template placeholder, or
does not exist, the startup alert in the alert channel changes colour and lists
each bad setting, its value and the reason. The bot still boots; nothing refuses
to start. When all four are fine, the startup alert is unchanged.

**The setup template stops looking fillable.** `docs/SETUP.md` shows
`<your-windows-account>` where it used to show `USERNAME`, with one line saying
the bot does not fill it in.

## User Stories

### Reading logs

1. As an admin, I want `@Purchasing logs 500` to give me exactly 500 lines, so that I can trust what I am reading is the whole window I asked for.
2. As an admin, I want a long tail to arrive as a file rather than be cut short, so that I never lose the lines that explain an error.
3. As an admin, I want a short tail to still post inline, so that a quick glance stays a quick glance.
4. As an admin, I want the reply to state how many lines it holds, so that I know when the log had fewer lines than I asked for.
5. As an admin, I want `@Purchasing logs all` to send me the whole current log file, so that I can open it in an editor and search it instead of scrolling a thread.
6. As an admin, I want `@Purchasing logs rejections` to send me the whole `rejections.log`, so that I can see why submissions were refused without walking to the server.
7. As an admin, I want `@Purchasing logs` with no number to keep showing the last 30 lines, so that my existing habit still works.
8. As an admin, I want `@Purchasing log …` to behave the same as `@Purchasing logs …`, so that the existing alias keeps working.
9. As an admin, I want every file the bot sends to have Slack tokens and webhook URLs masked, so that posting a log never leaks a credential.
10. As an admin, I want the file to be named after what it holds, so that several downloads in my folder are distinguishable.
11. As an admin, I want a clear reply when the log file does not exist, so that I can tell "no log" from "the bot is down".
12. As an admin, I want a clear reply when the upload fails, including Slack's error, so that I know whether it is a scope problem or a transient one.
13. As an admin, I want `@Purchasing logs banana` to tell me the three forms it understands, so that a typo is not silently treated as something else.

### Where logs may be asked for

14. As an admin, I want log commands to work only in the alert channel, so that lab members' names and purchase details are never posted to a channel where they don't belong.
15. As an admin asking in the wrong channel or a DM, I want the bot to reply naming the alert channel, so that I know where to ask instead of wondering whether it heard me.
16. As an admin, I want the bot to say plainly when the alert channel is not configured, so that a missing setting does not look like a refusal.
17. As a lab member who is not an admin, I want the existing "restricted to bot administrators" reply wherever I ask, so that the admin gate is unchanged.
18. As the lab, I want no log text or file posted anywhere except the alert channel, so that the refusal itself never carries log content.

### Startup storage check

19. As an admin, I want the startup alert to name any storage path that does not exist, so that I learn about it before an approval fails.
20. As an admin, I want the startup alert to call out a path still holding a template placeholder such as `USERNAME`, so that the actual mistake is named rather than only its symptom.
21. As an admin, I want the startup alert to name a storage setting that is unset, so that an empty `.env` line is caught too.
22. As an admin, I want each problem listed with its `.env` setting name, its value and the reason, so that I know exactly which line to edit.
23. As an admin, I want the startup alert to look visibly different when storage has problems, so that I notice it among routine boot messages.
24. As an admin, I want the startup alert unchanged when all four paths are fine, so that a healthy boot stays quiet.
25. As an admin, I want the bot to keep booting even with bad storage paths, so that the lab can still use everything that does not touch storage, and the service does not restart in a loop.
26. As an admin, I want storage problems written to the log at ERROR level too, so that they are recorded even when the alert channel is unset or Slack is unreachable.
27. As an admin, I want the workbook checked as a file and the three folders checked as folders, so that a path pointing at the wrong kind of thing is caught.

### Setup documentation

28. As whoever sets up the server next, I want the `.env` example to show an obviously unfinished placeholder, so that I do not paste it in unchanged.
29. As whoever sets up the server next, I want one sentence telling me the bot does not fill the placeholder in, so that I know it is my job.

## Implementation Decisions

### Part A — log commands (ticket 23)

**A1. One channel rule for every `logs` form.** The handler checks, in this
order:

1. The caller is an admin. If not, reply with the existing
   `🔒 This command is restricted to bot administrators.` wherever they asked.
   This is unchanged.
2. `config.ADMIN_ALERT_CHANNEL` is set. If not, reply in the thread:
   `⚠️ Logs are unavailable: ADMIN_ALERT_CHANNEL is not set in the bot's .env.`
3. The message's channel equals `config.ADMIN_ALERT_CHANNEL`. If not, reply in
   the thread: `🔒 Logs are only available in <#{ADMIN_ALERT_CHANNEL}>.` (Slack's
   channel-link syntax, so it renders as a clickable channel name). Nothing else
   is posted and no file is uploaded.

No new setting is added. The alert channel is the logs channel.

**A2. The form is the word after `logs`/`log`.** It is read from the message the
same way the number is read today:

| After the keyword | Form |
|---|---|
| nothing | tail, 30 lines |
| a whole number *n* | tail, *n* lines; *n* below 1 becomes 1; **no upper cap** |
| `all` | whole `p_bot.log` as a file |
| `rejections` | whole `rejections.log` as a file |
| anything else | reply `Unknown logs option. Use \`logs [n]\`, \`logs all\`, or \`logs rejections\`.` and nothing else |

Matching `all` and `rejections` is case-insensitive. No new keyword tuples are
added. `logs` and `log` stay the only first words, and the second word is the
handler's business.

**A3. Tail: inline when it fits, file when it doesn't.** Read the last *n* lines
of `config.LOG_FILE` and mask them. The inline limit stays **2,800 characters**,
the same value as today, but it now picks the delivery method instead of trimming:

- masked text ≤ 2,800 characters → post inline in the thread, headed
  `📋 *Recent Bot Logs (Last {k} lines):*`, where *k* is the number of lines
  actually returned, which is fewer than *n* when the file is shorter;
- masked text > 2,800 characters → upload as a file in the thread (A5), with
  filename `p_bot_last_{k}_lines.log` and comment
  `📋 Last {k} lines of p_bot.log (too long to post inline).`

The 100-line clamp is removed from the handler and from the admin read function.
The 2,800-character trim is removed. There is no path left where lines are
dropped without the reply saying so.

**A4. Whole files.**

- `logs all` → whole `config.LOG_FILE`, masked, filename `p_bot.log`, comment
  `📋 Full p_bot.log ({k} lines).`
- `logs rejections` → whole `config.REJECTIONS_LOG_FILE`, masked, filename
  `rejections.log`, comment `📋 Full rejections.log ({k} lines).`

"Whole" means the current file only. Rotated copies (`p_bot.log.1` … `.5`) are
not included. The file rotates at 10 MB, so reading it into memory is fine.

**A5. How a file is sent.** Use `client.files_upload_v2` with `channel` set to
the message's channel, `thread_ts` set to the message's thread, **`content` set
to the masked text**, `filename`, `title` equal to the filename, and
`initial_comment` set to the comment from A3/A4. The raw file on disk is never
handed to Slack, so masking cannot be bypassed. The template command's fallback
to the legacy `files_upload` is **not** copied here.

**A6. One masking function.** The three masking substitutions in the admin
module's tail reader (`xoxb-…`, `xapp-…`, `hooks.slack.com/services/…`) move into
a single function that every path in A3–A4 uses. The admin module gains one read
function that returns the masked text and its line count for "last *n* lines" or
"whole file" of a given path. The existing tail reader keeps its signature for its
current callers, minus the 100 clamp.

**A7. Failure replies, in the thread, never an upload:**

- the file does not exist → `Log file not found at \`{path}\`.`, the same text as
  today, now for all three forms;
- reading raises → `Error reading log file: {error}`, as today;
- `files_upload_v2` raises → `⚠️ Could not upload {filename}: {error}` and log
  the exception at WARNING.

**A8. Help text and glossary.** In the help source that App Home and the help
reply share, replace the single `logs [n]` line with three:

- `` `@Purchasing logs [n]` `` — _(Admin Only, alert channel)_ Last *n* lines (default 30); long output arrives as a file.
- `` `@Purchasing logs all` `` — _(Admin Only, alert channel)_ The whole current log file.
- `` `@Purchasing logs rejections` `` — _(Admin Only, alert channel)_ The whole rejections log.

In `CONTEXT.md`, under **Alert channel**, add one sentence: *It is also the only
place the `logs` keyword answers, because logs carry names and purchase details.*

### Part B — startup storage check (ticket 24)

**B1. A pure check in the path-validation module.** Add a function that inspects
the four storage paths and returns a list of problems, empty when all are fine.
Each problem carries the `.env` setting name, the value, and a reason. The four,
in this order, are:

| Setting | Config value | Must be |
|---|---|---|
| `PURCHASING_LOG_PATH` | `WORKBOOK_PATH` | an existing **file** |
| `EPIFS_DIR` | `EPIFS_DIR` | an existing **folder** |
| `CONFIRMATIONS_DIR` | `CONFIRMATIONS_DIR` | an existing **folder** |
| `QUOTES_DIR` | `QUOTES_DIR` | an existing **folder** |

Reasons are checked in this order, and only the first that applies is reported:

1. empty or unset → `not set`
2. any path component (split on both `\` and `/`) is exactly `USERNAME`, or
   contains `<` or `>` → `still contains a template placeholder`
3. the path exists but is the wrong kind (a folder where a file is expected, or
   the reverse) → `exists but is not a file` / `exists but is not a folder`
4. the path does not exist → `does not exist`

The function reads `config` attributes at call time, so tests can monkeypatch
them. It does no I/O beyond existence and kind checks and never prompts. The
module's interactive prompt functions are untouched.

**B2. The startup alert reports it.** `heartbeat.send_startup_alert(client)`
calls the B1 check.

- **Before** its existing "no alert channel / no client" early return, it logs
  each problem at ERROR as
  `Storage path problem: {SETTING} = {value!r} — {reason}`. This way the problems
  are recorded even when no alert can be sent.
- With **no problems**, the alert is exactly what it is today.
- With **one or more problems**:
  - the header text becomes `🟠 P-Bot Online — storage paths need attention`;
  - a section is inserted directly after the header-and-fields section, reading
    `*Storage path problems:*` followed by one line per problem,
    `• \`{SETTING}\` = \`{value}\` — {reason}`, and then the line
    `_Workbook writes and EPIF saves will fail until these are fixed in the server's .env and the bot is restarted._`;
  - the fallback `text` gains the same lines.

The bot continues to boot either way. `main()` is not changed.

**B3. The template.** In `docs/SETUP.md`, every `C:\Users\USERNAME\…` example
becomes `C:\Users\<your-windows-account>\…`. Directly under the `.env` example
block, add: *Replace `<your-windows-account>` with the Windows account OneDrive
is signed in under on this machine. The bot does not fill it in, and the startup
alert will flag it if you forget.* The four `example` strings in the
path-validation module's `STORAGE_PATHS` get the same substitution.

## Testing Decisions

A good test here drives the bot the way Slack does and asserts on what the bot
asked Slack to do: the reply text, or the upload's channel, thread, filename and
content. It never asserts on which internal function was called. Use real files
in `tmp_path` and monkeypatch `config`; don't mock the file reads.

**Part A: one seam, `app.dispatch_command`,** with a `MagicMock` client and
`say`, as `test_dispatch_logs_restricted_to_admins` does today. Monkeypatch
`config.ADMIN_SLACK_USER_IDS`, `config.ADMIN_ALERT_CHANNEL`, `config.LOG_FILE`
and `config.REJECTIONS_LOG_FILE` to a test admin, a test channel and real
temporary files. The cases must include:

- a 500-line log, `logs 500` in the alert channel → one upload whose `content`
  has exactly 500 lines, the last of which is the file's last line; no inline
  reply;
- a 5-line log, `logs 3` → inline reply holding exactly those 3 lines, headed
  "Last 3 lines", and no upload;
- `logs 50` on a 10-line file → the header says 10;
- `logs all` → one upload with filename `p_bot.log` whose content equals the whole
  file after masking;
- `logs rejections` → one upload with filename `rejections.log` from the
  rejections file;
- a log containing `xoxb-…`, `xapp-…` and a webhook URL → every upload's
  `content` holds the masked forms and none of the originals;
- an admin in another channel → exactly one reply, containing
  `<#{alert channel}>`, and **no** `files_upload_v2` call and no log text;
- a non-admin in the alert channel → the existing padlock reply;
- `ADMIN_ALERT_CHANNEL` empty → the "unavailable" reply;
- `logs banana` → the unknown-option reply and no upload;
- missing log file → "Log file not found", no upload;
- `files_upload_v2` raising → the "Could not upload" reply.

**One existing test changes by design.** `test_dispatch_logs_restricted_to_admins`
sends `logs 20` from `C123` and expects the tail. Under A1 that is refused. The
fix is to set `config.ADMIN_ALERT_CHANNEL = "C123"` in that test. The assertion
stays as it is. Record this in the ticket's `## Comments`.

`test_get_tail_logs_and_token_masking` stays green unchanged. It must, because
it pins the masking.

**Part B: one seam, `heartbeat.send_startup_alert(client)`,** with a `MagicMock`
client and a monkeypatched `config.ADMIN_ALERT_CHANNEL`. Point the four path
settings into `tmp_path`. Cases:

- all four real (a file and three folders) → header is still
  `🟢 P-Bot Online & Ready` and no text anywhere in the posted blocks contains
  "Storage path problems";
- the workbook path containing a `USERNAME` component → the orange header, and
  the problems section names `PURCHASING_LOG_PATH` with reason
  `still contains a template placeholder`;
- one folder missing → only that setting is named, with `does not exist`;
- the workbook path pointing at a folder → `exists but is not a file`;
- an empty setting → `not set`;
- `ADMIN_ALERT_CHANNEL` empty with a bad path → returns `False`, posts nothing,
  and `caplog` holds the ERROR line naming the setting.

**Prior art:** `tests/test_monitoring_and_queue.py`
(`test_dispatch_logs_restricted_to_admins`, `test_get_tail_logs_and_token_masking`,
`test_send_startup_alert`) and `tests/test_onboarding_and_commands.py`
(`test_template_command` asserts on `files_upload_v2`).
`tests/test_15_purchasing_channel.py` shows the startup-check-with-`caplog`
pattern.

Name the new test files `tests/test_23_logs_from_slack.py` and
`tests/test_24_startup_storage_check.py`, matching the per-ticket convention.

## Out of Scope

- Rotated log copies (`p_bot.log.1` … `.5`) and any `logs` form that reaches them.
- Any way to edit `.env` or change paths from Slack. Fixing a bad path stays a
  person at the server.
- Refusing to boot on bad storage paths.
- Expanding `%USERNAME%` or `~` in `.env` values.
- `TEMPLATE_DIR`. The template command already reports missing files itself.
- Blocking or pre-checking approvals when the workbook is missing. The existing
  failure reply stays as it is.
- Changing `@Purchasing health`. It already reports storage health.
- The legacy `files_upload` fallback.
- The mislabelled `Log Path:` line in the startup alert's fallback text, which
  shows the workbook path. Leave it; Part B adds its lines beside it.

## Further Notes

- **The production fix for 2026-09-21 is a human task, not in this spec.** Edit
  the server's `.env` (`C:\Isaac_programs\Slackbot\.env`) so the four path lines
  read `C:\Users\ilegault\…`, confirm the Hirst-Lab OneDrive shortcut is synced
  under that account, restart the service, check `@Purchasing health`, and have
  Charlie re-approve the DB15 breakout board request. Part B would have caught
  this at boot.
- **Slack scope:** uploads need `files:write`. The template command already
  uploads with `files_upload_v2`, so the scope is expected to be present. If an
  upload fails with `missing_scope`, that is a `human-task` (add the scope and
  reinstall), not something to code around.
- Neither ticket may assume a merge deploys. Isaac merges, then runs
  `@Purchasing update` from the alert channel.
