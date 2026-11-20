# 154: Deploy, rerun the autostart script and check one bot survives a reboot

**Status:** ready-for-developer

**Runner:** developer

**Auto-merge:** no

**Blocked by:** 151, 152, 153

**Spec:** `.scratch/one-running-bot/spec.md` (Implementation Decisions: Rollout is two developer tickets)
**Binding:** `docs/adr/0022-one-running-bot.md`

## What to build

Put tickets 151 and 152 on **the server**, replace its launchers with the one the new
script installs, and prove three things there: a reboot starts exactly one bot, a second
copy is refused and reported, and `@Purchasing restart` still works. Needs a person at the
server: rerunning the script and rebooting cannot be done from Slack.

## Acceptance criteria

- [ ] `@Purchasing update`, then the startup line in the production log names a commit that contains tickets 151 and 152. (by hand)
- [ ] At the server, in an elevated PowerShell in the bot's folder: `python scripts\setup_autostart.py`. Afterwards `Get-ScheduledTask | Where-Object TaskName -match 'Bot'` lists only `Purchasing-Bot`, and the Startup folder has no `P-Bot.lnk`. (by hand)
- [ ] Reboot the server. After it is back: the production log has exactly one "Starting Purchasing bot" line for this boot; the Alert channel has exactly one "online" message and no "A second Purchasing bot tried to start" message; `@Purchasing health` answers. (by hand)
- [ ] With the bot running, double-click `run_bot.bat`. After about 15 seconds that window shows the refusal and stays open; the Alert channel gets "🛑 A second Purchasing bot tried to start on <the server's name> and stopped — one is already running."; the running bot still answers `@Purchasing health`. Close the window. (by hand)
- [ ] `@Purchasing restart`: the bot comes back with one new "Starting Purchasing bot" line in the log and no refusal message in the Alert channel. (by hand)

## Comments

