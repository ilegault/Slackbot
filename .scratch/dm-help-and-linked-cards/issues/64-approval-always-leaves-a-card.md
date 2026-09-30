# 64: Approval always leaves a card in the thread

**Status:** done

**Runner:** any

**Auto-merge:** yes

**Blocked by:** 57

**Spec:** `.scratch/dm-help-and-linked-cards/spec.md` (item 4)
**Binding:** `docs/adr/0010-linked-cards-and-direct-message-help.md` decision 1, `docs/adr/0002-request-lifecycle-and-surfaces.md` decision 3, invariants 1 and 3 in `AGENTS.md` §2, ADR 0001

## What to build

In production an approver approved a thread and the bot wrote the workbook row and DM'd
the buyer, but **no card existed in the thread**, so there was no Mark Processed button.
`lifecycle.finalize_purchase_request` (its `on_success`, the block headed
`# Update or post card in thread`) updates a card `if target_card_ts:` and does nothing
otherwise. Make the else case post one.

Build the request payload and history once, before the `if`. When there is no card:

- `req_payload` is the shape `lifecycle.handle_epif_drop` builds (`"parsed"` with
  `date_of_purchase` as an ISO string or `None`, `"requester"`, `"user_id"` = the notify
  target, `"is_pending_name"`, `"thread_ts"`), plus `"source": "epif"` when `pdf_bytes` was
  supplied. Add `items` and `shipping` when `items` is non-empty, as
  `lifecycle._process_interview_completion` does. Then `state`, `assignee_id`, `assignee`,
  `epif_file` and `bom_file` exactly as the update path sets them.
- The History lines are the same ones the update path appends (`Approved by …`, and
  `Assigned to …` when there is an assignee).
- Post with `client.chat_postMessage(channel=channel, thread_ts=thread_ts, text="🛒 Purchase Request (Approved)", blocks=blocks.build_request_blocks("approved", req_payload, history=hist, items=items), metadata={"event_type": "purchase_request", "event_payload": req_payload})`.
- If that post raises, log the error at ERROR and carry on: the approval, row and DMs
  stand (ticket 65 adds the admin alert).

The update-in-place path is unchanged and must not also post.

## Acceptance criteria

- [x] **No card in the thread → one is posted.** In `tests/test_64_approval_posts_card.py`
  (copy the `clean_roster`, `temp_epifs_dir`, `temp_boms_dir` and `sync_queue` fixtures and
  the fake-client style from `tests/test_46_epif_path_dm_attaches_epif.py`), run
  `lifecycle.finalize_purchase_request` with a client whose `conversations_replies` returns
  only a plain human message. Exactly one `chat_postMessage` call carries
  `metadata["event_type"] == "purchase_request"` and `thread_ts` equal to the thread; its
  `metadata["event_payload"]["state"] == "approved"`; its blocks hold exactly one primary
  button with text `Mark Processed` and `action_id` `req_processed`, plus a `Cancel` button;
  the row-append recorder was called once.
- [x] **History and buyer are on the card.** With an assignee, the card's section text
  contains `Buyer:` and the assignee's name, its context block contains `Approved by` and
  `Assigned to`, and the payload holds `assignee_id`.
- [x] **The posted card is readable by the next handler.** Feed the kwargs of that
  `chat_postMessage` back as the only message in a fake `conversations_replies` and assert
  `slack_io.find_card_in_thread` returns state `approved` with the same `assignee_id`.
- [x] **A thread that already has a card is updated, not duplicated.** With a card present
  in the fake replies: one `chat_update` whose `ts` is the card's, and **no**
  `chat_postMessage` call carrying `metadata` (absence asserted).
- [x] **A failing card post does not undo the approval.** `chat_postMessage` raising for the
  card only: the row-append recorder was still called once, the assignee's DM was still
  sent, an ERROR record is in `caplog`, and no exception escapes.

**Tests may fake:** the Slack client, `log_writer` I/O as ticket 46's fixtures do. **Must
be real:** `finalize_purchase_request`, `blocks.build_request_blocks`, `slack_io.find_card_in_thread`.
Existing tests that count `chat_postMessage` calls in an approval with no card: rewrite the
assertion in place (same test name) to allow the one new card post — do not delete or weaken
what they check.

## Gate

Run in this order, exactly as CI does (`.github/workflows/tests.yml`). Zero failures before
you push. If `tools/type_gate.py` exists on `master` when you start, also run
`python tools/type_gate.py` after `check_tests_first.py`, and use
`pytest --tb=short -q -n auto --dist loadfile` in place of the last line.

```
ruff check .
python scripts/check_tests_first.py
pytest -q --tb=short --durations=25
```

## Comments

Summary (2026-09-30):
- Updated `lifecycle.finalize_purchase_request` (`on_success`) to build history, request payload, and card blocks cleanly once, and post an approved card via `chat_postMessage` if no existing card is present in the thread.
- If `chat_postMessage` raises when posting the fallback card, the error is logged at ERROR level and the approval, row append, and assignee DM stand.
- Thread with existing card continues to update in place via `chat_update` without posting a duplicate card.
- Added comprehensive unit tests in `tests/test_64_approval_posts_card.py` covering all 5 acceptance criteria.


