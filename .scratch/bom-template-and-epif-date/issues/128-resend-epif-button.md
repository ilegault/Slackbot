# 128: Resend EPIF button on the buyer's DM card

**Status:** ready-for-agent

**Runner:** any

**Auto-merge:** yes

**Blocked by:** 127

**Spec:** `.scratch/bom-template-and-epif-date/spec.md` (Part C, stories 23–25)
**Binding:** `docs/adr/0001-tests-first-and-no-muted-failures.md`; `docs/adr/0010-linked-cards-and-direct-message-help.md`
**Glossary:** `CONTEXT.md` — **DM card**, **EPIF path**

## What to build

On the EPIF path, the buyer's DM card shows a **Resend EPIF** button in every state before
`delivered`. Clicking it re-uploads every file the DM is meant to carry for this request, all read
from the archive:

- the EPIF (`epif_file` in `EPIFS_DIR`);
- the BOM (`bom_file` in `BOMS_DIR`);
- the quotes (`quote_count` quotes, named by `bom.quote_filename` in `QUOTES_DIR`).

The uploads go through ticket 127's `_upload_to_dm`. It is allowed for the assigned buyer or an
admin (`roster.is_admin`). Anyone else is denied with `slack_io.deny`.

1. **`config`**: `ACTION_RESEND_EPIF = "resend_epif"`.
2. **`blocks.build_dm_card_blocks`** — add the button (label `Resend EPIF`, pointer value) for
   route `epif` in states `approved`, `processed`, `confirmed`.
3. **`app`** — an action listener: ack, extract the pointer, delegate.
4. **`lifecycle.handle_resend_epif(client, channel, thread_ts, card_ts, user_id, respond)`** —
   re-read the card with `slack_io.get_card_by_ts`, check the role, collect the paths that
   exist, upload each, then `respond` with `Sent again: <file names>`. A missing archive file
   is named in that reply as `not found: <name>` and does not stop the others.

## Acceptance criteria

- [ ] `test_resend_epif_button_on_epif_path_only`: present for `epif` in `approved`/`processed`/`confirmed`, absent for `workday` and for `delivered`.
- [ ] `test_resend_epif_uploads_the_archived_files`:
  - With an archived EPIF, BOM and one quote in temp dirs, the assignee's click uploads exactly those three file names to `req_data["dm_channel"]`.
  - `respond` gets text starting `Sent again:`.
- [ ] `test_resend_epif_denied_for_others`: a non-assignee non-admin gets `deny`, and the fake records zero uploads.
- [ ] `test_resend_epif_names_a_missing_file`: with the BOM file deleted, the EPIF still uploads and the reply contains `not found:` and the BOM's name.

May fake: the Slack client, `respond`. Must be real: the archive files in temp directories, `slack_io.get_card_by_ts` on the fake's stored card, and the upload helper from 127.

## Gate

Run all four, in CI's order, and all must pass:

    ruff check .
    python scripts/check_tests_first.py
    python tools/type_gate.py
    pytest --tb=short -q -n auto --dist loadfile

Tests need `SLACK_BOT_TOKEN=xoxb-test-not-a-real-token`, `SLACK_APP_TOKEN=xapp-test-not-a-real-token` and `PYTHONUTF8=1` in the environment, as `.github/workflows/tests.yml` sets.

The gate holds a PR that adds a new test which already passes on today's code. Where a ticket says checks share one test function, keep them together so the function fails on the base commit.

## Comments
