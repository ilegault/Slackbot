# Spec — hardening the live paths, and roster self-service

**Status:** `ready-for-agent`

Written 2026-09-16, after tickets 01–09 and 11 landed. Covers ticket set **12
onward**. Convert to tickets in the order the Implementation Decisions section is
written — each numbered decision block is one seam, and the order is the
dependency order.

Read before implementing anything here:

- `CONTEXT.md` — the glossary. Every word below is used as it defines it.
- `docs/adr/0001-tests-first-and-no-muted-failures.md` — binding on all test work.
- `docs/adr/0002-request-lifecycle-and-surfaces.md` — the surfaces and the
  interface rule (decision 6 superseded by 0004).
- `docs/adr/0003-decline-and-cancel.md`
- `docs/adr/0004-assignment-replaces-claim.md`
- `docs/adr/0005-assignment-can-be-a-button.md` — required before decision 6 below.
- `.scratch/lifecycle-and-buyers/spec.md` — the lifecycle rebuild. Sections 3.7
  (notification policy) and 3.8 (keyword parsing) were never built; decisions 1
  and 5 below are the scoped-down versions that will be.

---

## Problem Statement

Three things are wrong at once for the people using the bot.

**The bot lies about what it did, and sometimes eats the evidence.** A lab member
posts a purchase request. Somebody who is not Charlie clicks Approve, and the
request message *disappears* — replaced by a padlock line only that person sees.
Nobody is notified, the requester never learns their request went dark, and there
is nothing left in the channel to click. Fifteen separate places in the bot behave
this way. Separately, when Charlie does approve and the workbook write fails
validation, the card still advances to "Approved" — so the channel says the
purchase is logged when no row exists.

**The bot acts on words nobody said.** Keyword routing is a chain of substring
matches. In a request thread today, "@Purchasing can you **check** this?" attempts
a full approval and an Excel write; "@Purchasing waiting on **confirmation**" marks
the order confirmed. An unrecognised word does nothing at all and says nothing, so
a typo is indistinguishable from the bot being down.

**A new lab member cannot join, and a departed one cannot leave.** `/roster-set-name`
refuses any name that is not already in a hardcoded list inside `roster.py`, so
someone new to the lab is told their own name "is not recognized" with no way
forward. Someone already registered who typed their name wrong is told only "you
are already registered" and cannot correct it. And there is no way to remove a
person at all — `remove-buyer` and `remove-approver` strip a role, but Katarina
graduating leaves her in the roster and in the workbook's dropdown forever.

Two smaller gaps sit alongside: the posted card offers no way to name a buyer even
though ADR 0005 accepted a picker, and the interview has nowhere to put the product
page or quote link that nearly every request has, so people paste it into the
purpose field where it is neither validated nor rendered.

## Solution

**Denials become private replies that leave the request standing.** One helper
sends every refusal as an ephemeral message to the person who clicked — visible to
them alone, in place, with the request message untouched. A source scan makes a
sixteenth bare denial impossible to add.

**The card follows the write, not the click.** A card advances a stage only inside
the queued write's success callback — the place `finalize_purchase_request` already
does it correctly. Button listeners lose `chat_update` entirely and go back to what
a listener is for: ack, extract, permission-check, delegate. If the workbook is
locked, the card honestly stays where it is until the write lands, which is what
"Excel is the final reference" means.

**The Approve button uses the payload it was handed.** It already carries the whole
parsed request in its `value` and throws it away to go re-read Slack. It stops
doing that, and the regex that scraped the bot's own summary text back out of a
message is deleted.

**One word, matched exactly.** The first word after the mention is matched against
the canonical vocabulary and nothing else. No substrings, no `("check", "test")`
approval trigger. A word the bot does not know gets a short reply naming the words
it does.

**`/roster-set-name` covers all three cases in one command.** Register, correct,
rename. A correction that differs only in case, spacing or punctuation applies
instantly. A name nobody holds goes to an admin. A name another lab member already
holds is refused outright and never reaches an admin. `@Purchasing remove-member`
ends a membership properly, refusing if it would leave the lab with no admin or no
approver.

**And two additions:** a buyer picker beside Approve on the posted card, and an
optional links field on the interview's second screen.

## User Stories

1. As a lab member, I want my request message to survive someone clicking the
   wrong button, so that my purchase does not silently disappear from the channel.
