# 93: Posted cards enter the request log

**Status:** ready-for-agent

**Runner:** any

**Auto-merge:** yes

**Blocked by:** None (can start immediately)

**Spec:** `.scratch/nudge-settings-and-expected-delivery/spec.md`
**Binding:** `docs/adr/0013-nudge-settings-per-stage-and-expected-delivery.md` decision 7; `docs/adr/0011-buyers-hand-off-requests-and-the-request-log.md` decision 3 (amended); ADR 0001

## What to build

So the approved nudge (ticket 94) can find requests nobody has approved yet, a card's request-log
entry is created when the card is **posted**, not at approval. Approval then updates that same
entry, so each request keeps one history. Declined and superseded cards are flagged in the log.
One thread can hold several posted cards (a batch), so entries are matched by card, not by thread.

1. `src/store.py`: new `find_id_by_card(channel: str, card_ts: str) -> Optional[str]`, like
   `find_id_by_thread` but matching `card_ts`.
2. `src/lifecycle.py` `_process_interview_completion` (after the card is posted; thread =
   `card_ts`) and `handle_epif_drop` (after its card is posted; thread = the thread): create the
   entry with `_request_log(client, store.create, channel=..., thread_ts=..., card_ts=..., requester=..., requester_id=<poster's Slack ID>, posted_at=<now ISO>, history=["Posted by <requester> on <now>"])`.
   A log failure alerts and never blocks posting (that is what `_request_log` already does).
3. `src/lifecycle.py` `finalize_purchase_request` (the block that calls `store.find_id_by_thread`
   today): look up `store.find_id_by_card(channel, actual_card_ts)` first; only when that finds
   nothing, use the thread lookup **and only if** that entry has no `posted_at` (so approving one
   card in a batch never overwrites another card's entry). Then update or create exactly as
   today.
4. `src/lifecycle.py` `handle_decline`: after the card update, `store.update(<id by card msg_ts>, declined=True)`
   and append a history line, through `_request_log`. In `handle_epif_drop`, where a stale card
   is rebuilt as `superseded`, set `superseded=True` on that card's entry the same way.
5. `src/nudge.py` `run_nudges`: skip any entry that has no `approved_at` before the processed /
   confirmed / delivered logic (today's code already skips them by accident; make it explicit).

Requests posted before this ships have no entry until approval, as today.

## Acceptance criteria

New test file `tests/test_93_posted_cards_logged.py`; temp `requests.json`; fake client; prior art
`tests/test_76_request_log_approval_and_assign.py`.

- [ ] **Posting creates the entry.** Completing `/new-purchase` → exactly one entry with `card_ts` = the posted card's ts, `requester_id` = the submitter, a `posted_at`, no `approved_at`. Dropping an EPIF that posts a card → one entry with that card's ts and the dropper's ID.
- [ ] **Approval updates it.** Approving that card → still exactly one entry for that `card_ts`, now with `approved_at`, `rows`, and its history containing the `Posted by` line and the approval lines.
- [ ] **Batch-safe.** A thread with two posted cards (two entries) → approving the second card updates only the second entry; the first keeps no `approved_at`.
- [ ] **Decline and supersede flag the entry.** Declining a posted card → its entry has `declined == True`. Dropping a corrected EPIF that supersedes a card → the old card's entry has `superseded == True`, and the new card has its own entry.
- [ ] **The nudge ignores posted entries.** A posted entry with `posted_at` three working days ago → `nudge.run_nudges` sends nothing for it; a `store.create` that raises during posting → the card is still posted and `slack_io.alert_admins` is called.

**Tests may fake:** the Slack client, the lock queue. **Must be real:** `store` on the temp file, `_process_interview_completion`, `handle_epif_drop`, `finalize_purchase_request`, `handle_decline`.

## Gate

Run in this order, exactly as CI does (`.github/workflows/tests.yml`). Zero failures before
you push.

```
ruff check .
python scripts/check_tests_first.py
python tools/type_gate.py
pytest --tb=short -q -n auto --dist loadfile
```

## Comments
