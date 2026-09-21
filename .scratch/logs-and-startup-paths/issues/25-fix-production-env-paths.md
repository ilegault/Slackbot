# 25: Fix the production server's storage paths and re-run the DB15 approval

**What to build:** The live bot writes to the real Purchasing Log again, and the
DB15 breakout board request that failed on 2026-09-21 is logged.

**Blocked by:** None (can start immediately)

**Status:** human-task

An agent must not claim this. It needs someone physically at the production
server, and it needs Charlie.

## Why

The server's `.env` still holds the setup template's `C:\Users\USERNAME\…` for
all four storage paths, so every workbook write fails. Ticket 24 makes this
visible at boot, but only a person at the server can fix it.

## Steps

- [ ] On the server, edit `C:\Isaac_programs\Slackbot\.env` so that `PURCHASING_LOG_PATH`, `EPIFS_DIR`, `CONFIRMATIONS_DIR` and `QUOTES_DIR` read `C:\Users\ilegault\…`
- [ ] Confirm the Hirst-Lab OneDrive shortcut is synced under the `ilegault` account, so those paths exist on disk
- [ ] Restart the service
- [ ] `@Purchasing health` in the alert channel reports storage healthy
- [ ] Charlie re-approves the DB15 breakout board request. The row appears in the Purchasing Log and the card posts

## Comments
