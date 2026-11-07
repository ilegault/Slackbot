# Spec — App Home and help link the Purchasing Log

**Status:** ready-for-agent
**Binding:** ADR 0021 (App Home and help link the Purchasing Log — supersedes the "no link"
half of ADR 0002 decision 9), ADR 0009 (storage settings stay six; health screen), ADR 0010
decision 5 (help is packed into section blocks), ADR 0001 (tests first, no muted failures)
**Glossary:** `CONTEXT.md` — new: **Log link**. Distinct from **Link** and **Item link**.

## Problem Statement

**The Purchasing Log** is what the lab reads and acts on, but nothing in Slack leads to it.
A lab member who wants to check where their order stands has to find the workbook by
browsing OneDrive shortcuts into a shared folder. App Home names the file
(`Purchasing-Log.xlsx`) without letting anyone open it. ADR 0002 had ruled a link out; the
developer has reversed that because access is the point. The lab's file hosting is
expected to move to a different cloud soon, so the link is a stop-gap that must survive
that move without a code change.

## Solution

App Home shows an **Open Purchasing Log** button on its Welcome section, and
`/purchasing-help` shows one clickable "Purchasing Log" line near the top. Both open the
**Log link** in the browser; Microsoft's own sign-in decides who gets in. The address
comes from one `.env` setting, `PURCHASING_LOG_URL`, so moving clouds is one line and a
restart. If the setting is missing or is not a web address, both surfaces say so plainly
instead of the link, the bot logs a warning, and `@Purchasing health` shows
`Log link: not set`. A bad value can never reach Slack, so it can never blank App Home.

## User Stories

1. As a lab member, I want an Open Purchasing Log button on App Home, so that I can open the workbook without hunting through OneDrive.
2. As a lab member, I want the button near the top of App Home, so that I see it without scrolling.
3. As a lab member, I want `/purchasing-help` to carry the same link, so that I can reach the log from any channel or DM.
4. As a lab member, I want the link to open in my browser and let Microsoft ask me to sign in, so that the bot never has to know who may see the log.
5. As a requester, I want to open the log after approval, so that I can see my row and its stage myself.
6. As a buyer, I want the log one click away, so that I can check what is approved and not yet processed.
7. As an approver, I want the log one click away, so that I can review spending without asking a grad student.
8. As a lab member, when the link has not been set, I want to read "The Purchasing Log link isn't set up yet. Ask an admin." where the link would be, so that I know the log exists and who can fix it.
9. As a lab member, I want App Home to still load when the link setting is wrong, so that one typo on the server does not take away the whole Home tab.
10. As an admin, I want a malformed `PURCHASING_LOG_URL` treated exactly like a missing one, so that there is one failure mode to recognise.
11. As an admin, I want `@Purchasing health` to show `Log link: set` or `Log link: not set`, so that I can see at a glance whether the setting took after a restart.
12. As an admin, I want a warning in `p_bot.log` when the setting is present but is not a web address, so that I can tell a typo from a missing line.
13. As an admin, I want the link to be any `http://` or `https://` address with no host-specific checks, so that moving the log to another cloud is only an `.env` change.
14. As an admin, I want no label to say SharePoint or OneDrive, so that the wording stays right after the move.
15. As an admin, I want the Log link kept out of the startup path check, so that a missing link never raises a storage alert or blocks boot.
16. As an admin, I want `docs/SETUP.md` to list `PURCHASING_LOG_URL` with an example, so that whoever sets up the server knows the setting exists.
17. As a lab member clicking the button, I want no error triangle on it, so that the button does not look broken after it opens the link.
18. As a lab member clicking the button, I want the bot to post nothing, so that opening the log stays silent.
19. As the developer, I want App Home and help to render the link from one shared constant, so that the two surfaces cannot drift (as with the stage definitions).
20. As the developer, I want thread cards, buyer DMs and nudges left exactly as they are, so that this change stays small.

## Implementation Decisions

