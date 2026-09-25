# Spec — The BOM sheet in the lab's layout

**Status:** ready-for-agent
**Binding:** `docs/adr/0008-bom-sheet-follows-the-lab-layout.md` (supersedes ADR 0006 decision 10),
`docs/adr/0006-bom-line-items-and-editable-posted-cards.md` (everything else),
`docs/adr/0001-tests-first-and-no-muted-failures.md`

## Why

The BOM the bot produces (tickets 26–33, all `done`) uses a placeholder column set.
Purchasing already receives hand-made BOMs in a set layout. The bot's sheet should look
like those, minus the parts the developer said are redundant with the EPIF.

While checking where line items enter the bot, a third copy of the items box turned up
in the Workday details modal (bare-thread approval, ticket 40). It shows an example that
the parser rejects, and its submit handler passes a list where Slack needs a string, so
a bad paste there breaks the modal instead of showing the error.

## Tickets

| # | Ticket | Blocked by |
|---|---|---|
| 49 | The BOM sheet uses the lab layout | None |
| 50 | One items box everywhere | None |

Independent. Either order.

## Out of scope

- The paste format. Unchanged (ADR 0008 decision 7).
- `bom.parse_line_items`, `bom.check_total`, `bom.needs_bom`, `bom.bom_filename`,
  `bom.describe_changes`, `log_writer.save_bom`. Unchanged.
- The Notes-column text written to the Purchasing Log (`BOM: <file> (N items)`). Unchanged.
- Any new field on the request, the card, or the EPIF.
