# 20: `@Purchasing remove-member @user`

**What to build:** A graduating student leaves cleanly. One admin command ends a
membership and strips all three roles in a single save, refuses if it would leave
the lab with no admin or no approver, and names the leftover workbook dropdown
cell so a human can delete it.

**Blocked by:** 16, 18

**Status:** done

**Read before starting:** `CONTEXT.md` on **remove a role vs remove a member** —
it is already written correctly; implement to it. Ticket 11 requirement 2 (the
workbook mirror is append-only) is unchanged and binding, as is
`docs/adr/0001-tests-first-and-no-muted-failures.md`.

## Why

`remove-buyer` and `remove-approver` strip a role. There is no way to remove a
**person**. Katarina graduating leaves her in the roster and in the workbook's
dropdown forever, and her name keeps validating on new requests.

The two meanings must stay distinct: `remove-buyer` means "off purchasing duty",
`remove-member` means "left the lab".

## Requirements, stated as requirements

1. **`roster.remove_member(slack_id) -> dict`** hard-deletes the `requesters`
   entry and removes the ID from `admins`, `approvers` and `buyers` **in one atomic
   save**. It returns what it removed, so the reply can name it. **No tombstone.**

2. **Refused outright if it would leave the roster with no admin or no approver.**
   The check runs **before any write**. This is a lockout guard, not a warning.

3. **Admin-only, through `@Purchasing remove-member @user`**, matched as a two-word
   keyword by ticket 16. `REMOVE_MEMBER_KEYWORDS` goes in `config.py` — invariant 4,
   one home per constant.

4. **`remove-buyer` and `remove-approver` are unchanged** and keep their meaning.
   The glossary's distinction is the point.

5. **The workbook mirror stays append-only.** A removal writes **nothing** to the
   workbook. After a removal the bot posts to `ADMIN_ALERT_CHANNEL` naming the
   sheet, the table and the **cell reference** of the now-orphaned dropdown entry,
   so a human can delete it by hand. Order Log rows still reference the name, which
   is why this is a person's call and not the bot's.

6. **Removal takes effect on validation immediately**, because ticket 18 made
   `get_valid_requesters()` read the roster and nothing else. Assert it rather than
   assume it.

7. **`ops.py` is the home for the handler.** It already holds `handle_remove_buyer`
   and `handle_remove_approver` in exactly this shape.

## Acceptance criteria

- [x] `roster.remove_member` on a user holding all three roles removes the ID from
      **all four lists in one save**, and a re-read from disk confirms it
- [x] `remove_member` on the **last admin** is refused, `roster.json` is
      byte-identical afterwards, and the reply says why
- [x] `remove_member` on the **last approver**, likewise
- [x] A non-admin issuing `remove-member` is denied ephemerally and no write occurs
- [x] After a removal, **one** message reaches `ADMIN_ALERT_CHANNEL` naming the
      sheet, the table and the **cell reference** of the orphaned dropdown entry
- [x] After a removal, the workbook is **byte-identical** — the mirror is
      append-only and a removal writes nothing to it
- [x] After a removal, `validators.validate` rejects that name
- [x] `@Purchasing remove-member @user` matches as a two-word keyword and
      `@Purchasing remove-buyer @user` still strips only the buyer role, leaving the
      `requesters` entry intact — assert both in the same test
- [x] `REMOVE_MEMBER_KEYWORDS` lives in `config.py` and appears nowhere else as a literal
- [x] `ruff check .`, `python scripts/check_tests_first.py` and `pytest -q` all pass

## Out of scope

- Deleting anything from the workbook. Requirement 5 — a human does it.
- A tombstone, an archive, or a "former member" state. Requirement 1: hard delete.
- Reassigning or cancelling the removed member's in-flight requests. Not asked
  for; note it in `## Comments` if it comes up.
- Surfacing `remove-member` in App Home and `/purchasing-help`. Ticket 22.

## Comments

### 2026-09-17

- Implemented `roster.remove_member(slack_id)`:
  - Hard-deletes `requesters` entry and strips `admins`, `approvers`, and `buyers` in one atomic save.
  - Lockout guard: raises `ValueError` before any disk write if removing the user would leave the roster with zero admins or zero approvers.
  - Returns summary dict with `slack_id`, `name`, `roles`, `roles_removed`, and `requester_removed`.
  - Leaves workbook untouched (workbook mirror remains append-only).
- Implemented `log_writer.find_requester_cell(name, workbook_path)`:
  - Reads workbook zip read-only to locate the cell reference (e.g. `D14`) of the requester in `Roles & Lists` sheet `Requesters` table.
- Implemented `ops.handle_remove_member`:
  - Admin-only command. Non-admin users are denied ephemerally via `slack_io.deny`.
  - Calls `roster.remove_member` and catches lockout refusals, replying with the refusal reason.
  - Sends exactly one alert to `ADMIN_ALERT_CHANNEL` naming the sheet, table, and exact cell reference of the orphaned dropdown entry.
- Added `config.REMOVE_MEMBER_KEYWORDS = ("remove-member", "remove member")` and wired in `app.dispatch_command`.
- Added test suite in `tests/test_20_remove_member.py` covering all 9 acceptance criteria.
- Gate verified: `ruff check .` clean, `check_tests_first.py` clean, `pytest -q` 262 passed, 31 skipped.
