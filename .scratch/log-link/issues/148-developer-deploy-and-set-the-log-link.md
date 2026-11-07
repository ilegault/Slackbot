# 148: Deploy, then set the Log link on the production server

**Status:** ready-for-developer

**Runner:** developer

**Auto-merge:** no

**Blocked by:** 146, 147

**Spec:** `.scratch/log-link/spec.md` (Implementation Decisions: Server setting is a human task)
**Binding:** `docs/adr/0021-app-home-and-help-link-the-purchasing-log.md`

## What to build

Put tickets 145–147 on the production server, give it the Purchasing Log's sharing link,
and check every surface. Needs a person at the server: no agent can edit its `.env`.

## Acceptance criteria

- [ ] `@Purchasing update`, then the startup line in the production log names a commit that contains tickets 145–147.
- [ ] Before adding the setting: App Home's Welcome section and `/purchasing-help` both show "The Purchasing Log link isn't set up yet. Ask an admin.", and `@Purchasing health` shows `Log link: not set`.
- [ ] Copy the workbook's sharing link from the browser, add `PURCHASING_LOG_URL=<link>` to the production `.env`, and restart the service.
- [ ] After the restart: `@Purchasing health` shows `Log link: set`; App Home shows **Open Purchasing Log**, which opens the workbook in the browser, shows no error triangle, and the bot posts nothing; the "Purchasing Log" line in `/purchasing-help` opens the same workbook.
- [ ] A lab member who is not an admin can open the link from App Home (Microsoft's sign-in lets them in).

## Comments

