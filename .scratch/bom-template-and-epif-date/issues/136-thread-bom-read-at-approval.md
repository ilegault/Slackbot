# 136: A thread's .xlsx is read at approval; an Off-template BOM is flagged, never blocking

**Status:** in-progress

**Runner:** any

**Auto-merge:** yes

**Blocked by:** 132

**Spec:** `.scratch/bom-template-and-epif-date/spec.md` (Part E, stories 56–59, 62)
**Binding:** `docs/adr/0019-boms-come-in-through-the-lab-template-and-are-read.md`; `docs/adr/0015-approval-reads-the-card-or-the-threads-files-by-role.md`; `docs/adr/0001-tests-first-and-no-muted-failures.md`
**Glossary:** `CONTEXT.md` — **Thread files at approval**, **Off-template BOM**, **DM card**

## What to build

At `@Purchasing approved` in a thread with no posted card, the BOM file the thread classifier
picks (`slack_io.classify_thread_files`, role `bom`, today `.xlsx` or `.csv`) is handled in one
of two ways.

- **It reads cleanly and matches the EPIF amount.** `bom.read_bom_template` finds no problems
  and `bom.check_bom_total` matches the EPIF's amount. Its rows become the request's line items,
  and the bot rebuilds and archives the BOM as on the form path (ticket 132).
- **Anything else is an Off-template BOM** (a CSV, not the template, row problems, or a total
  mismatch).
  1. Approval proceeds unchanged.
  2. The file is archived as given under `bom.bom_filename(...)` with its own extension.
  3. `off_template_bom: true` and the problem text are stored on the card payload.
  4. The bot posts in the thread:
     `⚠️ <@requester> — this BOM isn't ready for purchasing: <first problem>. Use **Replace BOM** on the card to upload the lab template version before it's processed.`
  5. While the flag is set, `blocks.build_dm_card_blocks` and `blocks.request_summary_lines`
     show the line `⚠️ BOM not in the lab template — requester asked to update`.

The workbook row, the EPIF and the buyer's DM are written exactly as today. **Never** refuse or
delay the approval because of the BOM.

The reading happens in the same place `handle_epif_processing` / `finalize_purchase_request`
picks up the thread's BOM today. Reuse that download.

## Acceptance criteria

- [ ] New file `tests/test_136_thread_bom.py`, `test_clean_template_in_thread_is_read`:
  - Approve a thread holding a Filled-EPIF PDF at $858.50 plus the fixture `.xlsx`, as `tests/test_103_thread_files_at_approval.py` sets up a thread.
  - The card metadata holds 4 items.
  - The archived BOM in the temp `BOMS_DIR` reads back with `read_bom_template` to those items.
  - No thread message contains `isn't ready for purchasing`.
- [ ] `test_off_template_bom_still_approves_and_asks_for_a_replacement`:
  - The same thread with a CSV instead of the xlsx: the workbook row is written (queue task captured), and the archived file keeps `.csv`.
  - A thread message mentions the requester and contains `Replace BOM`.
  - The DM card blocks contain `BOM not in the lab template`.
  - All in this one function.
- [ ] `test_total_mismatch_is_off_template`: the fixture with an EPIF of $900.00 approves and posts the replace message naming `$858.50` and `$900.00`.

May fake: the Slack client, file downloads (return fixture bytes), the queue's workbook write. Must be real: the thread classifier, `read_bom_template`, `check_bom_total`, `build_bom_workbook`, `log_writer.save_bom` into a temp dir.

## Gate

Run all four, in CI's order, and all must pass:

    ruff check .
    python scripts/check_tests_first.py
    python tools/type_gate.py
    pytest --tb=short -q -n auto --dist loadfile

Tests need `SLACK_BOT_TOKEN=xoxb-test-not-a-real-token`, `SLACK_APP_TOKEN=xapp-test-not-a-real-token` and `PYTHONUTF8=1` in the environment, as `.github/workflows/tests.yml` sets.

The gate holds a PR that adds a new test which already passes on today's code. Where a ticket says checks share one test function, keep them together so the function fails on the base commit.

## Comments