2. As a lab member who clicked a button I am not allowed to click, I want a private
   message telling me so, so that I learn the rule without broadcasting my mistake.
3. As a lab member, I want the refusal to say which role can do the thing, so that
   I know who to ask.
4. As an approver, I want the card to say "Approved" only when a row was actually
   written, so that I do not tell the lab a purchase is logged when it is not.
5. As an approver, I want a failed approval to leave the request exactly as it was,
   so that I can fix the EPIF and approve the same message again.
6. As a buyer, I want "Mark Processed" to advance the card only once column U
   actually holds a date, so that the card and the workbook cannot disagree.
7. As a buyer, I want the card to wait rather than lie when the workbook is open on
   somebody's desktop, so that I can trust what it says.
8. As an approver, I want clicking Approve on a request that came from
   `/new-purchase` to log exactly the request shown on the card, so that what I
   approved is what gets written.
9. As a bot admin, I want no part of the bot to reconstruct a request by regexing
   the bot's own summary text, so that a wording change cannot corrupt a row.
10. As a lab member, I want `/new-purchase` requests to land in the purchasing
    channel, so that the people who act on them see them.
11. As a bot admin, I want the bot to refuse to start rather than post purchase
    requests into the alert channel, so that a missing setting is loud, not silent.
12. As an approver, I want "@Purchasing can you check this?" to do nothing to the
    purchasing log, so that asking a question cannot spend money.
13. As a lab member, I want a word the bot does not know to get a reply naming the
    words it does know, so that I can tell a typo from an outage.
14. As an approver, I want `@Purchasing approved` to mean approved and nothing else
    to mean it, so that the one irreversible action has one spelling.
15. As an approver, I want to pick the responsible buyer from a dropdown on the
    posted card, so that I do not have to remember the `@`-mention syntax.
16. As an approver, I want skipping the picker to still approve the request, so
    that a missing buyer never costs a purchase its approval.
17. As an approver, I want the bot to tell me which input it used when I both pick
    and mention someone, so that I am not guessing.
18. As a buyer, I want a picked buyer to be checked against the buyers roster
    exactly as a mentioned one is, so that the two inputs cannot drift.
19. As a new lab member, I want `/roster-set-name` to accept my name even though
    nobody in the lab has used it before, so that I can start requesting purchases.
20. As a new lab member, I want to be told my name is waiting on an admin, so that
    I know to wait rather than retry.
21. As a bot admin, I want a new name to reach me with a button, so that approving
    it is one click in the alert channel.
22. As a lab member who typed my name wrong, I want to fix it with the same
    command, so that I do not have to find an admin for a typo.
23. As a lab member correcting only capitalisation or spacing in my own name, I
    want the change to apply immediately, so that a cosmetic fix is not a ticket
    for someone else.
24. As a lab member, I want a name another member already holds to be refused
    outright, so that nobody can register as me.
25. As a bot admin, I want an impersonation attempt never to reach my approval
    queue, so that I cannot approve one by reflex.
26. As a lab member opening the modal, I want to see the name I am currently
    registered under, so that I know whether I am registering or correcting.
27. As a bot admin, I want `@Purchasing remove-member @user` to end a membership
    and strip all three roles at once, so that a graduating student leaves cleanly.
28. As a bot admin, I want `remove-member` refused if it would leave the lab with
    no admin or no approver, so that I cannot lock everyone out.
29. As a bot admin, I want the bot to name the leftover dropdown cell in the alert
    channel when I remove someone, so that I know exactly what to delete by hand.
30. As a bot admin, I want `remove-buyer` to keep meaning "off purchasing duty" and
    `remove-member` to mean "left the lab", so that the two are never confused.
31. As a lab member, I want a removed member's name to stop validating on new
    requests, so that removal actually removes.
32. As a requester, I want a field for the product page or quote link, so that the
    person buying it does not have to guess which item I meant.
33. As a requester, I want the link to be optional, so that a request without one
    is not blocked.
34. As a buyer, I want the link rendered under the request summary in the channel,
    so that I can open it without scrolling the thread.
35. As a lab member, I want App Home to show the name I am registered under, so
    that I can check it without running a command.
36. As a lab member, I want App Home to tell me when I am not registered and offer
    the fix, so that the first thing I see is the thing I need to do.
37. As a buyer, I want App Home to show which roles I hold, so that I know which
    buttons I can use.
