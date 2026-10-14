# 137: Replace BOM, from approval until processed

**Status:** ready-for-agent

**Runner:** any

**Auto-merge:** yes

**Blocked by:** 134, 136

**Spec:** `.scratch/bom-template-and-epif-date/spec.md` (Part E, stories 58, 60–63)
**Binding:** `docs/adr/0019-boms-come-in-through-the-lab-template-and-are-read.md`; `docs/adr/0010-linked-cards-and-direct-message-help.md`; `docs/adr/0001-tests-first-and-no-muted-failures.md`
**Glossary:** `CONTEXT.md` — **Replace BOM**, **Off-template BOM**, **BOM check**, **processed**

## What to build

A **Replace BOM** button on the thread card and on the DM card, while the request is `approved`
and has a BOM (`bom_file` on the card).

- **Who:** the requester (`req_data["user_id"]`), any buyer (`roster.is_buyer`) or an admin.
  Anyone else gets `slack_io.deny`.
- **Click:** opens a modal with the BOM file field (`block_bom`, `.xlsx`). Submitting it goes
  through ticket 134's reading view and check view with `origin = "replace"`. The total is
  checked against the card's EPIF amount.
- **On a clean submit,** `lifecycle.handle_replace_bom(...)` is the only implementation. It
  re-reads the card with `slack_io.get_card_by_ts`, re-checks the state is still `approved`
  and the role, then:
  1. rebuilds the BOM with `build_bom_workbook`;
  2. overwrites the archive at the card's existing `bom_file` name. If the old file was an
     Off-template `.csv`, it saves under the `.xlsx` name instead, and updates the workbook
     Notes column through the queue (`log_writer` via `queue_worker`, as other updates do);
  3. stores the new items in the card metadata and clears `off_template_bom`;
  4. re-renders both linked cards (as `handle_set_expected_delivery` does);
  5. uploads the BOM to the assigned buyer's DM through ticket 127's `_upload_to_dm` if it
     has landed, else the existing upload code;
  6. posts `BOM replaced by <name>` in the thread.
- **The button never appears from `processed` onward**, and Mark Processed is never gated on
  it.

## Acceptance criteria

- [ ] New file `tests/test_137_replace_bom.py`, `test_button_only_while_approved_with_a_bom`: an element with `action_id == "replace_bom"` exists on the thread card and DM card for an `approved` card with `bom_file`, and not for `processed`, nor for a card without `bom_file`.
- [ ] `test_replace_clears_the_off_template_flag`:
  - Starting from ticket 136's off-template approval, replace with the fixture as the requester (EPIF amount $858.50).
  - The archived BOM reads back to 4 items.
  - `off_template_bom` is gone from the card payload.
  - The DM card no longer contains `BOM not in the lab template`.
  - One upload of the BOM file name went to the buyer's DM.
- [ ] `test_replace_denied_for_others`: a user who is not the requester, not a buyer and not an admin gets `deny`; no `views_open`, no upload.
- [ ] `test_replace_refused_after_processed`: with the card moved to `processed` between opening and submitting, the handler changes no file and uploads nothing.

May fake: the Slack client, downloads, the thread starter, the queue's workbook. Must be real: the reader, builder, `log_writer.save_bom` into a temp dir, `slack_io.get_card_by_ts` on the fake's stored card, the real Bolt listener registry for the button.

## Gate

Run all four, in CI's order, and all must pass:

    ruff check .
    python scripts/check_tests_first.py
    python tools/type_gate.py
    pytest --tb=short -q -n auto --dist loadfile

Tests need `SLACK_BOT_TOKEN=xoxb-test-not-a-real-token`, `SLACK_APP_TOKEN=xapp-test-not-a-real-token` and `PYTHONUTF8=1` in the environment, as `.github/workflows/tests.yml` sets.

The gate holds a PR that adds a new test which already passes on today's code. Where a ticket says checks share one test function, keep them together so the function fails on the base commit.

## Comments
