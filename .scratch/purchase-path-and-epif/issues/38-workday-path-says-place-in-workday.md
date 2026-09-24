# 38: A Workday-path approval tells the buyer to place it in Workday

**Status:** ready-for-agent

**Blocked by:** None (can start immediately)

Spec: Implementation Decision 3 (the Workday half). Binding: ADR 0007 decision 8.

**What to build:** A requester picks Fisher Scientific from the vendor list, and Charlie
approves it, assigning Smeet. The thread says *"Assigned to @Smeet (Smeet) to place in
Workday."* Smeet's DM is a short summary with the item, vendor, price, link and row. It
says to place the order in Workday and then use the card's buttons. It contains **no
email draft**. No EPIF is created.

- [ ] Workday-path requests use `to place in Workday`, and the unassigned line reads `Needs a buyer to place in Workday.` The string "Workday / ShopUW" no longer appears in any approval or assignment message.
- [ ] Which path a request is on is decided by one shared function: the payload's `route`; with no route, an uploaded EPIF means `epif` and anything else means `workday`. If ticket 37 has already added it, reuse it. Otherwise add it here, and 37 reuses it.
- [ ] The Workday DM begins `Place this in Workday:` and lists item, vendor, price, link and row. It is sent at approval with an assignee and on a later assign, through the one existing implementation.
- [ ] Scenario test: a Workday-path approval posts the new thread line. The assignee's DM contains no `Subject:` / email-draft text and **no file upload** (absence asserted). No file appears in `EPIFs/`.
- [ ] Existing tests asserting the old wording on Workday requests are updated, and the commit message cites ADR 0007.
- [ ] Full gate green (all four commands).

## Comments
