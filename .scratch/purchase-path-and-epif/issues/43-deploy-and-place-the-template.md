# 43: Place the template on the production server and deploy

**Status:** ready-for-developer

**Runner:** developer

**Auto-merge:** yes

**Blocked by:** 34, 35, 37, 38, 39, 40, 41, 42, 44, 45, 46, 47

**What to build:** The developer confirms `EPIF_TEMPLATE_HIRST.pdf` is in the production
server's `Purchasing/_TEMPLATE` folder, sets `EPIF_TEMPLATE_PATH` in the server's `.env`
only if it lives elsewhere, merges, and runs `@p-bot update`. **An agent must not claim
this ticket.**

- [ ] The startup storage alert does not name the EPIF template.
- [ ] One real EPIF-path order puts a filled EPIF in the buyer's DM, and it opens in Acrobat with every field editable.
- [ ] One bare-thread approval posts the Workday reply and the waiting-for-details card, and Fill in details logs a row.
- [ ] `@p-bot add-vendor` works in production, and Screen 1 has no "Suggest a new vendor" option.

## Comments