38. As a bot admin, I want every new roster command reflected in App Home and in
    `/purchasing-help` from one source, so that the two surfaces cannot drift.
39. As a bot admin, I want a source scan to fail the build if a bare denial is
    added back, so that this class of bug cannot return.
40. As a bot admin, I want `chat_update` to appear nowhere in the listener layer,
    so that a future handler cannot advance a card on a failed write.

## Implementation Decisions

### 1. Denials are ephemeral and never replace anything

**The seam:** the Bolt listener functions in `src/app.py`, called directly with a
synthetic `body` and a `MagicMock` `respond`. This is the established seam —
`tests/test_regression_guards.py` already has eight `test_permission_denial_*`
tests shaped exactly this way. No new seam.

- Add one helper, `slack_io.deny(respond, text)`. It calls
  `respond(text=…, response_type="ephemeral", replace_original=False)`. It holds no
  Slack client, so it stays inside `slack_io`'s remit.
- Every refusal path in `src/app.py` goes through it. That is the fifteen current
  `respond(text=…)` calls: eleven padlock denials, the unassigned-request warning
  on `req_processed`, and the three non-denial informational replies, which get the
  same treatment for the same reason.
- `replace_original` and `response_type` appear nowhere in `src/` today. This is
  the root cause: a block action's reply through `response_url` **replaces the
  message it was clicked on** unless told otherwise.
- Invariant 5 is unchanged — this is still `respond(…)`, not `chat.postEphemeral`.
  The single permitted `chat_postEphemeral` call site is the one in
  `handle_roster_set_name_submit`, and decision 7 moves that path onto `deny`'s
  sibling anyway, at which point zero remain. Update the guard test's expected
  count rather than leaving it asserting one.

### 2. A card advances only inside the write's success callback

**The seam:** `src/lifecycle.py` handlers, called with a fake client and a fake
`say`, with `queue_worker` draining synchronously. Existing seam.

- `finalize_purchase_request.on_success` **already renders the card correctly**,
  using `slack_io.find_card_in_thread` to locate it. Nothing about approval's card
  rendering needs inventing; the bug is that `handle_req_approve_action` renders it
  a *second* time, unconditionally, immediately after submitting the write — which
  is a background thread's worth of time before the write has happened.
- `lifecycle.handle_processed`, `handle_confirmation` and `handle_delivery` gain
  three parameters: `card_ts`, `req_data`, `history`. Each renders the card inside
  its own `on_success`, and appends its history line there too. A refusal branch
  (no row identified, nothing to write) returns without touching the card.
- Every `chat_update` call is removed from `src/app.py`. After this ticket the
  string appears nowhere in that file, and a source scan asserts it.
- **The history line moves with the render.** Today the listener appends
  "Processed by X on …" before calling the handler, so the line is written whether
  or not anything was. The handler appends it in `on_success` instead.
- **Accepted consequence:** when `Purchasing-Log.xlsx` is open on somebody's
  desktop, the card stays on the previous stage until the lock queue drains. That
  is the truth, and it is what ADR 0002 means by the workbook being the final
  reference. The queue already messages the thread about a delayed write; no
  second "pending" state is added to the card.
- `handle_cancel` already returns a bool and renders its own terminal card. It is
  the model the other handlers are being brought in line with. Do not change it.

### 3. The Approve button uses the payload it was handed

**The seam:** `src/app.py` listener + `src/lifecycle.py` handler. Existing.

- `handle_req_approve_action` reads the complete parsed request out of the button's
  `value` and then calls `lifecycle.handle_epif_processing()` without it.
  `handle_epif_processing` gains a `posted_payload: dict | None` parameter, and the
  listener passes what it already parsed.
- Resolution order inside `handle_epif_processing` becomes: `direct_file` →
  a PDF found in the thread → `posted_payload` → the metadata lookup → the
  "I couldn't find a PDF or purchase request" reply. The keyword path
  (`@Purchasing approved` typed into the thread of a card the modal posted) has no
  button payload, which is why the metadata lookup stays.
- **Delete the regex branch of `find_modal_request_in_thread`** — the block that
  matches `🛒 *New Purchase Request` and rebuilds thirteen fields with nine regexes
  over the bot's own prose, inventing `"vendor_contact_email": "sales@vendor.com"`
  along the way. `.scratch/lifecycle-and-buyers/spec.md` §1 named this function a
  defect and §3.8 ordered it deleted. Keep the Slack `metadata` branch, which is
  structured and correct, and rename the function `find_request_metadata_in_thread`
  so it stops claiming to parse prose.
