# 88: Confirmed nudge

**Status:** in-progress

**Runner:** any

**Auto-merge:** yes

**Blocked by:** 87

**Spec:** `.scratch/nudge-settings-and-expected-delivery/spec.md`
**Binding:** `docs/adr/0013-nudge-settings-per-stage-and-expected-delivery.md` decisions 1, 2, 4; ADR 0001

## What to build

A processed request that hasn't been confirmed gets the **confirmed** nudge: every N working days
after Date Processed (default every 5, DM). The DM re-posts the buyer's DM card with Mark
Confirmed, the same way the processed nudge re-posts it with Mark Processed.

1. `src/nudge.py`: new pure `parse_sheet_date(value) -> date | None`. The bot writes workbook dates
   as Excel serial numbers (`log_writer._to_serial`), and `log_writer.get_row_info` returns raw
   cell text, so accept: an int/float or numeric string as an Excel serial (day 0 = 1899-12-30);
   `YYYY-MM-DD` (optionally with a time part); `M/D/YYYY`; `M/D/YY`. Anything else (including
   empty) → `None`.
2. `src/nudge.py`: pull the DM-card re-post out of the assigned-processed path into
   `_repost_dm_card(client, entry, req_data, history, card_state, section_text)`. It retires the
   old DM card (`lifecycle.sync_dm_card(..., state="replaced", ...)`), posts
   `section_text` + `blocks.build_dm_card_blocks(card_state, ...)`, updates the thread card's DM
   pointers with `blocks.build_request_blocks(card_state, ...)`, and returns the new `(dm_channel, dm_ts)`.
   The processed nudge calls it with `"approved"` and its existing text.
3. `src/nudge.py` `run_nudges`: read the first row's `get_row_info`. Date Processed parsed, Date
   Confirmed and Date Delivered empty, `confirmed.enabled` true, entry has `buyer_id`, thread card
   state `processed`, and `is_due(working_days_between(date_processed, today), confirmed.every)` →
   - `dm`: `_repost_dm_card(..., "processed", "⏰ <item> was processed <n> working days ago and isn't marked Confirmed yet.")`;
   - `channel`: thread reply with `reply_broadcast=True`:
     `⏰ <@buyer> — this request was processed <n> working days ago and isn't marked Confirmed yet.`;
   - then `store.update(id, last_nudged=..., dm_channel=..., dm_ts=...)` as today.
   A Date Processed present but unparseable → skip the entry with a warning. The processed nudge
   still skips any entry with a Date Processed.

## Acceptance criteria

New test file `tests/test_88_confirmed_nudge.py`; temp log and settings; `get_row_info`
monkeypatched to return Date Processed as the serial string for Monday 2026-10-05 (`"46300"`)
and empty Date Confirmed; the fake thread card is in state `processed`.

- [ ] **`parse_sheet_date`.** `"46300"` → 2026-10-05; `46300` → 2026-10-05; `"2026-10-05"` → 2026-10-05; `"10/5/2026"` and `"10/5/26"` → 2026-10-05; `""`, `None`, `"soon"` → `None`.
- [ ] **Day 5 DM, day 4 nothing.** 2026-10-09 (day 4) → no post. 2026-10-12 (day 5) → one DM to the buyer whose blocks contain `processed 5 working days ago` and a `Mark Confirmed` button; the old DM card is updated to `Replaced by the reminder below`; no `reply_broadcast`.
- [ ] **Channel option.** Settings `confirmed.channel` true, `dm` false → day 5: one post with `reply_broadcast=True` containing `<@buyer>` and `isn't marked Confirmed yet`, no DM.
- [ ] **Stops.** A Date Confirmed present → nothing; `confirmed.enabled` false → nothing; Date Processed `"soon"` → nothing and no exception; the processed nudge never fires for this entry.
- [ ] **No regressions.** `tests/test_78_nudge_assigned.py` and `tests/test_87_nudge_settings.py` pass unchanged after the `_repost_dm_card` extraction.

**Tests may fake:** the Slack client, `log_writer.get_row_info`. **Must be real:** `nudge`, `nudge_settings` and `store` on temp files, `blocks`, `lifecycle.sync_dm_card`.

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
