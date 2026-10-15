# 124: The Filled EPIF is dated at approval; the interview stops asking for a date

**Status:** in-progress

**Runner:** any

**Auto-merge:** yes

**Blocked by:** 121

**Spec:** `.scratch/bom-template-and-epif-date/spec.md` (Part B, stories 9, 15, 18)
**Binding:** `docs/adr/0001-tests-first-and-no-muted-failures.md`; `docs/adr/0007-purchase-path-and-generated-epif.md`
**Glossary:** `CONTEXT.md` — **EPIF date**, **Request date**, **Filled EPIF**

## What to build

The request carries two dates instead of one.

- **`request_date`** — the day the request is posted. It goes in workbook column M.
- **`epif_date`** — the date printed in the EPIF's Date of Purchase field.

A Filled EPIF is dated the day it is made: at approval, or at a switch to the EPIF path. The
interview and Edit no longer ask for a date.

Today one value, `parsed["date_of_purchase"]`, comes from the `block_date_of_purchase`
datepicker. It is typed on the day the form is filled in, and feeds both
`log_writer.build_row` (column M) and `epif_filler.fill_epif`.

1. **Every modal that renders `block_date_of_purchase` stops rendering it**:
   `blocks.build_stage2_view` (also used for Edit) and `blocks.build_workday_details_view`.
   Remove the matching extraction and error mapping in `app.handle_stage2_submit`,
   `app.handle_workday_details_submit` and `app.handle_edit_submit`.
2. **`interview.build_parsed_from_stages`** sets `request_date` to the posting day
   (`datetime.date.today()`, through one helper so tests can pin it, as `app._today` is used
   today).
3. **`log_writer.build_row`** writes `config.COLUMN_DATE_OF_REQUEST` from `request_date`,
   falling back to `date_of_purchase`. For an uploaded EPIF, `epif_parser.parse_epif`'s
   `date_of_purchase` is copied into both values, so uploaded EPIFs log as today.
4. **`epif_filler.fill_epif`** writes Date of Purchase from `epif_date`, falling back to
   `date_of_purchase`.
5. **The Filled EPIF's date** — where `lifecycle.finalize_purchase_request` and
   `lifecycle._finalize_switch_to_epif` call `fill_epif`, set `parsed["epif_date"]` to the
   day it is made before the call, and store it on the request payload as `epif_date`
   (ISO string) so ticket 125 can read it.
6. **Docstrings** — update `epif_filler`'s and `log_writer.build_row`'s to say why the two
   dates are separate.

## Acceptance criteria

- [ ] `test_no_modal_asks_for_a_date` builds `blocks.build_stage2_view` (new request and edit meta) and `blocks.build_workday_details_view`, and asserts no block has `block_id == "block_date_of_purchase"`.
- [ ] `test_filled_epif_is_dated_the_approval_day`: posted on day D1 and approved on day D2 — pin both dates by monkeypatching the one date helper from step 2, nothing else.
  - Drive approval through `lifecycle.finalize_purchase_request` as `tests/test_45_epif_approval_archives.py` does.
  - Read the archived PDF from the temp `EPIFS_DIR` with `epif_parser.parse_epif`; its `date_of_purchase` is D2.
  - The row dict passed to the workbook writer has column M equal to D1.
  - In the same function, an uploaded EPIF dated 09/01/2026 logs column M as 09/01/2026 and is archived unchanged.
- [ ] Every existing test that submits Screen 2, Edit or Workday-details views is rewritten in place under the same name to stop sending `block_date_of_purchase`. No test function is deleted. (no test: the full suite in the gate proves it)

May fake: the Slack client, the lock queue's workbook write (capture the row dict). Must be real: `fill_epif` on `tests/fixtures/EPIF_TEMPLATE_HIRST.pdf`, `parse_epif`, `log_writer.save_epif` into a temp directory.

## Gate

Run all four, in CI's order, and all must pass:

    ruff check .
    python scripts/check_tests_first.py
    python tools/type_gate.py
    pytest --tb=short -q -n auto --dist loadfile

Tests need `SLACK_BOT_TOKEN=xoxb-test-not-a-real-token`, `SLACK_APP_TOKEN=xapp-test-not-a-real-token` and `PYTHONUTF8=1` in the environment, as `.github/workflows/tests.yml` sets.

The gate holds a PR that adds a new test which already passes on today's code. Where a ticket says checks share one test function, keep them together so the function fails on the base commit.

## Comments