- `slack_io.find_row_in_thread` is narrowed to the bot's own `Logged to row N`
  wording and stops matching bare `Row #N` in human prose. It is reached only when
  no `req_data` carries the row.

### 4. `PURCHASING_CHANNEL` is a constant with a home, and has no silent fallback

**The seam:** `src/config.py` plus the existing `test_layering_and_isolation.py`
source scan. Existing.

- `lifecycle.py` reads `os.environ.get("PURCHASING_CHANNEL")` inline and falls back
  to `config.ADMIN_ALERT_CHANNEL`, then to the requester's own DM. Invariant 4 says
  every constant has one home. Add `config.PURCHASING_CHANNEL` beside
  `ADMIN_ALERT_CHANNEL` and read it from there.
- **Remove the fallback chain.** If `PURCHASING_CHANNEL` is unset, the bot logs an
  error at startup through `path_validator`'s existing operator-facing check and
  refuses to post purchase requests, rather than quietly filing them in the alert
  channel. A wrong channel is worse than a loud failure: nobody acts on a request
  they do not see, and nobody notices it arrived in the wrong room.
- A source scan asserts `os.environ` is read nowhere in `src/` except `config.py`.

### 5. One word, matched exactly, with a reply when it is unknown

**The seam:** a new pure function in `src/text_rules.py` plus `dispatch_command`.
`dispatch_command` is already the single dispatch point and is already tested by
calling it with a fake `say` (`tests/test_08_assignment.py`). One new pure
function is the smallest addition that collapses fourteen substring checks into
one decision.

```python
def parse_keyword(stripped_text: str) -> str | None:
    """The first word of a mention-stripped message, matched exactly against the
    canonical vocabulary. None when it matches nothing."""
```

- Input is the *mention-stripped* text `text_rules.parse_mentions` already returns.
  ADR 0004 decision 8 is unchanged and binding: a lowercased Slack ID is
  alphanumeric and can contain `log`, `take` or `submit`.
- Take the first word, lowercase it, strip surrounding punctuation, and match it
  **exactly** against the keyword tuples in `config.py`. Two-word admin phrases
  (`remove vendor`, `add buyer`, `promote admin`) match on the first two words.
- **Delete the `("check", "test")` approval trigger** at the tail of
  `dispatch_command`. It is the single most dangerous line in the bot: it routes
  any message containing the substring "check" into an approval and an Excel write.
- `config.PROCESSED_KEYWORDS` keeps `submitted`/`submit`/`ordered` as silent
  backwards-compatible aliases — CONTEXT.md says these keep working so Charlie's
  habits do not break, and are taught nowhere. Exact matching does not change that;
  it stops `submitted` matching inside another word.
- Add the `else` branch the chain has never had:

```
🤔 I don't know the word "checkk".

In a request thread I understand:
   approved · assign · processed · confirmed · delivered · quote · decline

Or use the buttons on the request message above.
```

  The reply goes in-thread on an `app_mention`, and through `deny` on anything
  carrying a `response_url`. It is posted only when the bot was actually mentioned,
  so the `message` event firing on every channel message stays silent.

### 6. The posted card carries a buyer picker

**The seam:** `blocks.build_request_blocks` — a pure builder taking a dict and
returning blocks. Already the seam for every card assertion in
`test_regression_guards.py` and `test_08_assignment.py`. Read
`docs/adr/0005-assignment-can-be-a-button.md` first; it is the whole rationale.

- `build_request_blocks("posted", …)` renders a `users_select` in the same
  `actions` block as Approve and Decline, with `action_id` `req_assign_select` and
  a placeholder reading "Assign a buyer (optional)".
- **A `users_select` carries no arbitrary `value`.** Its action payload carries
  `selected_user` and the message's blocks. The handler recovers the request
  payload from the sibling Approve button's `value` inside
  `body["message"]["blocks"]`. Do not add a parallel store for this; the message is
  still the store (invariant 3) and `src/store.py` stays dead.
- Selecting a buyer does not approve anything. It records the selection on the card
  by re-rendering with `assignee_id` set, and Approve reads it from the button
  value it already carries. Approval remains the money decision and stays a
  deliberate second click.