- **The setting.** `config` gains one constant read from the `PURCHASING_LOG_URL` environment variable, stripped, with no default (empty when unset), next to the other `.env` reads. It is **not** added to `config.STORAGE_SETTINGS`: the bot never reads or writes through it, and ADR 0009's six storage settings stay six.
- **What counts as set.** The value is the Log link only if, after stripping, it starts with `http://` or `https://` (case-insensitive) and contains no whitespace. Anything else — empty, `www.…`, a Windows path, a value with spaces — is "not set". No `https://` is added (unlike item links in ADR 0020): the admin pastes the full address they copied. This rule is a pure function in `text_rules` that takes the raw string and returns the URL or `None`, because the same rule must give the same answer on App Home, in help and on the health screen, and a pure function is testable without Slack.
- **Shared text in `blocks`.** One module-level constant holds the not-set sentence: `The Purchasing Log link isn't set up yet. Ask an admin.` One module-level constant holds the button and link label: `Open Purchasing Log`. Both `build_app_home_view()` and `get_help_message()` use them; neither carries a second copy of either string.
- **Read at render time.** The builders read `config`'s constant each time they render, not once at import, so tests can set it and a value fixed on the server takes effect at the next restart without other changes.
- **App Home.** The Welcome section (the one under the "Hirst Lab Purchasing Bot" header) gets a button accessory: `type: button`, text `Open Purchasing Log`, `url` = the Log link, a new action id held in `config` (e.g. `ACTION_OPEN_PURCHASING_LOG`). When the link is not set, the section has no accessory and its text gains the not-set sentence on its own line. The Welcome text is otherwise unchanged.
- **Help.** `get_help_message()` gains one line directly after the opening "🤖 *Hirst Lab Purchasing Bot*" line: `*Purchasing Log:* <URL|Open Purchasing Log>` when set, or `*Purchasing Log:* ` followed by the not-set sentence when not. Help stays plain mrkdwn text packed by `chunk_mrkdwn`.
- **The warning.** When the raw setting is non-empty but not a web address, rendering App Home or help logs one `WARNING` through `logging.getLogger(__name__)` naming `PURCHASING_LOG_URL` and the reason (not a web address). An empty setting logs nothing. The warning lives in the `blocks` layer, not in the pure function, which stays side-effect free.
- **Health screen.** `admin.get_system_health()` adds one field saying whether the Log link is set, using the same pure function; `admin.build_health_blocks()` renders one line, `Log link: set` or `Log link: not set`, outside the storage section. The URL itself is not shown.
- **The click.** Slack sends a `block_actions` payload even for a link button and shows an error triangle if it is not acknowledged. `src/app.py` registers an `@app.action` listener for the new action id that calls `ack()` and does nothing else — no post, no view update, no DM. One success line at `DEBUG` is allowed; nothing at `INFO` or above.
- **Docs.** `docs/SETUP.md` lists `PURCHASING_LOG_URL` in its `.env` example and its settings table, described as the browser link to the Purchasing Log, optional, not a storage path.
- **Server setting is a human task.** After the code is merged and deployed, the developer copies the workbook's sharing link and adds `PURCHASING_LOG_URL=<link>` to the production server's `.env`, then restarts. No agent can do this.

## Testing Decisions

- Test what a lab member would see, not how the code is arranged: the blocks of the App Home view, the text of help, the health blocks, and the absence of any Slack call on a click. A test that would pass with the button pointed at the wrong address, or with the not-set sentence missing, is the wrong test.
- Set the setting by monkeypatching the `config` constant (good, empty, malformed) — never by editing a real `.env`. Nothing touches the real workbook, roster or network.
- **App Home and help** (`blocks.build_app_home_view`, `blocks.get_help_message`): with a good URL, the Welcome section's accessory is a button whose `url` equals that exact URL and whose text is `Open Purchasing Log`, and help contains `<URL|Open Purchasing Log>`; with an empty value and with a malformed value (`www.example.com/log`, `C:\Users\x\Purchasing-Log.xlsx`, `https://exa mple.com`), no block anywhere in the view has a `url` key, and both surfaces contain the not-set sentence. Assert the two surfaces use the shared constants (prior art: the shared-constant tests in `tests/test_09_app_home_help.py` and `tests/test_22_live_roster_panel.py`). A malformed value produces a `WARNING` record naming `PURCHASING_LOG_URL`; an empty one produces none (use `caplog`).
- **Health** (`admin.build_health_blocks` fed by `admin.get_system_health`): shows `Log link: set` with a good URL and `Log link: not set` with an empty or malformed one, and the storage section still lists exactly the six storage settings. Prior art: `tests/test_55_health_paths.py`.
- **The click** (real Bolt listener registry, not a monkeypatched stand-in): a `block_actions` payload for the new action id is acknowledged and the fake Slack client records no `chat_postMessage`, `chat_update`, `chat_postEphemeral` or `views_publish` call. Prior art for finding the real registry and a fake client: `tests/test_12_denials.py`, `tests/test_62_ignore_slack_events.py`.
- The pure rule in `text_rules` is covered through the three seams above; it needs no tests of its own beyond what the seams exercise.

## Out of Scope

- A Log link on thread cards, buyer DMs, the DM card, nudge messages or the email draft.
- A link to a request's own row in the workbook.
- Reading the workbook to show any of its contents on App Home.
- Checking or managing who may open the link; visiting the URL; converting the local `PURCHASING_LOG_PATH` into a web address.
- Setting the link from Slack (an admin keyword or App Home form), or storing it anywhere but `.env`.
- Adding the Log link to the startup path check or the admin startup alert.
- Rewording the rest of App Home or help, including the Welcome sentence that mentions OneDrive.
- `CONTEXT.md` and the ADRs — already written for this effort.

## Further Notes

- This is a stop-gap: the developer expects the lab's file hosting to move to a different cloud. When it does, the server's `.env` changes `PURCHASING_LOG_PATH` and `PURCHASING_LOG_URL` in the same visit.
- The not-set sentence says "Ask an admin" because only an admin at the production server can set it.
