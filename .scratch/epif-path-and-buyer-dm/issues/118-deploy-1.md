# 118: Deploy 1 — EPIF-path requests get their EPIF

**Status:** ready-for-developer

**Runner:** developer

**Auto-merge:** no

**Blocked by:** 111, 112

**Spec:** `.scratch/epif-path-and-buyer-dm/spec.md` ("Human tasks")

## What to build

Put tickets 111 and 112 on the production server. This also ships tickets 99–110, which
are merged but have not been deployed since 2026-10-06.

## Acceptance criteria

- [ ] Before updating: `@Purchasing health` shows `EPIF_TEMPLATE_PATH` pointing at the template **PDF**, not the `_TEMPLATE` folder. The production log flagged the folder on 2026-09-28. If it still points at the folder, fix the server's `.env` first.
- [ ] `@Purchasing update`, then confirm the startup line in the production log names a commit that contains tickets 111 and 112.
- [ ] Check approved rows 25 and 27: if a card's payment method is P-card or Req/PO, fill its EPIF by hand and send it to the assigned buyer.
- [ ] Approve the P-card requests that were posted before this deploy and are still waiting. Confirm the first one archives an EPIF, its thread says "to email to purchasing", and the production log shows `📨 Buyer DM sent … (epif path)`.

## Comments