- The selected person goes through the **same** checks a mentioned person does:
  on the buyers roster, and registered as a lab member. A refusal leaves the
  request unassigned and never refuses the approval — ADR 0004 decision 2,
  unchanged and binding.
- **If both a picker selection and an `@`-mention are present, the mention wins**,
  and the bot says which it used. ADR 0005 decision 4.
- Both inputs resolve to `lifecycle.handle_assign`. Invariant 1: no second
  implementation of assignment.

### 7. `get_valid_requesters()` returns roster names only

**The seam:** `src/roster.py` against a `tmp_path` roster file via
`monkeypatch.setattr(roster, "ROSTER_PATH", …)`. Existing seam,
`tests/test_roster.py` and `tests/test_11_roster_sync.py`.

**This contradicts nothing in an ADR, but it does resolve a live conflict between
`CONTEXT.md` and the code, and `docs/agents/domain.md` requires that be surfaced
rather than silently decided.** CONTEXT.md's **Register** entry says "A name nobody
holds is allowed and goes to an admin for approval." The code refuses it:
`roster.get_valid_requesters()` unions the roster's names with
`roster.DEFAULT_VALID_REQUESTERS`, a thirteen-name hardcoded list, and
`/roster-set-name` rejects anything outside that union. Ticket 11 deleted
`config.VALID_REQUESTERS` and moved the same hardcoded list one file over. The
glossary is right and the code is wrong.

- `get_valid_requesters()` returns the names in `roster.json` `requesters` and
  nothing else.
- `DEFAULT_VALID_REQUESTERS` is demoted to seed-only: it may populate a roster file
  that does not exist yet, and nothing else may read it. A source scan asserts it
  is referenced only inside `_get_initial_seed`.
- `validators.validate` is unchanged. It checks the requester name against
  `get_valid_requesters()`, and after this change that means "is a registered lab
  member" — which is what it was always trying to ask. Ticket 11's
  `sync_roster_lists` already appends every registered name to the workbook's
  `Requesters` table, so a name that validates is a name the dropdown has.
- **Migration check before this lands:** every name currently in the workbook's
  `Requesters` table must exist in `roster.json`. The reconciliation of 2026-09-16
  did exactly this, so the expected diff is none — but the ticket verifies it
  rather than assuming.

### 8. One `/roster-set-name` covering register, correct and rename

**The seam:** `app.handle_roster_set_name_command` and
`app.handle_roster_set_name_submit`, called directly with synthetic bodies —
the shape `test_regression_guards.py:test_roster_set_name_invalid_name_returns_error_and_posts_no_alert`
already uses. Plus `blocks` for the modal, which must become a builder rather than
a dict literal inside the listener so it can be asserted on without a client.

- Move the modal into `blocks.build_roster_set_name_view(user_id, current_name)`.
  A dict literal inside a listener cannot be tested without faking `views_open`.
- **The modal is state-aware.** It opens showing the name the user is currently
  registered under, or says they are not registered yet. It no longer prints the
  whole lab roster as a "your name must match one of" instruction, because that
  instruction is about to stop being true.
- Four outcomes, decided in this order on submit:
  1. **The name another lab member already holds** — refused outright, in the
     modal, as a field error. It never reaches an admin. This is the
     impersonation guard and it is the reason the ordering matters.
  2. **A normalization-only change to the submitter's own name** — differs from
     their current name only by case, leading/trailing whitespace, internal
     spacing or punctuation. Applied immediately, no approval. Correcting your own
     typo is not an admin's problem.
  3. **A different name, for a user already registered** — a rename. Goes to the
     alert channel for admin approval, on a button carrying
     `{"slack_id", "old_name", "new_name"}`.
  4. **Any name, for a user not in the roster** — registration. Goes to the alert
     channel on the existing `approve_new_requester` button. This is the case the
     current code refuses and CONTEXT.md says it must allow.
- The pending request lives in the alert-channel button's `value`, exactly as
  `approve_new_requester` already does. **No new state file.** `src/store.py`
  stays dead, invariant 3 unchanged.
- The submitter is told which of the four happened, in their own words: refused,
  applied, or waiting on an admin.
- The `chat_postEphemeral` call in this handler goes away with the rewrite.

### 9. `@Purchasing remove-member @user`

