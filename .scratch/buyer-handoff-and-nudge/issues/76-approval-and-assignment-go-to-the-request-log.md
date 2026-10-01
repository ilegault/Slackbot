# 76: Approval and assignment are written to the request log

**Status:** in-progress

**Runner:** any

**Auto-merge:** yes

**Blocked by:** None (can start immediately)

**Spec:** `.scratch/buyer-handoff-and-nudge/spec.md` ("The request log")
**Binding:** `docs/adr/0011-buyers-hand-off-requests-and-the-request-log.md` decision 3, `docs/adr/0010-linked-cards-and-direct-message-help.md` decision 2 (the thread card stays the store), ADR 0001

## What to build

Every approval creates one entry in the request log, `requests.json` (`store.STORE_PATH`,
already gitignored), and every assign or reassign updates it. The log sits beside the cards:
nothing reads cards from it, and it never holds a stage. A log failure never stops a purchase.

1. `lifecycle`: add one private helper, `_request_log(client, fn, *args, **kwargs)`, that calls a
   `store` function inside `try/except`; on any exception it logs at ERROR and calls
   `slack_io.alert_admins(client, "⚠️ Couldn't write the request log (requests.json): <error>")`,
   and returns `None`. Every write below goes through it.
2. `lifecycle.finalize_purchase_request` → `on_success`, after the card is posted or updated
   (`actual_card_ts` is known): `store.create(...)` with `channel`, `thread_ts`,
   `card_ts=actual_card_ts`, `requester`, `requester_id=notify_target`,
   `buyer=assignee_name`, `buyer_id=assignee_id`, `rows=[row]`, `history=` the card's history
   lines just built, plus extra fields `approved_at` (ISO date-time now),
   `buyer_set_at` (the same ISO value when a buyer was named, else `None`),
   `cancelled=False`, `last_nudged=None`. If `store.get_by_thread(channel, thread_ts)` already
   returns an entry, update that one instead of creating a second.
3. `lifecycle.handle_assign`, after a successful assignment in any state except `posted`:
   find the entry with `store.get_by_thread(channel, thread_ts)`; `store.update` its
   `buyer`, `buyer_id`, and `buyer_set_at` (ISO now), and `store.append_history` the same
   `Assigned to …` / `Reassigned to …` line the card got. No entry (a request approved before
   this shipped) → do nothing, no alert.
4. `store.get_by_thread` returns the request dict without its ID; add `find_id_by_thread(channel,
   thread_ts) -> str | None` beside it, used by steps 2–3 to call `update` / `append_history`.
5. Update `store`'s module docstring: it is **the request log** (glossary term), holds no stage,
   and cards are not drawn from it.

## Acceptance criteria

New test file `tests/test_76_request_log_approval_and_assign.py`. `monkeypatch.setattr(store,
"STORE_PATH", str(tmp_path / "requests.json"))`; approval fixtures and fake client as
`tests/test_64_approval_posts_card.py`; roster and `sync_queue` as `tests/test_69_cards_move_together.py`.

- [ ] **Approval creates one entry.** An approval naming buyer A: reading the temp `requests.json`
  gives exactly one entry whose `thread_ts`, `channel` and `card_ts` equal the thread and the
  posted card's ts, `buyer_id == "U_A"`, `rows == [<row written>]`, `approved_at` and
  `buyer_set_at` both non-null, and a history line starting `Approved by`. The file has no key
  named `state` or `stage` in the entry.
- [ ] **Unassigned approval.** Approval with no buyer named: entry has `buyer_id is None` and
  `buyer_set_at is None`.
- [ ] **Reassignment updates the entry.** After the approval above, `lifecycle.handle_assign`
  moves it to buyer B: still one entry, `buyer_id == "U_B"`, `buyer_set_at` later than or equal
  to `approved_at`, last history line starts `Reassigned to`.
- [ ] **A log failure never blocks and alerts.** With `store.create` monkeypatched to raise, the
  approval still writes the workbook row and posts the card, and exactly one message goes to the
  admin alert channel containing `request log`.
- [ ] **No entry, no noise.** `handle_assign` on a thread with no log entry: the assignment
  happens, the log file is unchanged, and nothing is posted to the admin alert channel.

**Tests may fake:** the Slack client, `log_writer` I/O as `test_64` does. **Must be real:** `store`
writing the temp `requests.json`, `finalize_purchase_request`, `handle_assign`, the roster on a temp file.

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
