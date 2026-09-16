# 11: Mirror the roster into the workbook's Roles & Lists sheet

**What to build:** Make `roster.json` the source of truth for the two name lists
on the workbook's `Roles & Lists` tab. When a name lands in `requesters` or
`buyers`, the bot appends it to the matching Excel list, so the Order Log's
`Requester Name` dropdown is current without anyone opening the file.

**Blocked by:** None. 08 is `done`; this does not touch 09's surface.

**Status:** done

**Read before starting:** invariant 2 in `AGENTS.md` ("one writer for the
workbook"), the module docstring of `src/log_writer.py` (it explains why the
workbook is edited as a zip and never through openpyxl), and
`docs/adr/0001-tests-first-and-no-muted-failures.md`, which is binding.
`CONTEXT.md` has the vocabulary.

## Why

The `Requester Name` dropdown on the Order Log is not a list of strings in the
sheet's data validation. It is the defined name `RequesterNames`, which points at
`Requesters[Requester Name]` — a real Excel table on the `Roles & Lists` tab. The
`Grad Student` list beside it is the second table, `GradStudents`, and it is the
list of people whose Date Processed / Date Confirmed cells the lab treats as
theirs.

Both tables are maintained by hand today. `/roster-set-name` writes `roster.json`
and nothing else, so a new lab member can register with the bot, be accepted, be
assignable — and still not appear in the dropdown the lab actually types into.
The two lists drift, silently, and the first symptom is someone picking a name
that is not there.

On 2026-09-16 the two were reconciled by hand and the sheet was given room to
grow. This ticket is what stops it drifting again.

## Starting state — already done by hand, do not redo it

The workbook on OneDrive has been updated. These are facts to build against, not
work to repeat:

- **`Requesters`** (`xl/tables/table4.xml`), ref `D4:D17`. Header `D4`, data
  `D5:D17` — the 13 names in `roster.json` `requesters`, in this order: Isaac,
  Smeet, Dylan, Alex, Casey, Prof. Hirst, Erich, Finn, Eddie, Katarina, Keyvan,
  Hansel, Zehui. `Charlie H.` and `Copeland` were removed; they had no Slack ID
  behind them.
