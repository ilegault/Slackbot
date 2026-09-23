# 08: Assignment replaces claim — the approver names the buyer

**What to build:** Delete the claim mechanism entirely and replace it with an
assignee named by the approver in the approval message itself. Approval reads the
one non-bot `<@U…>` mention in the text; that person becomes the buyer, gets the
email draft, and is the only one (besides an approver or admin) who can move the
request along.

**Blocked by:** None — 01 through 07 are all `done`

**Status:** done

**Read `docs/adr/0004-assignment-replaces-claim.md` before anything in this
ticket.** It supersedes `docs/adr/0002-request-lifecycle-and-surfaces.md`
decision 6 — read 0002 for the surrounding lifecycle, but implement from 0004
where they disagree. `docs/adr/0001-tests-first-and-no-muted-failures.md` is
binding. `CONTEXT.md` has the vocabulary.

## Why

Ticket 03 made every approved request wait for a Claim, broadcast to all buyers.
Charlie asked for the opposite: he names the responsible person when he approves,
because he is the one who set the rotation up and he already knows whose turn it
is. He types it today, by hand, in both of these shapes:

```
@Dylan Kohler @Purchasing Approved
@Purchasing Approved @Dylan Kohler
```

(`@Purchasing` is the bot. The app is named Purchasing in Slack; "p-bot" is only
ever a word people use in conversation.)

**Nothing is being migrated.** Claim has never run in production — `roster.json`
ships `"buyers": []` so the gate refused everyone, and the deploy that would have
carried ticket 03 failed. There are no live cards with a Claim button on them.
Delete the code; do not write a compatibility shim.

## Requirements, stated as requirements

1. **One parsing rule, in one pure function.** Add to `src/text_rules.py`:

   ```python
   def parse_mentions(text: str, bot_user_id: str | None = None) -> tuple[str, list[str], list[str]]:
       """Return (text with all mentions removed, user ids excluding the bot, user-group ids)."""
   ```

   It matches `<@U…>` / `<@W…>` (with or without a `|label` suffix) and
   `<!subteam^…>`. It is pure: no Slack client, no I/O, no state. Every decision
   below reads its output; nothing anywhere else may regex a mention out of text.

2. **Strip mentions before matching keywords.** `dispatch_command` currently
   substring-matches `text.lower()` against every keyword tuple. A lowercased
   Slack ID is alphanumeric and can contain `log`, `take` or `submit`, so from now
   on the *stripped* text is what gets matched. This is ADR 0004 decision 8 and it
   is a correctness requirement, not a tidy-up.

3. **The bot's own ID comes from Bolt, not from a constant.** Take
   `context.get("bot_user_id")` in the `app_mention` and `message` listeners and
   pass it down to `dispatch_command`. Fall back to a module-level cached
   `client.auth_test()["user_id"]` if the context key is missing — one call, cached,
   never per-message.

4. **Mention count decides, position does not.**

   | Non-bot user mentions | Behaviour |
   |---|---|
   | 1 | that user is the assignee |
   | 0 | approve, and leave the request unassigned |
   | 2+ | approve, leave unassigned, refuse the assignment asking which one |
   | any user group | approve, leave unassigned, refuse: name a person, not a group |

   Never silently take the first of several.

5. **A refused assignment never refuses the approval.** In every row of that table
   the rows are written, the EPIFs are archived and the card is posted. The only
   thing that varies is whether an assignee is set. Same for a named non-buyer and
   for a buyer with no `requesters` entry.

6. **Permission depends on the current state, per ADR 0004 decision 3.** Unassigned
   → any buyer, approver or admin may assign (including a buyer naming themselves).
   Assigned → approver, admin, or the current assignee only.

7. **A named non-buyer is refused with the fix in the message**, in-thread:
   `⚠️ <@U…> isn't on the buyers list, so I can't assign this to them. An admin can
   add them: @Purchasing add-buyer @Name`. A named buyer who has no `requesters`
   entry keeps the existing `/roster-set-name` refusal — same reason as ticket 03,
   the name would be a profile guess.

8. **The email draft is generated once, in `lifecycle.handle_assign`,** with the
   assignee's resolved name, and DM'd to the assignee. No draft is sent for an
   unassigned request. A reassignment sends a fresh draft to the new assignee. Draft
   fields come from the button `value` payload falling back to
   `log_writer.get_row_info(row)` — **do not re-parse the PDF** (ticket 03's rule,
   still binding).

9. **`approved` is now a terminal-button state of its own.** In
   `build_request_blocks`: `primary_buttons["approved"]` becomes
   `("Mark Processed", "req_processed")`, and the `"claimed"` entries in both
   `primary_buttons` and `secondary_buttons` are deleted. `Cancel` stays on
   `approved`. The state list in the docstring becomes
   `posted -> approved -> processed -> confirmed -> delivered`.

10. **The card says who owns it.** The summary block gains one line, rendered from
    `request["assignee_id"]` / `request["assignee"]`:
    `• *Buyer:* <@the-assignee>` or `• *Buyer:* ⚠️ _Unassigned_`.

11. **`req_processed`, `req_confirmed` and `req_delivered` are gated on assignee or
    admin** — not on `is_buyer`. An unassigned request cannot be marked processed;
    the denial says to assign it first.

