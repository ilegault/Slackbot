# 60: Developer — dev .env, deploy, verify on the server, update AGENTS.md

**Status:** ready-for-developer

**Runner:** developer

**Auto-merge:** no

**Blocked by:** 51, 52, 53, 54, 55, 56, 57, 58, 59

**Spec:** `.scratch/commands-paths-and-name/spec.md`
**Binding:** `docs/adr/0009-keywords-storage-settings-and-the-bot-name.md`

## What to build

A person at the dev machine and the production server. **An agent must not claim this
ticket.** It edits `AGENTS.md`, so it is held and is a leaf.

## Acceptance criteria

- [ ] The dev `.env` has `BOMS_DIR` and `EPIF_TEMPLATE_PATH` (there are no defaults any
  more, ADR 0009 decision 4).
- [ ] After merge and `@Purchasing update`, the startup alert on the server is green, and
  `@Purchasing health` lists all six storage settings with their full paths, all ✅.
- [ ] `@Purchasing remove-vendor <test vendor>` and `@Purchasing remove vendor <test vendor>`
  both work on the server, and `@Purchasing flurb` gets an in-thread reply, no crash alert.
- [ ] `/blank-template` delivers `EPIF_TEMPLATE_HIRST.pdf` with its instructions.
- [ ] `AGENTS.md`: "P-Bot" → "the Purchasing bot" and `@p-bot` → `@Purchasing`
  (developer's own edit).

## Comments
