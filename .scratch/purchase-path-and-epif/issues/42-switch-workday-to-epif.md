# 42: Switch an approved Workday request to EPIF before it's processed

**Status:** ready-for-agent

**Blocked by:** 37, 38

Spec: Implementation Decision 4 (switch). Binding: ADR 0007 decision 5, invariant 2.

**What to build:** An approved Workday request is logged at row 22 and assigned to Smeet.
Smeet opens Workday and the vendor isn't there. The card has a **Switch to EPIF** button.
Smeet presses it, and the EPIF-path interview opens pre-filled from the request. On
submit, **row 22 itself** is rewritten with the new vendor, payment method and details,
the filled EPIF is generated and archived in the same queued write, one thread line
records `🔁 Switched to EPIF by Smeet`, and Smeet gets the EPIF DM. Once the request is
processed, the button is gone and a switch is refused.

- [ ] Switch to EPIF appears only on `approved`-or-later cards with `route = workday` and no Date Processed. It disappears after Mark Processed.
- [ ] Permission: the requester, the assignee, any buyer while unassigned, or an admin. Others get a private denial.
- [ ] The rewrite goes through `log_writer` and the queue (the only writer). It changes vendor, payment method and every detail field of the **same** row. It keeps the requester, date of request and stage dates. The row count is unchanged.
- [ ] Inside the queued task, the switch re-reads Date Processed and refuses if it is set, even if the button was pressed earlier. On refusal the row is unchanged, no EPIF is archived, and the actor is told why.
- [ ] The card's `route` becomes `epif`, one history and thread line is added, and the EPIF DM with attachment goes to the assignee.
- [ ] Scenario tests, temporary workbook: switch before processed (same row number rewritten, row count unchanged, EPIF archived, DM has a file); switch after processed (refused, row byte-identical, no EPIF); non-member (denied, nothing changed).
- [ ] Full gate green (all four commands).

## Comments