- **`GradStudents`** (`xl/tables/table3.xml`), ref `A4:B7`. Header row 4, names
  `A5:A7` — the three IDs in `roster.json` `buyers`: Isaac, Smeet, Dylan. Colour
  in `B5:B7`. (Finn was dropped because he is not yet a buyer. Ticket 10 adds
  him; when it runs, this ticket's code is what puts him back in the sheet.)
- **The sheet is `xl/worksheets/sheet2.xml`.** `Roles & Lists` is the second
  sheet; `config.SHEET_XML` points at sheet1 and is the Order Log.
- **Rows 5 through 49 already exist** in the sheet XML with their styles:
  `<c r="A{n}" s="3"/>`, `<c r="B{n}"/>`, `<c r="D{n}" s="3"/>`. This is
  deliberate, and it is the same guarantee `log_writer` relies on for Order Log
  rows 12–1999: **the rows are there, the bot fills blanks, it never creates
  structure.**
- **Row 50 is the hard floor.** The instructional notes block that used to start
  at row 20 was moved down to row 50 to make that room. Writing at or below row
  50 would overwrite it.
- **The defined names need no edit.** `RequesterNames`, `GradStudentNames` and
  `ColorOptions` are table-column references (`Requesters[Requester Name]` and so
  on), so they follow the table's `ref` automatically. `xl/workbook.xml` is not
  touched by this ticket.

## Requirements, stated as requirements

1. **The writer is `log_writer`, and nothing else opens the file.** This is
   invariant 2 and it is not negotiable. Add to `src/log_writer.py`:

   ```python
   def sync_roster_lists(workbook_path: str = None) -> dict:
       """Append any roster name missing from the Roles & Lists tables.

       Returns {"requesters_added": [...], "grads_added": [...], "skipped": [...]}.
       """
   ```

   No new module opens `Purchasing-Log.xlsx`. No openpyxl, anywhere, ever — a
   load-and-save through openpyxl silently destroys the x14 conditional
   formatting, `xl/metadata.xml` and the web-extension parts, and there is
   nothing in the logs afterwards to explain it.

2. **Append-only. Never delete, never reorder.** A name already in the column
   (compared case-insensitively, trimmed) is left exactly as it is. A name in
   the sheet but not in the roster is left alone. The sheet is edited by humans
   and the bot must never be the reason someone's typing disappeared.

3. **Fill existing cells; do not create rows.** Reuse the `_cell_pattern` /
   `_render_cell` pair already in the module: match the `<c>` element, keep its
   `s="…"` style index, write the value as `t="inlineStr"`. If the target `<c>`
   is absent from the XML, that is a **failure**, not a cue to synthesise one —
   raise and let requirement 6 handle it.

4. **The table `ref` and its `autoFilter ref` grow in lockstep.** Both tables
   carry `<table … ref="…">` and `<autoFilter ref="…">` and the two must match.
   Appending two requesters takes `Requesters` from `D4:D17` to `D4:D19`; both
   attributes change. A table whose range does not cover the new row means the
   name is in the cell and absent from the dropdown, which is the exact failure
   this ticket exists to prevent.

5. **The colour cell is left blank.** `GradStudents` column B is optional and
   human-chosen. Appending a grad student writes column A only.

6. **Running out of room is reported, never guessed at.** The last writable row
   is 49 — put it in `config`, do not inline it. If an append would need row 50
   or below, write nothing for that name, add it to `skipped`, log it, and post
   one message to `config.ADMIN_ALERT_CHANNEL` naming the name and saying the
   `Roles & Lists` tab needs more rows above the notes block. Never write over
   row 50.

7. **The trigger lives in `roster.py`, not in the handlers.** Call the sync from
   `add_requester`, `add_buyer` and `remove_buyer`, immediately after
   `save_roster()`. One trigger point covers `/roster-set-name`, the admin
   approve-new-requester button in `app.py:486`, and
   `ops.handle_add_buyer` / `handle_remove_buyer` — and covers every caller
   written after this ticket, which patching three handlers would not. This is
   invariant 1 applied to the roster.

   `remove_buyer` is deliberately included and deliberately does nothing to the
   sheet under requirement 2. Wire it so the behaviour is asserted, not assumed.

8. **The workbook write goes through the queue, and a failure never fails the
   roster change.** Submit via `queue_worker.submit_write_task(...)` — the
   workbook is routinely open in Excel on somebody's desktop, and the queue is
   what turns "locked, try later" into "written" instead of "lost". `roster.json`
   is the source of truth; the sheet is a mirror. `add_buyer` must return
   normally, and the buyer must be a buyer, even if the workbook is locked,
   missing, or on an unreachable OneDrive path.

9. **The sync is inert when there is no workbook.** If `config.WORKBOOK_PATH`
   does not exist, return an empty report and log at debug. The test suite calls
   `roster.add_requester` in a dozen places and must not start touching Excel.
   Add `config.ROSTER_XLSX_SYNC` (default on, overridable by env) so a test can
   switch it off explicitly rather than by accident of the filesystem.

10. **One source of truth for which names are valid.** `/roster-set-name` today
    validates against `config.VALID_REQUESTERS` (`src/app.py:312`), a hardcoded
    set still containing `Charlie H.` and `Copeland` and missing `Hansel` and
    `Zehui` — so two people already in `roster.json` are refused by the modal
    that exists to register them. `src/validators.py:76` already prefers
    `roster.get_valid_requesters()`. Make the modal agree with the validator:
    `app.py` reads `roster.get_valid_requesters()`, `config.VALID_REQUESTERS` is
    **deleted**, and `roster.DEFAULT_VALID_REQUESTERS` — the seed used only when
    `roster.json` does not exist — is updated to the 13 current names. This is
    invariant 4; it is the same drift as the sheet, one file over.

11. **Every new constant has one home in `config.py`**: the roster sheet's XML
    part name, both table part names, the first and last writable row, and the
    column letters for the two lists. No literals in `log_writer`.

## Acceptance criteria

- [x] `log_writer.sync_roster_lists` exists with the signature above and is the
      only new code that opens the workbook
- [x] The string `openpyxl` appears nowhere in `src/`
- [x] A test builds a fixture workbook, adds a requester not in the sheet, and
      asserts the name lands in the first free `D` row **and** that
      `Requesters`' `ref` and `autoFilter ref` both grew by one row
- [x] A test adds a name already in the sheet in different case (`"isaac"`) and
      asserts the sheet XML is **byte-identical** afterwards
- [x] A test asserts a name present in the sheet but absent from `roster.json`
      is still there after a sync — assert on the specific name, not the count
- [x] A test adds a buyer and asserts the name lands in column `A`, that column
      `B` of that row is still empty, and that `GradStudents`' ref grew
- [x] A test asserts `remove_buyer` removes the ID from `roster.json` and leaves
      the sheet byte-identical
- [x] A test fills the sheet to row 49, adds one more name, and asserts: nothing
      written at or below row 50, the name is in the returned `skipped` list, and
      one message went to `ADMIN_ALERT_CHANNEL`
- [x] A test with the workbook locked (`~$Purchasing-Log.xlsx` present) asserts
      `roster.add_buyer` still returns and the ID **is** in `roster.json`
- [x] A test with `config.WORKBOOK_PATH` pointing at a nonexistent file asserts
      `roster.add_requester` succeeds and no exception escapes
- [x] A round-trip test asserts that after a sync every other part of the zip is
      byte-identical to the input — specifically `xl/worksheets/sheet1.xml`,
      `xl/styles.xml`, `xl/metadata.xml` and the `xl/webextensions/` parts — and
      that the part **order** in the archive is unchanged
- [x] A test asserts the sheet still parses and that `x14:conditionalFormatting`
      is still present in `sheet1.xml` after a sync
- [x] `/roster-set-name` accepts `Hansel` and `Zehui`, and `config.VALID_REQUESTERS`
      appears nowhere in `src/`
- [x] `ruff check .`, `python scripts/check_tests_first.py` and `pytest -q` all pass

## Out of scope

- Writing the buyer into an Order Log column. ADR 0004 decision 7 says no, and
  that has not changed.
- Reading the sheet back to discover names the bot does not know. The roster is
  the source of truth; the sheet is the mirror. One direction only.
- The other dropdown lists on the tab (EPIF Category, Delivery Room, Fund,
  Project ID, Urgency, Status, How Buying). They are driven by
  `OFFSET`/`COUNTA` defined names, not tables, and no roster field corresponds
  to them. Leave them alone.
- Extending the `Roles & Lists` tab past row 49. Requirement 6 reports it; a
  human does it.
- `src/store.py`. Still imported by nothing. Leave it alone.

## Comments

### 2026-09-16

- Implemented `log_writer.sync_roster_lists(workbook_path=None, client=None)`:
  - Append-only mirror of `roster.json` requesters and buyers into `Roles & Lists` sheet (`sheet2.xml`).
  - Fills existing cells (`D` for requesters, `A` for grad buyers) preserving XML styles (`s="3"`).
  - Column `B` (color) is left blank for new grad buyers.
  - Updates table `ref` and `autoFilter ref` in lockstep for both `Requesters` (`table4.xml`) and `GradStudents` (`table3.xml`).
  - Enforces row 50 hard floor: skips names exceeding row 49, adds to `skipped` list, logs warning, and sends alert to `config.ADMIN_ALERT_CHANNEL`.
  - Inert when no workbook exists or when `config.ROSTER_XLSX_SYNC` is false.
  - Preserves archive part order and byte-identity for all untouched parts (including `x14:conditionalFormatting` in `sheet1.xml`).
- Wired roster triggers:
  - `roster.add_requester`, `roster.add_buyer`, and `roster.remove_buyer` call `_trigger_roster_sync()` after saving `roster.json`.
  - Submits write task through `queue_worker.submit_write_task` so workbook locks or missing paths never fail roster updates.
  - `remove_buyer` leaves the sheet byte-identical.
- Reconciled validation source of truth:
  - Deleted `config.VALID_REQUESTERS` and removed all references across `src/`.
  - Updated `roster.DEFAULT_VALID_REQUESTERS` to 13 current names (`Isaac`, `Smeet`, `Dylan`, `Alex`, `Casey`, `Prof. Hirst`, `Erich`, `Finn`, `Eddie`, `Katarina`, `Keyvan`, `Hansel`, `Zehui`).
  - Updated `/roster-set-name` command and submission handler in `src/app.py` to validate against `roster.get_valid_requesters()`, now accepting `Hansel` and `Zehui`.
- Tests:
  - Added `tests/test_11_roster_sync.py` with 14 test functions covering all acceptance criteria.
  - Verified full test gate: `ruff check .` (clean), `python scripts/check_tests_first.py` (clean), `pytest -q` (169 passed, 31 skipped).

