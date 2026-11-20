# 153: Stop the second bot on the server now

**Status:** ready-for-developer

**Runner:** developer

**Auto-merge:** no

**Blocked by:** None (can start immediately)

**Spec:** `.scratch/one-running-bot/spec.md` (Problem Statement; Implementation Decisions: Rollout is two developer tickets)
**Binding:** `docs/adr/0022-one-running-bot.md`

## What to build

Two copies of the bot are running on **the server** since its last reboot, started by the
two launchers the old autostart script installed. Stop one and remove the Startup-folder
launcher so the next reboot starts one. Needs a person at the server; no code. Can be done
before tickets 151 and 152 land, and stops the doubled nudges today.

## Acceptance criteria

- [ ] In PowerShell on the server, `Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*app.py*' } | Select-Object ProcessId, CreationDate, CommandLine` lists the running bots (expected: two). (by hand)
- [ ] `Stop-Process -Id <one of them>`; the same command then lists exactly one, and its console window is the one left open. (by hand)
- [ ] `Remove-Item "$env:APPDATA\Microsoft\Windows\Start Menu\Programs\Startup\P-Bot.lnk"`; `Get-ScheduledTask | Where-Object TaskName -match 'Bot'` still shows the scheduled task, so the bot still starts at boot. (by hand)
- [ ] `@Purchasing health` answers in the Alert channel. (by hand)
- [ ] At the next weekday 9:00 run, no nudge line in the production log appears twice for the same request on the same day, and no thread gets two copies of the same nudge card. (by hand)

## Comments

