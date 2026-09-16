# 19: One `/roster-set-name` covering register, correct and rename

**What to build:** One command that handles all three cases a lab member can be
in. A new member registers. Someone who typed their own name wrong fixes it. A
real rename goes to an admin. A name another member already holds is refused
outright and never reaches an admin.

**Blocked by:** 12, 18

**Status:** ready-for-agent

**Read before starting:** `CONTEXT.md`'s **Register** entry (this ticket is what
finally implements it) and `docs/adr/0001-tests-first-and-no-muted-failures.md`,
which is binding. Ticket 18 must be `done` — this ticket's central premise is
that a name nobody holds is allowed, and 18 is what allows it.

## Why

`/roster-set-name` refuses any name outside a hardcoded list, so a new lab member
is told their own name "is not recognized" with no way forward. Someone already
registered who typed their name wrong is told only "you are already registered"
and cannot correct it. The modal prints the entire lab roster as a "your name
must match one of" instruction — an instruction that ticket 18 just made false.

Isaac's decision, recorded: one command, not two. Anyone may submit their own
name; a brand-new name still goes through admin approval; correcting your own
name needs no approval, but changing to a **different** name does, to prevent
impersonation.

## Requirements, stated as requirements

1. **Move the modal into `blocks.build_roster_set_name_view(user_id, current_name)`.**
   A dict literal inside a listener cannot be asserted on without faking
   `views_open`. This is the seam the tests need.

2. **The modal is state-aware.** It opens showing the name this user is currently
   registered under, or says they are not registered yet. It **no longer prints the
   whole lab roster** as a "your name must match one of" instruction, because that
   instruction has stopped being true.

3. **Four outcomes, decided on submit in this order. The ordering is the
   impersonation guard and it is not an implementation detail:**

   1. **A name another lab member already holds** — refused outright, in the modal,
      as a field error. **It never reaches an admin.**
   2. **A normalization-only change to the submitter's own name** — differs from
      their current name only by case, leading/trailing whitespace, internal
      spacing or punctuation. **Applied immediately, no approval.** Correcting your
      own typo is not an admin's problem.
   3. **A different name, for a user already registered** — a rename. Goes to
      `ADMIN_ALERT_CHANNEL` for approval, on a button carrying
      `{"slack_id", "old_name", "new_name"}`.
   4. **Any name, for a user not in the roster** — registration. Goes to the alert
      channel on the existing `approve_new_requester` button. **This is the case
      the current code refuses and `CONTEXT.md` says it must allow.**

4. **No new state file.** The pending request lives in the alert-channel button's
   `value`, exactly as `approve_new_requester` already does. Invariant 3 unchanged,
   `src/store.py` stays dead.

5. **The submitter is told which of the four happened, in their own words** —
   refused, applied, or waiting on an admin. Outcome 4 says explicitly that the
   name is waiting on an admin, so the person waits instead of retrying.

6. **The `chat_postEphemeral` call in `handle_roster_set_name_submit` goes away
   with the rewrite**, onto `slack_io.deny` (ticket 12). After this ticket **zero**
   `chat_postEphemeral` call sites remain in `src/`. Update invariant 5's guard
   test to assert zero rather than leaving it asserting one.

7. **The approval buttons write through `roster.add_requester` / the rename
   equivalent**, so ticket 11's `sync_roster_lists` fires and the workbook dropdown
   follows. Do not write `roster.json` directly from the handler.

## Acceptance criteria

- [ ] `blocks.build_roster_set_name_view(user_id, current_name)` exists, is pure,
      and is asserted on without faking `views_open`
- [ ] The modal shows the submitter's current registered name; for an unregistered
      user it says so — asserted on the **specific name**, not on block count
- [ ] The modal does not contain the full lab roster
- [ ] Submitting a name **another member holds**: a field error, and **nothing
      posted to `ADMIN_ALERT_CHANNEL`** — assert on the absence
- [ ] Submitting `"  isaac "` from the user registered as `Isaac`: applied
      immediately, `roster.json` updated, nothing posted to the alert channel
- [ ] Submitting a brand-new name from an **unregistered** user: the alert channel
      gets one message with an `approve_new_requester` button carrying that name,
      and `roster.json` is **unchanged until it is clicked**
- [ ] Clicking that button registers the name and triggers `sync_roster_lists`
- [ ] Submitting a different name from a **registered** user: a rename request
      reaches the alert channel naming **both** names
- [ ] Each of the four outcomes tells the submitter which one happened
- [ ] `chat_postEphemeral` appears nowhere in `src/`, and the invariant 5 guard
      test asserts zero
- [ ] `ruff check .`, `python scripts/check_tests_first.py` and `pytest -q` all pass

## Out of scope

- `remove-member`. Ticket 20.
- The App Home roster panel and its button into this modal. Ticket 22, which is
  written against this ticket's finished modal.
- Any change to how `approve_new_requester` itself is rendered beyond carrying the
  rename payload.
- A tombstone or history of previous names. Not asked for.