**The seam:** `roster.remove_member` (pure-ish, `tmp_path` roster) plus
`ops.handle_remove_member` (fake client + `say`). `ops.py` already holds
`handle_remove_buyer` and `handle_remove_approver` in exactly this shape.

- `roster.remove_member(slack_id) -> dict` hard-deletes the `requesters` entry and
  removes the ID from `admins`, `approvers` and `buyers` in one atomic save. It
  returns what it removed so the reply can name it. No tombstone.
- **Refused outright if it would leave the roster with no admin or no approver.**
  The check runs before any write. This is a lockout guard, not a warning.
- Admin-only, through `@Purchasing remove-member @user`, matched as a two-word
  keyword by decision 5. `REMOVE_MEMBER_KEYWORDS` goes in `config.py`.
- `remove-buyer` and `remove-approver` are unchanged and keep their meaning. The
  glossary's distinction — remove a role vs remove a member — is the point.
- **The workbook mirror stays append-only.** Ticket 11's requirement 2 is unchanged.
  After a removal the bot posts to `ADMIN_ALERT_CHANNEL` naming the sheet, the
  table and the **cell reference** of the now-orphaned dropdown entry, so a human
  can delete it. Order Log rows still reference the name, which is why this is a
  person's call and not the bot's.
- Removal takes effect on validation immediately, because decision 7 made
  `get_valid_requesters()` read the roster and nothing else.

### 10. An optional links field on interview Screen 2

**The seam:** `blocks.build_stage2_view` and `interview.build_parsed_from_stages`,
both pure. Existing — `tests/test_interview.py`.

- `build_parsed_from_stages` **already reads `stage2["link"]`** and already falls
  back to `epif_parser.first_url(purpose)`. The `link` key is already in the
  nineteen-key parsed dict, and `log_writer.build_row` already writes it to
  `config.COLUMN_LINK`. Almost nothing needs building: the field is missing from
  the modal, and that is all.
- Add a `block_link` optional `plain_text_input` to Screen 2, labelled for product
  pages and quote links, placed after Purpose. `optional: true`.
- `validators.validate` gains no rule for it. A request without a link is valid.
- Render it under the summary in the channel post and on the card, as its own
  bullet, only when present.
- **On the Excel question, follow the code, not the planning note.** The state doc
  recorded "not written to Excel", but `log_writer.build_row` has always written
  `parsed["link"]` to `COLUMN_LINK` when present, and the EPIF path already fills
  it. Making the modal path alone skip the column would make the two paths write
  different rows for the same purchase. The field writes to `COLUMN_LINK` like
  everything else. If that is wrong, it is a decision to reverse for both paths.

### 11. A live roster panel on App Home

**The seam:** `blocks.build_app_home_view`, pure, plus the shared text constants
it and `get_help_message` both read. `tests/test_09_app_home_help.py` is the
existing seam and already asserts the two surfaces cannot drift.

- `build_app_home_view()` gains a `user_id` parameter and a panel above the
  existing static content showing: the name this user is registered under, or that
  they are not registered yet; which of the three roles they hold; and a button
  opening the `/roster-set-name` modal.
- `blocks.py` already imports `roster`, and blocks may import storage under the
  layering rule. It still holds no Slack client and makes no API call.
- `_ADMIN_COMMANDS` gains `remove-member`, and `_SLASH_COMMANDS` gains whatever
  decision 8 changed about `/roster-set-name`. Both surfaces update from the one
  constant — never a second copy pasted into either function.
- Not registered is the interesting case: the panel leads with the fix, because
  that is the first thing that person needs.

## Testing Decisions

A good test here asserts what a person in Slack would see or what the workbook
would hold — the blocks, the text, the target channel, the cell — and never that a
function was called or exists. `docs/adr/0001` is binding: a failing test is fixed
or escalated, never muted. No `xfail`, no weakened assertion, no narrowed input.

**Prior art to copy, per area:**

| Area | Existing test to model on |
|---|---|
| Listener + denial + payload | `tests/test_regression_guards.py::test_permission_denial_*` |
| Lifecycle handler + fake client | `tests/test_08_assignment.py` |
| Card blocks | `tests/test_regression_guards.py::test_build_request_blocks_next_step_buttons` |
| App Home / help drift | `tests/test_09_app_home_help.py` |
| Roster against a tmp file | `tests/test_roster.py`, `tests/test_11_roster_sync.py` |
| Source/AST scans | `tests/test_layering_and_isolation.py`, `tests/test_regression_guards.py::test_only_log_writer_opens_workbook_path` |
| Workbook round-trip byte-identity | `tests/test_11_roster_sync.py` |

