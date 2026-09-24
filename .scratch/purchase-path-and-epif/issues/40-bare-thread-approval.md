# 40: Charlie can approve a thread with no EPIF as a Workday order

**Status:** ready-for-agent

**Blocked by:** 38

Spec: Implementation Decision 4 (bare-thread approval, waiting for details, Fill in details, Cancel). Binding: ADR 0007 decisions 4–5, ADRs 0003–0005.

**What to build:** Katarina posts a screenshot and a Grainger link. Charlie replies
`@Purchasing @Dylan approved`. Instead of "couldn't find a PDF", the bot posts one reply:
*"✅ Approved by Charlie. No EPIF in this thread, so I'm treating this as a **Workday
order**. @Katarina, please fill in the details so it can be logged. If this vendor isn't
on Workday, press **This needs an EPIF** instead."* It also posts a card reading
"Approved — waiting for details" with **Fill in details**, **This needs an EPIF** and
**Cancel**. Nothing is written yet. Katarina presses Fill in details, picks Grainger from
the list, and fills the Workday details form. The row is written with her as requester,
the card becomes an ordinary approved card, and Dylan gets the Workday DM. Charlie never
approves again.

- [ ] A bare thread is one with no EPIF PDF, no card payload and no interview metadata. For such a thread, approval posts exactly one thread reply (wording above) and one `waiting_for_details` card, and writes no row (absence asserted).
- [ ] The requester is the author of the thread's parent message, resolved through the roster the same way as for an uploaded EPIF.
- [ ] An assignee named in the approval is recorded using the existing mention rules (ADR 0004). A refused assignment never refuses the approval.
- [ ] The `waiting_for_details` state is serialised on the card like every other state (invariant 3). It has no stage buttons and no buyer picker. Keyword assignment still works on it.
- [ ] Fill in details and This needs an EPIF may be pressed by the requester, the assignee, any buyer while unassigned, or an admin. Anyone else gets a private denial and nothing else happens (absence asserted). In this ticket, This needs an EPIF may only reply privately that it is coming in ticket 41. It must not write anything.
- [ ] Fill in details opens a single-screen Workday details form. Its vendor select is limited to the vendor list, followed by item, purpose, link, total, date, room, project, fund, category and the optional line-items box. On submit it is checked by the existing validator, then written through the existing finalize path with `route = workday`. The card becomes `approved`, and the Workday DM (ticket 38) goes to any assignee.
- [ ] Cancel on a `waiting_for_details` card (approver or admin) writes nothing, turns the card terminal with `🚫 Cancelled by …` and no buttons, and posts one thread line.
- [ ] Threads containing an uploaded EPIF or an interview card behave exactly as before (regression test).
- [ ] Scenario tests, fake client plus a temporary workbook: bare approval (reply, card, no row); Fill in details by the requester (row written, requester correct, card approved); by a non-member (denied, no row); cancel while waiting (workbook unchanged, card terminal).
- [ ] `CONTEXT.md` **Waiting for details** and **Bare-thread approval** match what was built. If not, flag it rather than editing the glossary silently.
- [ ] Full gate green (all four commands).

## Comments
