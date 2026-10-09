# Active work: EPIF-path requests get their EPIF, and the buyer's DM shows the request (111–119)

This is a pointer, not the work. The work is the spec and the tickets below.

- Spec: `.scratch/epif-path-and-buyer-dm/spec.md`
- Tickets: `.scratch/epif-path-and-buyer-dm/issues/111-…` through `119-…` (9 tickets: 7 agent, 2 developer)
- **Read before starting:** `docs/adr/0018-the-path-is-the-payment-method-and-the-dm-card-shows-the-request.md` (new)
- Also binding: ADR 0007 (decisions 1, 5–7; decision 8 replaced by 0018), ADR 0010 (decision 2 amended by 0018), ADR 0016 (refusals via `slack_io.notify`), ADR 0001 (tests first)
- Glossary: `CONTEXT.md`. Updated: **Workday path / EPIF path** (the payment method records the path) and **DM card** (the thread card's fields)
- Tracker conventions: `docs/agents/issue-tracker.md`

**Next:** 111 and 113 have no blockers. **Start with 111.** It fixes a live production bug:
no `/new-purchase` request on the EPIF path has ever produced an EPIF; the bot treats it
as Workday at approval. 113 touches only `src/blocks.py` and can run alongside it.

## Dependency graph

    Deploy 1   111 ──► 112 ──► 118 (ready-for-developer: deploy)
               111 ───────────► 118
    Deploy 2   113 ──► 114 ──► 115 ──► 117 ──► 119 (ready-for-developer: deploy)
               111 ──► 114     112 ──► 115
               111 ──► 116 ──► 117     115 ──► 119
               113 ──► 116

Some edges exist only so that two tickets never edit the same function at once:
112 waits on 111 because both edit `lifecycle._send_assignee_dm`. Keep them.
118 and 119 are `ready-for-developer`; an agent must not claim them.

## Requirements an implementer might treat as preferences — they are not

- `interview.get_request_route` reads only the payment method (plus `has_file`). Nothing writes or reads a `route` key on a request or card; modal `meta["route"]` stays.
- 111's end-to-end test starts from `lifecycle._process_interview_completion` and takes the Approve button's `value` off the posted card. A hand-built request dict or a patched `get_request_route` does not count; that is how this bug stayed hidden.
- 112's upload tests use a real `slack_sdk.WebClient` with only its network methods patched. A `MagicMock` client does not count.
- `blocks.request_summary_lines` is the one builder of request lines for both cards (113); the thread card's output stays byte-identical.
- The switch (117) rewrites the **same** row in one queued write and refuses if the row is processed by the time the write runs.
- No test is deleted in this set. Changed tests are rewritten in place under the same name with the same number of assertions.
- A new test that already passes on today's code makes the gate hold the PR. Tickets say where such checks share a test function with ones that fail today; follow that.

## Deliberately not in this set

- Changing how Approve reads the buyer picker (production shows assignment at approval works).
- A tool to repair requests already approved without an EPIF (done by hand in 118).
- The legacy `files_upload` fallback branches.
- The ticket-engine change that should have refused ticket 42's empty PR (taken to ticket-engine separately).
