# 02: Grad buyers become a roster list of Slack IDs

**What to build:** Replace `config.GRAD_STUDENT_BUYERS` — a hardcoded set of
display-name strings — with a `buyers` list of Slack IDs in the roster, editable
from Slack by an admin like every other roster list.

**Blocked by:** 01

**Status:** ready-for-agent

Read `docs/adr/0002-request-lifecycle-and-surfaces.md` decision 5 first.
`docs/adr/0001-tests-first-and-no-muted-failures.md` is binding.

## Why

`GRAD_STUDENT_BUYERS = {"Isaac", "Dylan", "Smeet", "Finn"}` in `config.py` is the
only role in the system that is not a roster concept. Because the entries are
names and not IDs:

- the claim broadcast cannot `<@…>` anyone — it prints plain text nobody is
  notified about;
- a buyer with no roster entry can only claim if `resolve_requester`'s
  profile-name fallback happens to match;
- adding Finn, Smeet and Dylan is a code edit plus a restart, when it should be an
  admin action from Slack.

## Requirements

- **`is_buyer` takes a Slack ID.** Do not add a name-based variant. Matching on
  names is the defect this ticket removes.
- **`load_roster` must backfill the `buyers` key** for rosters saved before this
  ticket. It already backfills `requesters`, `admins`, `approvers` and `vendors` —
  follow that pattern exactly. A roster file written yesterday must not crash the
  bot today.
- **A buyer needs two roster entries.** Membership in `buyers` gets them past the
  permission check, but the history line ("Claimed by Dylan") comes from
  `resolve_requester()`, which reads `requesters`. When `add-buyer` targets a user
  with no `requesters` entry, still add them, but **reply in Slack with a visible
  warning** naming the user and telling the admin to run `/roster-set-name` for
  them. A log line is not enough — the symptom otherwise surfaces much later as a
  failed claim.

## Acceptance criteria

- [ ] `"buyers": []` is in the roster schema in `_get_initial_seed()`, storing
      Slack IDs exactly as `approvers` does
- [ ] `load_roster` backfills a missing `buyers` key; a roster JSON without it
      loads and `get_buyers()` returns `[]` rather than raising
- [ ] `get_buyers()`, `add_buyer(slack_id)`, `remove_buyer(slack_id)` and
      `is_buyer(slack_id)` exist in `roster.py`, mirroring the approver functions
- [ ] `is_buyer` takes an ID; there is no name-based variant anywhere
- [ ] Admin-only `@p-bot add-buyer @user` and `@p-bot remove-buyer @user` exist
      alongside the approver keywords, with the same permission check
- [ ] `/roster-list` output has a **Purchase Buyers** section
- [ ] `config.GRAD_STUDENT_BUYERS` is deleted, and every read of it is gone
      (`grep -rn GRAD_STUDENT_BUYERS src/` returns nothing)
- [ ] `add-buyer` on a user with no `requesters` entry adds the buyer **and**
      surfaces the warning to the admin in Slack
- [ ] A test asserts `get_buyers()` returns `[]` for a roster with no `buyers` key
- [ ] A test asserts the no-requester-entry warning **reaches the admin**, not just
      that the roster write happened
- [ ] A test asserts `add-buyer` from a non-admin is refused and writes nothing
- [ ] `ruff check .`, `python scripts/check_tests_first.py` and `pytest -q` all pass

## Human step, not part of this ticket

Seeding the live roster with Finn's, Smeet's and Dylan's Slack member IDs needs a
Slack session and the real IDs. After deploying, Isaac runs `@p-bot add-buyer` for
each and confirms each has a requester name.

## Comments
