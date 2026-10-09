# 117: Submitting the switch rewrites the row and sends the EPIF

**Status:** ready-for-agent

**Runner:** any

**Auto-merge:** yes

**Blocked by:** 115, 116

**Spec:** `.scratch/epif-path-and-buyer-dm/spec.md` (Part E, stories 17–19)
**Binding:** `docs/adr/0007-purchase-path-and-generated-epif.md` (decisions 5–7); `docs/adr/0018-the-path-is-the-payment-method-and-the-dm-card-shows-the-request.md`; `docs/adr/0016-one-rule-for-who-is-told.md` (refusals go through `slack_io.notify`); AGENTS.md invariant 2 (one writer, via the queue) and trap 12 (all-or-nothing writes)
**Glossary:** `CONTEXT.md` — **Workday path / EPIF path**, **Filled EPIF**

## What to build

Submitting ticket 116's form moves the request onto the EPIF path without a second
approval:

- the **same** workbook row is rewritten;
- the filled EPIF is archived in the same queued write;
- the thread card's payment method becomes P-card or Req/PO, so its path now reads `epif`;
- the thread gets `🔁 Switched to EPIF by {name}`;
- the assigned buyer gets the EPIF DM (draft, filled EPIF, DM card).

If the request was processed between the click and the write, nothing changes and the
person who submitted is told why.

1. `src/lifecycle.py` `_process_interview_completion`: after validation, when
   `meta.get("switch")` is set, `ack()` and hand off to a new
   `_finalize_switch_to_epif(client, switch, parsed, requester, user_id, stage2)`, then
   return. This is the same shape as the existing `bare_thread` hand-off to
   `_finalize_bare_thread_epif`. No new card is posted.
2. `_finalize_switch_to_epif` submits **one** `queue_worker.submit_write_task` whose
   action:
   1. Reads `log_writer.get_row_info(row)`. If its Date Processed value (column U) is set,
      it raises a refusal exception carrying "Already processed — the path can't change
      now." and writes nothing.
   2. Calls `log_writer.update_row(row, values)`, where `values` is
      `log_writer.build_row(new_parsed, requester)` **minus** columns
      `config.COLUMN_REQUESTER`, `config.COLUMN_DATE_OF_REQUEST`,
      `config.COLUMN_DATE_PROCESSED`, `config.COLUMN_DATE_CONFIRMED`,
      `config.COLUMN_DATE_DELIVERY`, `config.COLUMN_RECEIVED_BY` and
      `config.COLUMN_NOTES`. Before writing, it keeps the old values of exactly those
      columns from `get_row_info` so it can write them back.
   3. Fills and archives the EPIF exactly as `finalize_purchase_request`'s
      `write_action` does on the EPIF path: read `config.EPIF_TEMPLATE_PATH`, call
      `epif_filler.fill_epif`, then `log_writer.save_epif` under
      `log_writer.epif_archive_name(...)`. If that raises, it writes the old values back
      with `update_row` and re-raises.
   4. Returns `(row, saved_epif_path)`.
3. On success:
   - update the thread card with `chat_update`, including `metadata=`, as
     `finalize_purchase_request` does: payload `parsed` replaced by the new request with
     its date serialised, `epif_file` set, everything else kept;
   - post `🔁 Switched to EPIF by {resolved name}` in the thread and append the same line
     to History;
   - if the card has an assignee: retire the old DM card with
     `sync_dm_card(..., state="replaced", note="Switched to EPIF")`, then call
     `_send_assignee_dm(route="epif", epif_path=…, epif_fname=…, history=…, …)` with the
     email draft from `text_rules.generate_email_draft`, as `handle_assign` builds it.
4. On the refusal or any failure: post nothing in the thread except a failure line.
   For the refusal, DM the submitter through
   `slack_io.notify(client, actor_id=user_id, text=<the refusal>, channel=…, link_ts=…)`.
   The card is not updated.

## Acceptance criteria

- [ ] New `tests/test_117_switch_to_epif_submit.py`, on a temp workbook holding one approved Workday row:
  - submit the switch through `lifecycle._process_interview_completion` with a `switch` context and Screen 2 `payment_method="P-card"`;
  - assert that afterwards the row number and the row count are unchanged, the requester cell (column B) is unchanged, the payment-method cell (column L) reads P-card, and the vendor cell has the new vendor;
  - assert exactly one PDF is in the temp `EPIFS_DIR`, and `epif_parser.parse_epif` on it returns the vendor and amount.
- [ ] Same test function: the thread got a message containing `🔁 Switched to EPIF by`. The card's `chat_update` `metadata.event_payload.parsed.payment_method == "P-card"`, and `interview.get_request_route` on that payload is `epif`. The assigned buyer's DM contains `Send this email to purchasing`, and a `files_upload_v2` call names the PDF.
- [ ] Processed between click and write: set the row's Date Processed on the temp workbook **before** the queued task runs. Assert the row is byte-identical afterwards, `EPIFS_DIR` is empty, `chat_update` was not called, no `🔁` line was posted, and the submitter's DM contains `Already processed`.
- [ ] Template missing (`config.EPIF_TEMPLATE_PATH` pointing at a missing file): the row's cells equal their values before the switch, `EPIFS_DIR` is empty, and `chat_update` was not called.

May fake: the Slack client (`MagicMock`), the lock queue (synchronous, as the `sync_queue` fixture in `tests/test_45_epif_approval_archives.py`). Must be real: `log_writer` on a temp workbook copy (copy the `temp_workbook` fixture from `tests/test_45_epif_approval_archives.py`), `epif_filler.fill_epif` on `tests/fixtures/EPIF_TEMPLATE_HIRST.pdf`, `epif_parser.parse_epif`, `interview.build_parsed_from_stages`, `validators.validate`. A test that patches `update_row`, `fill_epif` or `get_request_route` does not count.

## Gate

Run all four, in CI's order, and all must pass:

    ruff check .
    python scripts/check_tests_first.py
    python tools/type_gate.py
    pytest --tb=short -q -n auto --dist loadfile

Tests need `SLACK_BOT_TOKEN=xoxb-test-not-a-real-token`, `SLACK_APP_TOKEN=xapp-test-not-a-real-token` and `PYTHONUTF8=1` in the environment, as `.github/workflows/tests.yml` sets.

## Comments
