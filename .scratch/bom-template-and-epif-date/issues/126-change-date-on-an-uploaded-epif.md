# 126: Change date works on a hand-filled (uploaded) EPIF

**Status:** done

**Runner:** any

**Auto-merge:** yes

**Blocked by:** 125

**Spec:** `.scratch/bom-template-and-epif-date/spec.md` (Part B, story 19)
**Binding:** `docs/adr/0001-tests-first-and-no-muted-failures.md`
**Glossary:** `CONTEXT.md` — **EPIF date**, **EPIF**

## What to build

A request approved from a hand-filled EPIF has no Filled EPIF to re-fill. **Change date** on such
a request rewrites only the uploaded PDF's `Date of Purchase` field. Every other field, and the
signature field, is left exactly as the requester wrote it.

1. **`src/epif_filler.py`** — add the pure function `redate_epif(pdf_bytes: bytes, new_date: datetime.date) -> bytes`.
   - It sets only the `Date of Purchase` field (`%m/%d/%Y`) on every page, sets
     `NeedAppearances`, and returns the bytes.
   - It reuses `fill_epif`'s XMP-metadata removal so `clone_from` works.
   - Add a docstring sentence on why it exists.
2. **`lifecycle.handle_change_epif_date`** (from 125) — when the request was not filled by the
   bot (`source == "epif"` with an uploaded file, as `finalize_purchase_request` distinguishes
   them), read the archived file, `redate_epif` it, and save under the same name. The rest of
   the handler is unchanged.

## Acceptance criteria

- [x] `test_redate_epif_changes_only_the_date`:
  - Fill the fixture template with `fill_epif` (every text field set, Fabrication ticked, P-card), then `redate_epif` it to 2026-11-02.
  - `parse_epif` of the result equals `parse_epif` of the input on every key except `date_of_purchase`, which is 2026-11-02.
- [x] `test_change_date_on_uploaded_epif`:
  - Approve a request from an uploaded EPIF dated 09/01/2026 (as `tests/test_45_epif_approval_archives.py`), then call `handle_change_epif_date` with 2026-11-02.
  - The archived file parses to 2026-11-02 and its purpose and total are unchanged.
  - Both checks are in this one function.

May fake: the Slack client. Must be real: `fill_epif`, `redate_epif`, `parse_epif` on the committed fixture; the archive in a temp directory.

## Gate

Run all four, in CI's order, and all must pass:

    ruff check .
    python scripts/check_tests_first.py
    python tools/type_gate.py
    pytest --tb=short -q -n auto --dist loadfile

Tests need `SLACK_BOT_TOKEN=xoxb-test-not-a-real-token`, `SLACK_APP_TOKEN=xapp-test-not-a-real-token` and `PYTHONUTF8=1` in the environment, as `.github/workflows/tests.yml` sets.

The gate holds a PR that adds a new test which already passes on today's code. Where a ticket says checks share one test function, keep them together so the function fails on the base commit.

## Comments

2026-10-15: Done. `epif_filler.redate_epif` rewrites only `Date of Purchase` (shares the XMP-removal and NeedAppearances helpers with `fill_epif`). `lifecycle.handle_change_epif_date` re-dates the archived file in place when the request came from an uploaded EPIF (`source == "epif"`), else re-fills as before. Tests: `tests/test_126_change_date_uploaded_epif.py` (both named tests; the second hand-edits a field the filler never writes, so a rebuild from the template would fail it).
