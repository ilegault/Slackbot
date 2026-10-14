# Active work: BOMs come in through the lab template, the EPIF date is the buyer's, categories have minimums (123–137)

This is a pointer, not the work. The work is the spec and the tickets below.

- Spec: `.scratch/bom-template-and-epif-date/spec.md`
- Tickets: `.scratch/bom-template-and-epif-date/issues/123-…` through `137-…` (15 tickets, all agent)
- Binding: ADR 0019 (BOMs come in through the lab template and are read; it supersedes parts of 0006, 0008 and 0012), ADR 0007 (the bot fills the EPIF), ADR 0010 (linked cards), ADR 0015 (thread files at approval), ADR 0001 (tests first)
- Glossary: `CONTEXT.md`. New: **EPIF date**, **Request date**, **Category minimum**, **BOM template**, **BOM check**, **Off-template BOM**, **Replace BOM**. Rewritten: **Line item**, **BOM**, **Filled EPIF**, **Thread files at approval**, **Edit**
- Committed data: `templates/HIRST_LAB_BOM_TEMPLATE.xlsx` (the standard), `tests/fixtures/BOM_TEMPLATE_FILLED_EXAMPLE.xlsx` (a real filled BOM, $858.50)
- Tracker conventions: `docs/agents/issue-tracker.md`

**Next:** once 121 and 122 are done, these are unblocked: 123, 124, 127, 129, 130, 131, 133. 127, 130 and 131 have no blockers at all. **Start with 131** (the pure BOM reader). The whole BOM chain (132 → 134 → 135, 136 → 137) waits on it, and it touches no file that another open ticket edits.

## Dependency graph

    121 ──► 123                          (A: category minimum)
    121 ──► 124 ──► 125 ──► 126          (B: EPIF date, Change date)
            127 ──► 128                  (C: DM upload retry, Resend EPIF)
    122 ──► 129                          (D: button values fit)
            130                          (D: failed update tells the editor)
            131 ──► 132 ──┬──► 134 ──► 135
    121 ──► 133 ──────────┘     │
                  132 ──► 136 ──┴──► 137 (E: BOM template)

No ticket is `ready-for-developer` and none is held. After the set merges, the developer deploys (`@Purchasing update`) and updates AGENTS.md traps 10 and 11 (paste box, shipping row), which go stale with 135.

## Requirements an implementer might treat as preferences — they are not

- `validators.category_minimum_problem`, `bom.read_bom_template`, `bom.check_bom_total`, `bom.bom_filename` and `epif_filler.redate_epif` are pure functions. They are tested on real files: the committed fixture and the EPIF template.
- The BOM reader never reads formula cells and never guesses headers. `.xlsx` only.
- The BOM total must equal the typed Total Price to the cent. There is no shipping anywhere.
- The uploaded BOM file is never kept on the form path. The bot rebuilds it from the committed template.
- The BOM check answers Slack immediately (`response_action="update"` to a reading view) and reads the file off the listener, then calls `views_update`. Line items never go in a button value.
- On the thread path a BOM never blocks approval, and Replace BOM never gates Mark Processed.
- Change date and Replace BOM never change workbook column M. Only Replace BOM may touch the Notes column, and only when the file name changes.
- Every DM upload goes through the one retry helper from 127.
- Tests named in criteria must fail on the base commit unless the criterion says "rewrite in place". Test functions are deleted only where a ticket's `Deletes tests:` line lists them.

## Deliberately not in this set

- Reading any spreadsheet layout other than the template, or reading quotes.
- Tracking shipping or tax.
- Re-dating, renaming or rebuilding EPIFs and BOMs approved before the deploy.
- A Slack table editor for BOM rows.
- A BOM on a batch (several EPIFs in one thread).
