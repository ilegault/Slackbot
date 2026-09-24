# 43: Place the template on the production server and deploy

**Status:** human-task

**Blocked by:** 34, 35, 37, 38, 39, 40, 41, 42

**What to build:** Isaac confirms `EPIF_TEMPLATE_HIRST.pdf` is in the production server's
OneDrive `Purchasing/_TEMPLATE` folder. He sets `EPIF_TEMPLATE_PATH` in the server's
`.env` only if it lives elsewhere. Then he merges and runs `@p-bot update`. **An agent
must not claim this ticket.**

- [ ] The startup storage alert does not name the EPIF template.
- [ ] One real EPIF-path order produces a filled EPIF in the buyer's DM. The filled EPIF opens in Acrobat, with every field editable.
- [ ] One bare-thread approval posts the Workday reply and the waiting-for-details card.
- [ ] `@p-bot add-vendor` works in production.

## Comments