**Modules tested:** `app` (listeners and `dispatch_command`), `lifecycle`,
`blocks`, `roster`, `ops`, `text_rules`, `slack_io`, `config`.

**Assert on absence wherever absence is the point.** A permission test that only
checks the denial text passes when the action also went through. Every denial test
asserts all four: the denial text, that the lifecycle handler was **not** called,
that `chat_update` was **not** called, and that `replace_original=False` was passed.

**Specific behaviours that must be covered:**

1. A non-approver clicks Approve: the denial is ephemeral, `replace_original` is
   `False`, `handle_epif_processing` was not called, and `chat_update` was not
   called.
2. Every one of the button listeners, given a user without the role, leaves the
   message intact. Parametrise over the listeners rather than writing six copies.
3. An approval whose EPIF fails validation: no row written, no store entry, and
   the card still reads its previous state — asserted on the blocks, not on a flag.
4. A `handle_processed` call that cannot identify a row posts its "couldn't figure
   out which order" reply and calls `chat_update` **not at all**.
5. A `handle_processed` whose queued write fails: the thread gets the error and the
   card stays on `approved`.
6. A successful `handle_processed`: the card reads `processed` and history gained
   exactly one line — not two, not zero.
7. `chat_update` appears nowhere in `src/app.py` (source scan).
8. `os.environ` is read nowhere in `src/` outside `config.py` (AST scan, modelled
   on `test_only_log_writer_opens_workbook_path`).
9. Approving a card posted by `/new-purchase` logs the item shown on that card,
   asserted by the row values reaching `log_writer.build_row` — not by asserting
   which lookup function ran.
10. The regex branch of the modal lookup is gone: a thread containing a message
    whose text mimics the old `🛒 *New Purchase Request` summary but carries no
    metadata produces **no** request and no row.
11. "@Purchasing can you check this?" writes nothing, calls no lifecycle handler,
    and produces the unknown-word reply.
12. "@Purchasing please take a look" and "@Purchasing waiting on confirmation"
    likewise.
13. `@Purchasing approved` still approves, and `@Purchasing submitted` still marks
    processed — the documented aliases must survive exact matching.
14. A message mentioning a user whose Slack ID contains `log` or `submit` routes on
    the typed word, not the ID (regression on ADR 0004 decision 8).
15. The posted card renders a `users_select` alongside Approve, and the approved
    card does not.
16. Picking a non-buyer leaves the request unassigned **and** the approval still
    writes the row.
17. A picked buyer and a mentioned buyer together: the mention wins, and the reply
    names which was used.
18. `get_valid_requesters()` returns exactly the roster's names for a roster file
    containing one name — asserted on the specific name, not the count.
19. `DEFAULT_VALID_REQUESTERS` is referenced only inside `_get_initial_seed`
    (source scan).
20. `/roster-set-name` submitting a name another member holds: a field error, and
    **nothing posted to `ADMIN_ALERT_CHANNEL`**.
21. `/roster-set-name` submitting `"  isaac "` from the user registered as `Isaac`:
    applied immediately, nothing posted to the alert channel.
22. `/roster-set-name` submitting a brand-new name from an unregistered user: the
    alert channel gets one message with an `approve_new_requester` button carrying
    that name, and `roster.json` is unchanged until it is clicked.
23. `/roster-set-name` submitting a different existing-style name from a registered
    user: a rename request reaches the alert channel naming both names.
24. `remove_member` on a user holding all three roles removes the ID from all four
    lists in one save, and a re-read from disk confirms it.
25. `remove_member` on the last admin is refused, `roster.json` is byte-identical
    afterwards, and the reply says why.
26. `remove_member` on the last approver, likewise.
27. After `remove_member`, one message reaches `ADMIN_ALERT_CHANNEL` naming the
    sheet, the table and the cell reference of the orphaned dropdown entry.
28. After `remove_member`, the workbook is byte-identical — the mirror is
    append-only and a removal writes nothing to it.
29. After `remove_member`, `validators.validate` rejects that name.
30. Screen 2 renders `block_link` as optional; a submission omitting it validates
    and produces `parsed["link"]` from the purpose URL fallback.
