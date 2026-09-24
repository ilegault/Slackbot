# 41: "This needs an EPIF" turns a waiting request into an EPIF order

**Status:** ready-for-agent

**Blocked by:** 37, 40

Spec: Implementation Decision 4 (This needs an EPIF). Binding: ADR 0007 decisions 4–6.

**What to build:** On a card that's waiting for details, Dylan finds the vendor isn't on
Workday and presses **This needs an EPIF**. The interview opens on the EPIF path with the
vendor to type. On submit, the row is written with `route = epif`, the filled EPIF is
generated and archived in the same queued write, the card becomes an ordinary approved
card, and the assignee gets the EPIF DM with the PDF attached. No new posted card
appears, and Charlie is not asked to approve again.

- [ ] Permission is the same as ticket 40. Others get a private denial with nothing written.
- [ ] The interview's private metadata carries the bare-thread context (channel, thread, card ts, requester, approver, assignee). On completion, the handler finalises against that card instead of posting a new posted card.
- [ ] The row append and the EPIF generation happen in one all-or-nothing queued task (ticket 37's path). If it fails, the card stays `waiting_for_details`.
- [ ] The thread line and DM are the EPIF-path wording from ticket 37.
- [ ] Scenario test: bare approval, then This needs an EPIF submitted by the assignee. One row with `route = epif`, one archived EPIF under the naming rule, the card `approved`, the DM has a file upload, and **no** second posted card or Approve button appears (absence asserted).
- [ ] Full gate green (all four commands).

## Comments
