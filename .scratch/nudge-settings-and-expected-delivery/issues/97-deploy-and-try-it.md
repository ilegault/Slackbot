# 97: Deploy and try uploads and nudges

**Status:** ready-for-developer

**Runner:** developer

**Auto-merge:** no

**Blocked by:** 81, 82, 83, 84, 85, 86, 87, 88, 89, 90, 91, 92, 93, 94, 95, 96

**Spec:** `.scratch/attached-boms-and-quotes/spec.md`, `.scratch/nudge-settings-and-expected-delivery/spec.md`
**Binding:** `docs/adr/0012-attached-boms-and-quotes-are-carried-not-read.md`, `docs/adr/0013-nudge-settings-per-stage-and-expected-delivery.md`

## What to build

Nothing to code. Merging to `master` does not update the production server; the developer does,
then checks the two features in real Slack.

## Acceptance criteria

- [ ] On the server, run `@Purchasing update` and confirm the bot restarts cleanly (health screen shows all storage paths OK).
- [ ] In Slack's app settings, confirm the bot still has the `files:read` and `files:write` scopes (file fields need `files:read`).
- [ ] Start `/new-purchase` with a real BOM `.xlsx` (one-vendor box ticked) and two quote PDFs: the card shows `BOM attached` and `Quotes: 2`, and the files appear in the thread.
- [ ] Approve it with a buyer named: the BOM and quotes land in the BOMs and Quotes folders under the `NNNN_` names, and in the buyer's DM.
- [ ] Open App Home as an admin: **Edit nudge settings** is there, the **Nudges** section matches the settings; set the delivered nudge's interval to the lab's choice (2–3 weeks) and decide whether to turn on the approved nudge.

## Comments

