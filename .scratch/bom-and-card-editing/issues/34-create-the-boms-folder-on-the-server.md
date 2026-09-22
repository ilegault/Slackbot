# 34: Create the BOMs folder on the production server

**Status:** human-task

**Blocked by:** 26

**Spec:** `.scratch/bom-and-card-editing/spec.md`, Further Notes

## What to build

Isaac, physically at the production server. Nothing here is an agent's to claim.

The bot writes approved BOMs to a folder that has to exist before any of this can
be deployed:

1. In the OneDrive `Purchasing` folder, beside `EPIFs`, `Quotes` and
   `Order-Confirmations`, create a **`BOMs`** folder.
2. Add `BOMS_DIR` to the server's `.env`, pointing at it, in the same style as
   `QUOTES_DIR`.
3. Restart the bot and check the startup alert names no bad paths.

Do this after merging ticket 26 and deploying, since the startup check is what
confirms it. Deploying is a human step: merge, then `@Purchasing update`.

## Acceptance criteria

- [ ] The `BOMs` folder exists on the production server's OneDrive Purchasing folder
- [ ] `BOMS_DIR` is set in the server's `.env` and points at it
- [ ] The startup admin alert after a restart reports no bad storage paths