31. A submission supplying a link produces that link in `parsed`, in the channel
    summary, and in `COLUMN_LINK` of the written row.
32. `build_app_home_view(user_id)` for a registered user shows that user's name;
    for an unregistered one it shows the registration prompt. Assert on the
    specific name, not on block count.
33. `remove-member` appears in both `build_app_home_view()` and
    `get_help_message()`, and the shared constant is the only place it is written.

Nothing in the suite touches the real `Purchasing-Log.xlsx`, the real
`roster.json`, or the network. `ruff check .`, `python scripts/check_tests_first.py`
and `pytest -q` must all pass with zero failures.

## Out of Scope

- **`src/store.py`.** Still imported by nothing, and nothing here changes that.
  Every decision above keeps request state on the message, per invariant 3.
  Building the request index is a separate effort with its own ADR.
- **Deleting `find_row_in_thread` outright.** `.scratch/lifecycle-and-buyers/spec.md`
  §3.8 ordered it, but the keyword path has no other way to resolve a row without
  the request index above. Decision 3 narrows it; deleting it waits.
- **Multi-EPIF batch intake** (`collect_thread_contents`, spec §3.2). The
  first-PDF-wins bug in `find_epif_in_thread` is real and unfixed, and it is a
  whole ticket set of its own.
- **The `notify()` helper** (spec §3.7) in its full four-audience form. Decision 1
  builds the denial half, which is the half that is losing messages in production.
- **Seeding the buyers roster.** That is ticket 10 in the previous set, still
  `human-task`, still waiting on a deploy. Finn is still missing from
  `roster.json`. No ticket here may assume he is there.
- **Making the repo private.** `claude/runbook-private-repo.md` in the Claude
  project covers it; it is a server visit, not code.
- **`roster.json` and `requests.json` being tracked in git.** The appendix of the
  previous spec and Part D of the runbook cover it. It blocks `@Purchasing update`
  and it is a human task at the server.
- **The frozen exe's roster path.** Harmless while production runs from source.
- **Teaching the bot the purchasing rotation.** Unchanged from the last set: the
  bot models a name chosen by a person who knows the rotation. A default buyer or a
  round-robin is a new ADR, not a constant.
- **Any change to `Purchasing-Log.xlsx` structure.** No new columns.

## Further Notes

**Deploying is a human step.** Isaac merges to `master`, then runs
`@Purchasing update`. Merging does not update the production server. No ticket may
assume otherwise, and no ticket may touch the server.

**Three documentation files are stale and should be corrected as part of whichever
ticket touches them, not as a separate cleanup:**

- `AGENTS.md` §2 still says "Today `blocks`, `handlers` and `listeners` are all
  inside one 2 855-line `src/app.py`, which is why every open ticket collides…
  Ticket 01 of the current set splits them." Ticket 01 landed. `src/app.py` is
  ~1 150 lines and the layers are split.
- `AGENTS.md` §9 trap 2 describes `config.GRAD_STUDENT_BUYERS` as live. Ticket 02
  removed it. Trap 8 says master has sixteen modified files uncommitted.
- `AGENTS.md` §9 trap 7 still uses "Claimed by Dylan" as its example. The word is
  **assigned**. The underlying trap is real and worth keeping — a buyer needs a
  `requesters` entry as well as a `buyers` entry — so fix the wording, not the trap.

**`CONTEXT.md` changes needed, by decision:**

- Decision 5 — the **Keyword** entry should say the first word is matched exactly,
  and that an unknown word gets a reply.
- Decision 7 — the **Requester** entry's sentence about validation should name
  `roster.json` as the only source and drop the implication that a hardcoded list
  backs it.
- Decision 9 — **remove a role vs remove a member** is already written correctly.
  No change; implement to it.

**Uncommitted work on `master` right now:** `CONTEXT.md` is modified and
`docs/adr/0005-assignment-can-be-a-button.md` is untracked. Commit both before
branching — ADR 0005 is binding on decision 6 and an implementing agent cannot
read a file that was never committed.

**On the four bugs leading this set:** decisions 1 through 4 are live in
production. They were found by reading the code while planning the roster work,
and bug 1's symptom — a request message vanishing when the wrong person clicks
Approve — has been observed in the lab. That is why the bugs come first and the
features come after, and why a ticket set that ships only decisions 1 and 2 is
still worth deploying on its own.
