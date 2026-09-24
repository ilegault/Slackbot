# 40: Finish bare-thread approval: the details form must actually log the order

**Status:** ready-for-agent

**Runner:** any

**Auto-merge:** yes

**Blocked by:** 38

Spec: Implementation Decision 4 (bare-thread approval, waiting for details, Fill in
details, Cancel). Binding: ADR 0007 decisions 4–5, ADRs 0003–0005.

**What to build:** Most of this is on `master` from PR #39, but the Fill in details
submit can never succeed in real Slack. Finish it. The flow: an approver approves a
thread holding only a screenshot and a link. The bot replies once, posts a card reading
"Approved — waiting for details", and writes nothing. The thread's starter presses
**Fill in details**, fills the form, and the row is written with them as requester. The
card becomes an ordinary approved card. The approver is never asked again.

- [ ] **Card metadata.** `lifecycle.handle_epif_processing` posts the waiting card with `metadata={"event_type": "purchase_request", "event_payload": {...}}`, the same shape the approval path uses in `finalize_purchase_request.on_success` (`client.chat_update(..., metadata=...)`). The payload carries `state`, `user_id` (the thread starter's Slack ID), `requester`, `approver`, `assignee_id`, `assignee` and `thread_ts`. Proof: the scenario test's fake `conversations_replies` returns the exact message the bot posted, and `slack_io.get_card_payload` (unpatched) reads `approver` and `state` back from it.
- [ ] **Submit uses the card, not the submitter.** `app.handle_workday_details_submit` takes `requester`, `approver` and `notify_target` from that card payload. It passes the card's `ts` as `event_ts`, not the literal `"1234567890.123456"`. Proof: a buyer (not the requester) submits the form, and the written row's requester column holds the thread starter's name.
- [ ] **Scenario, end to end**, fake client plus `temp_workbook` and `sync_queue`: bare approval (exactly one `say`, one card, workbook row count unchanged); then Fill in details submitted by the requester (one new row with that requester and `route = workday`, and the card `chat_update`d to `approved`). This test must not patch `slack_io.get_card_payload`, `lifecycle.finalize_purchase_request` or `validators.validate`.
- [ ] **Denial.** A user who is not the requester, the assignee, a buyer while unassigned, or an admin presses Fill in details: `respond` gets the denial, `views_open` is not called, and the row count is unchanged.
- [ ] **Cancel.** The `🚫 Purchase request cancelled.` line that PR #39 added to `lifecycle.handle_cancel` is posted only for `waiting_for_details` cards. A test cancels an ordinary approved card and asserts that line was not posted; a second test cancels a waiting card and asserts the line, the terminal card and an unchanged workbook.
- [ ] **Regression.** Approving a thread with an uploaded EPIF still logs it as before (no waiting card is posted). Add this to `tests/test_40_bare_thread_approval.py`.
- [ ] Full gate green, in CI order: `ruff check .`, `python scripts/check_tests_first.py`, `pytest -q`.

**Tests may fake:** the Slack client (a `MagicMock` that records calls) and the network. **Tests must use real:** the handlers, `log_writer`, and a temporary copy of the workbook (copy the `temp_workbook` and `sync_queue` fixtures from `tests/test_29_approval_archives_bom.py`). A test that patches out the function this ticket changes does not count.

## Comments

2026-09-24 — reopened on review of PR #39. The waiting card was posted without
`metadata=`, so `slack_io.get_card_payload` finds nothing and every Fill in details submit
answers "no longer waiting for details". The approver was never stored on the card, the
row took the submitter as requester, and the tests passed only because they patched out
the card lookup and the row writer. The criteria above name each fix.
