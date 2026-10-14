# 125: Change date on the buyer's DM card (Filled EPIF)

**Status:** ready-for-agent

**Runner:** any

**Auto-merge:** yes

**Blocked by:** 124

**Spec:** `.scratch/bom-template-and-epif-date/spec.md` (Part B, stories 10–17, 20)
**Binding:** `docs/adr/0001-tests-first-and-no-muted-failures.md`; `docs/adr/0010-linked-cards-and-direct-message-help.md` (linked cards)
**Glossary:** `CONTEXT.md` — **EPIF date**, **Filled EPIF**, **DM card**, **processed**

## What to build

On the EPIF path, while the request is `approved` (before **processed**), the assigned buyer's DM
card shows a **Change date** button. It opens a date picker defaulting to today. On submit, the
bot does four things:

- re-fills the Filled EPIF with the new **EPIF date**, overwriting the archived file under the
  same name;
- uploads the new copy to the buyer's DM;
- stores `epif_date` on the card;
- posts the thread history line `EPIF date changed to MM/DD/YYYY by <buyer name>`.

The workbook is never written; column M is the **Request date**.

Copy the expected-delivery feature, which already has exactly this shape:

- the button `blocks._expected_delivery_button`;
- the modal `blocks.build_expected_delivery_view`;
- the listeners `app.handle_set_expected_delivery_action` and
  `app.handle_expected_delivery_submission`;
- the handler `lifecycle.handle_set_expected_delivery`.

It re-reads the card, updates both linked cards and appends history.

1. **`config`**: `ACTION_CHANGE_EPIF_DATE = "change_epif_date"`,
   `CHANGE_EPIF_DATE_CALLBACK_ID = "change_epif_date_submit"`.
2. **`blocks.build_dm_card_blocks`**: in state `approved` and route `epif`, add the button
   (label `Change date`) beside Mark Processed. Its value is the same pointer JSON. Add the
   view builder `build_change_epif_date_view(thread_channel, thread_ts, card_ts, initial)`.
3. **`app`**: the action listener acks, re-reads the card with `slack_io.get_card_by_ts`, and
   opens the modal. It denies with `slack_io.deny` and opens nothing when either:
   - the clicker is not `req_data["assignee_id"]`; or
   - the state is not `approved`.

   The view listener acks and delegates.
4. **`lifecycle.handle_change_epif_date(client, channel, thread_ts, card_ts, user_id, chosen_date)`**
   — the only implementation. It re-reads the card and re-checks the assignee and state (a
   stale form must not act).
   - Read the template as `finalize_purchase_request` does, `fill_epif` with
     `epif_date=chosen_date`, and `log_writer.save_epif` under the card's `epif_file` name,
     overwriting.
   - Upload the file to the buyer's DM: `req_data["dm_channel"]`, through the same upload code
     `_send_assignee_dm` uses.
   - Update both cards and append the history line.
   - Log the success line with the path.

## Acceptance criteria

- [ ] `test_change_date_button_only_for_epif_path_before_processed` builds `blocks.build_dm_card_blocks` and asserts an element with `action_id == "change_epif_date"` is present for (`approved`, `epif`), and absent for (`approved`, `workday`) and (`processed`, `epif`).
- [ ] `test_change_date_refills_and_resends`:
  - Approve an EPIF-path request as `tests/test_45_epif_approval_archives.py` does, with a temp `EPIFS_DIR`.
  - Call `lifecycle.handle_change_epif_date` as the assignee with 2026-10-20.
  - `parse_epif` of the file at the same archived path gives `date_of_purchase == 2026-10-20`.
  - The fake client records one upload of that file name to the DM channel.
  - A thread message contains `EPIF date changed to 10/20/2026`.
  - The fake workbook writer received no task.
- [ ] `test_change_date_denied_for_non_assignee`:
  - The action listener, clicked by a different buyer, calls `deny` and never `views_open`.
  - `handle_change_epif_date` called by a non-assignee leaves the archived file's bytes unchanged and uploads nothing.
- [ ] `test_change_date_refused_after_processed`: with the card in `processed`, the handler changes nothing and uploads nothing.

May fake: the Slack client (record `files_upload_v2`, `chat_update`, `chat_postMessage`, `views_open`), the lock queue. Must be real: `fill_epif`, `parse_epif`, `log_writer.save_epif` into a temp directory, and the card round trip through `slack_io.get_card_by_ts` on the fake's stored message.

## Gate

Run all four, in CI's order, and all must pass:

    ruff check .
    python scripts/check_tests_first.py
    python tools/type_gate.py
    pytest --tb=short -q -n auto --dist loadfile

Tests need `SLACK_BOT_TOKEN=xoxb-test-not-a-real-token`, `SLACK_APP_TOKEN=xapp-test-not-a-real-token` and `PYTHONUTF8=1` in the environment, as `.github/workflows/tests.yml` sets.

The gate holds a PR that adds a new test which already passes on today's code. Where a ticket says checks share one test function, keep them together so the function fails on the base commit.

## Comments
