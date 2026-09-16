# 18: `get_valid_requesters()` returns roster names only

**What to build:** A genuinely new lab member stops being told their own name
"is not recognized". The thirteen-name hardcoded list stops being a gate and goes
back to being what it says it is — a seed for a roster file that does not exist yet.

**Blocked by:** None (can start immediately)

**Status:** done

**Read before starting:** `CONTEXT.md`'s **Register** and **Requester** entries,
`docs/agents/domain.md` on surfacing glossary/code conflicts, and
`docs/adr/0001-tests-first-and-no-muted-failures.md`, which is binding.

## Why

This resolves a live conflict between `CONTEXT.md` and the code, and
`docs/agents/domain.md` requires that be surfaced rather than silently decided.

`CONTEXT.md`'s **Register** entry says: "A name nobody holds is allowed and goes
to an admin for approval." The code refuses it. `roster.get_valid_requesters()`
unions the roster's names with `roster.DEFAULT_VALID_REQUESTERS`, a thirteen-name
hardcoded list, and `/roster-set-name` rejects anything outside that union.

Ticket 11 deleted `config.VALID_REQUESTERS` and moved the same hardcoded list one
file over, so the drift moved house rather than ending.

**The glossary is right and the code is wrong.**

## Requirements, stated as requirements

1. **`get_valid_requesters()` returns the names in `roster.json` `requesters` and
   nothing else.** No union, no defaults.

2. **`DEFAULT_VALID_REQUESTERS` is demoted to seed-only.** It may populate a roster
   file that does not exist yet, and nothing else may read it. A source scan
   asserts it is referenced only inside `_get_initial_seed`.

3. **`validators.validate` is unchanged.** It already checks the requester name
   against `get_valid_requesters()`, and after this change that means "is a
   registered lab member" — which is what it was always trying to ask. Ticket 11's
   `sync_roster_lists` already appends every registered name to the workbook's
   `Requesters` table, so a name that validates is a name the dropdown has.

4. **Migration check before this lands, verified rather than assumed:** every name
   currently in the workbook's `Requesters` table must exist in `roster.json`. The
   reconciliation of 2026-09-16 did exactly this, so the expected diff is **none** —
   but the ticket checks, and reports in `## Comments` if it is not none.

5. **`CONTEXT.md`'s Requester entry is updated in this ticket:** its sentence about
   validation names `roster.json` as the only source, and drops the implication
   that a hardcoded list backs it.

## Acceptance criteria

- [x] `get_valid_requesters()` returns exactly the roster's names for a roster file
      containing one name — asserted on **the specific name**, not the count
- [x] A name in `DEFAULT_VALID_REQUESTERS` but not in `roster.json` does **not**
      validate
- [x] A source scan asserts `DEFAULT_VALID_REQUESTERS` is referenced only inside
      `_get_initial_seed`
- [x] A roster file that does not exist is still seeded with the thirteen names,
      and a test asserts the seeded file's contents
- [x] `validators.validate` is unchanged and its existing tests pass untouched
- [x] The migration check is run and its result recorded in `## Comments` —
      the list of workbook `Requesters` names not present in `roster.json`, or "none"
- [x] `CONTEXT.md`'s Requester entry names `roster.json` as the only source
- [x] `ruff check .`, `python scripts/check_tests_first.py` and `pytest -q` all pass

## Out of scope

- The `/roster-set-name` modal itself — the four outcomes, the state-awareness,
  the impersonation guard. Ticket 19 builds those on top of this change.
- `remove-member`. Ticket 20, which relies on this ticket for removal to take
  effect on validation.
- Any change to the workbook's `Requesters` table. Ticket 11's mirror is
  append-only and stays that way.

## Comments

### 2026-09-16 Implementation summary

1. **Roster-only validation**: `src/roster.py:get_valid_requesters()` now returns `set(data.get("requesters", {}).values())` directly from `roster.json`, with no unioning against hardcoded lists or defaults.
2. **Seed demotion**: `DEFAULT_VALID_REQUESTERS` is now referenced only within `_get_initial_seed()` to populate initial `requesters` when a `roster.json` file does not yet exist.
3. **Documentation**: Updated `CONTEXT.md` under **Requester** to state that `roster.json` is the sole source for requester validation, eliminating the implication of a hardcoded fallback. Also updated `src/roster.py` module docstring.
4. **Migration verification**: Ran migration verification against the OneDrive workbook (`xl/tables/table4.xml` and `xl/worksheets/sheet2.xml`). The 13 names in the workbook's `Requesters` table (`Isaac`, `Smeet`, `Dylan`, `Alex`, `Casey`, `Prof. Hirst`, `Erich`, `Finn`, `Eddie`, `Katarina`, `Keyvan`, `Hansel`, `Zehui`) match `roster.json` `requesters` identically. List of workbook names not present in `roster.json`: **none**.
5. **Test coverage**:
   - `test_roster_first_run_seeding`: Asserts that a missing roster file gets seeded with the thirteen names and saved to disk.
   - `test_get_valid_requesters_returns_exactly_roster_names_for_single_name`: Asserts single-name roster file validation on the exact name (`{"Alice"}`).
   - `test_name_in_default_valid_requesters_not_in_roster_does_not_validate`: Asserts that default seed names not in `roster.json` do not validate.
   - `test_default_valid_requesters_referenced_only_in_get_initial_seed`: AST source scan asserting `DEFAULT_VALID_REQUESTERS` is referenced only inside `_get_initial_seed()` and nowhere else in `src/`.
   - `test_08_assignment.py`: Added `Isaac` to test's isolated `clean_roster` fixture.
6. **Local gate results**:
   - `ruff check .`: All checks passed.
   - `python scripts/check_tests_first.py`: Passed.
   - `pytest -q`: 172 passed, 31 skipped (0 failures).
