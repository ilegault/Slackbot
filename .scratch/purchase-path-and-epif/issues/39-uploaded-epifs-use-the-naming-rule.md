# 39: Uploaded EPIFs are archived under the same naming rule

**Status:** ready-for-agent

**Blocked by:** 37

Spec: Implementation Decision 2 (naming). Binding: ADR 0007 decision 7.

**What to build:** A student drops `my epif final v2.pdf` for a $349 Commonlands lens in
a thread, and Charlie approves it. The archived copy in `EPIFs/` is
`Commonlands_EPIF_$349.00_PG000025831.pdf`, named from the parsed vendor, amount and
project ID. The file in Slack keeps its original name. The "Saved EPIF to …" thread line
shows the new name.

- [ ] The uploaded-EPIF approval path saves through ticket 37's naming function, including the `_2` rule. There is no second naming implementation.
- [ ] The row-number prefix is not added to EPIF names. The BOM keeps `NNNN_<Vendor>_BOM.xlsx`, and its Notes line is unchanged.
- [ ] Cancel still moves the archived EPIF to `EPIFs/Cancelled/` under its archived name.
- [ ] Scenario test: approving a thread with an uploaded EPIF archives it under the rule, and the thread line names that file. A second identical upload archives as `_2`.
- [ ] Full gate green (all four commands).

## Comments
