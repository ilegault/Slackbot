# Spec: layer the app, then finish the lifecycle

**Effort:** `lifecycle-and-buyers`
**Written:** 2026-09-16
**Binding:** `docs/adr/0001-tests-first-and-no-muted-failures.md`,
`docs/adr/0002-request-lifecycle-and-surfaces.md`,
`docs/adr/0003-decline-and-cancel.md`
**Glossary:** `CONTEXT.md`

## What shipped before this

The previous effort landed four things and is not re-opened here:

- **T1** — every slash-command and block-action reply goes through `respond()`.
  One `chat_postEphemeral` call remains, on the message-event path where there is
  no `response_url`.
- **T2** — `@app.middleware log_request` with a per-kind payload extractor,
  start/completion lines and timings.
- **T3** — `build_request_blocks(state, request, history)` and five `@app.action`
  handlers. The message is the store.
- **T4** — help text and App Home both lead with the interface rule.

**T3 landed with a gap** (the PDF-drop path gets no buttons) and **T1–T4 landed
with no regression guards**. Those are tickets 04 and 06 below, not new ideas.

## What this effort does

Six tickets. One structural, four behavioural, one covering the lot.

| # | Ticket | Why now |
|---|---|---|
| 01 | Split `src/app.py` into layers | Every other ticket edits it. Blocking. |
| 02 | Buyers become a roster list of Slack IDs | Buyers cannot be mentioned; adding one needs a code edit |
| 03 | Every approved request waits for a claim | A buyer's own request skips the claim entirely |
| 04 | Buttons on the PDF-drop path | Two experiences for one task; live approver confusion |
| 05 | Decline, Cancel, and the `processed` rename | There is no way to say no |
| 06 | Regression guards | T1–T4 and 02–05 are untested |

## The structural problem, stated once

`src/app.py` is **2 855 of the repo's 5 470 lines** and holds three layers at
once: Block Kit builders, lifecycle operations, and Bolt listener registrations.
Consequences, all of them live:

- Tickets 02, 03, 04 and 05 all edit it, so they serialise and cannot be worked in
  parallel, and each one needs the whole file in context to change one handler.
- AGENTS.md invariant 1 — *one lifecycle operation, one implementation* — is a
  request rather than a structural fact. Nothing stops a button handler from
  growing its own copy of "mark delivered"; the only thing preventing it today is
  that someone remembered.
- A pure function like `build_request_blocks` cannot be tested without importing
  the module that constructs a live Bolt `App`.

Ticket 01 is a **pure move**: no behaviour change, no renames, no bug fixes, no
new features. It exists so the four tickets after it touch disjoint files.

## Dependency order

```
01 ──┬─ 02 ── 03 ─┐
     ├─ 04 ───────┼─ 06
     └─ 05 ───────┘
```

- **02 → 03**: the claim permission gate and the broadcast both need buyer Slack IDs.
- **04** and **05** are independent of 02/03 once 01 lands.
- **06** is last: it guards everything above plus the shipped T1–T4 surface.

## Requirements that will be read as preferences unless stated as requirements

1. **Ticket 01 changes no behaviour.** If the diff contains anything that is not a
   move plus its import, it is the wrong diff. A refactor with a fix smuggled
   inside it cannot be reviewed, and this one touches everything.
2. **A listener never reimplements a lifecycle operation.** Ack, extract,
   permission-check, delegate. If a signature does not fit the payload, adapt the
   payload or extract a shared core — never write a second copy.
3. **Roles are Slack IDs.** `is_buyer` takes an ID. No name-based variant "for
   convenience"; matching on names is the defect ticket 02 removes.
4. **Cancel un-writes the Excel row.** Blanked, not marked, not struck through.
   The workbook is a log of live approved purchases and their stage, nothing else.
5. **Cancel after `processed` is refused loudly**, in-thread, in words that tell
   the approver to go talk to purchasing.
6. **The `submitted` → `processed` rename happens once**, inside ticket 05, across
   every surface at the same time. Not opportunistically in 01, 02, 03 or 04 —
   that leaves both words coexisting for the length of the effort, which is the
   exact state ADR 0002 decision 4 exists to end.

## Two things that need a human, not an agent

- **Seeding the live roster with Finn's, Smeet's and Dylan's Slack IDs.** Ticket 02
  makes it possible; doing it needs the real member IDs and a Slack session.
- **Deploying.** Merging to `master` does not update the production server. Isaac
  merges, then runs `@p-bot update`. No ticket may assume otherwise.