12. **Delete, do not deprecate:** `config.CLAIM_KEYWORDS`, `lifecycle.handle_claim`,
    `app.handle_req_claim_action` and its `@app.action("req_claim")` registration,
    the `claimed` card state, the buyers broadcast in
    `finalize_purchase_request.on_success`, and the stale claim narration in the
    `src/app.py` module docstring (lines 9–13). Add
    `ASSIGN_KEYWORDS = ("assign", "assigned")` to `config`.

13. **Stop printing the server's file paths in the thread.** The approval message
    still posts ``Saved EPIF to `C:\Users\...` `` — a path on the production server
    that means nothing to anyone reading Slack. Print the file name only. It is in
    the block this ticket rewrites, so it goes now.

## Acceptance criteria

- [x] `text_rules.parse_mentions` exists with the signature above, is pure, and
      handles `<@U123>`, `<@U123|dylan>`, `<@W123>` and `<!subteam^S123>`
- [x] `dispatch_command` matches every keyword against mention-stripped text
- [x] A test asserts `@Purchasing logs` still reaches the ops logs handler after
      stripping, and that a message whose *only* other content is a mention with a
      keyword-shaped ID (e.g. `<@U0LOGS99>`) does **not** reach it
- [x] Approval naming a buyer **before** the bot mention assigns that buyer
- [x] Approval naming a buyer **after** the keyword assigns that buyer — same
      assignee, same thread text, same DM as the previous criterion
- [x] A test asserts the assignee DM contains the email draft signed with the
      **assignee's** name, and goes to the assignee's user ID
- [x] Approval with no mention writes the rows, posts the card in the unassigned
      state, posts a thread line asking for a buyer, and sends **no DM** — assert
      on the DM *not* being sent
- [x] Approval naming a non-buyer writes the rows, leaves the request unassigned,
      posts the `add-buyer` refusal, and sends no DM
- [x] Approval naming two users writes the rows, leaves the request unassigned, and
      posts a refusal naming both — a test asserts neither one became the assignee
- [x] Approval naming a user group leaves the request unassigned and refuses
- [x] A buyer assigning themselves to an **unassigned** request succeeds and is
      DM'd the draft
- [x] A buyer who is not the assignee assigning themselves to an **already
      assigned** request is refused: no card update, no DM, no history line
- [x] The approver reassigning an assigned request succeeds, DMs the new assignee,
      and leaves both the original and the reassignment in the card history
- [x] The current assignee reassigning to another buyer succeeds
- [x] `@Purchasing approved @Smeet` in a thread that is **already approved**
      reassigns and performs **no second Excel write** — assert `append_row` is not
      called
- [x] `req_processed` from a user who is neither the assignee nor an admin is
      refused: no Excel write, no `chat_update`, ephemeral denial
- [x] `req_processed` on an unassigned request is refused and the denial says to
      assign it first
- [x] `build_request_blocks("approved", …)` returns `Mark Processed` and `Cancel`,
      and the string `req_claim` appears nowhere in `src/`
- [x] The card renders the assignee line in both the assigned and unassigned forms
- [x] `@Purchasing claim` assigns nothing, writes nothing and updates no card
- [x] The approval thread message contains the saved EPIF's file name and does not
      contain a drive letter or a path separator
- [x] `ruff check .`, `python scripts/check_tests_first.py` and `pytest -q` all pass

## Out of scope

- The unknown-word reply from spec §3.8 (`🤔 I don't know the word "…"`). Still
  unbuilt, still wanted, not this ticket.
- `src/store.py`. Still imported by nothing in `src/`; ticket 06 gave it tests,
  which did not make it used. Leave it alone here.
- Any new workbook column for the buyer — ADR 0004 decision 7 says no.
- App Home and `/purchasing-help` text. That is ticket 09, and it is written
  against this ticket's finished behaviour.

## Comments

### Antigravity Session — Ticket 08 Implementation (2026-09-16)
- Implemented pure `text_rules.parse_mentions(text, bot_user_id)` handling `<@U123>`, `<@U123|dylan>`, `<@W123>`, and `<!subteam^S123>` format.
- Mention stripping integrated in `app.dispatch_command` before keyword matching.
- Replaced claim mechanism with assignment:
  - Approver naming buyer before or after keyword assigns buyer directly.
  - Email draft generated and DM'd to assignee with assignee's signature.
  - Approvals with 0, 2+, user group, or non-buyer mentions write rows and post unassigned card with appropriate in-thread guidance without rejecting approval.
  - Reassignment / self-assignment via `@Purchasing assign` and `@Purchasing approved` on already-approved thread without second Excel row write.
  - Gated `req_processed`, `req_confirmed`, `req_delivered` on assignee or admin.
  - Saved EPIF notification prints filename only.
  - Completely removed `req_claim`, `handle_claim`, `CLAIM_KEYWORDS`, and `claimed` state.
- Added comprehensive unit tests in `tests/test_08_assignment.py` covering all 22 acceptance criteria.
- Full gate passed: `ruff check .`, `python scripts/check_tests_first.py`, and `pytest -q` (133 passed, 31 skipped).

