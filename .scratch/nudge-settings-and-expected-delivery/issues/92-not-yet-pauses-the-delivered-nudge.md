# 92: "Not yet" on the nudge card; delivered nudges pause until the expected date

**Status:** in-progress

**Runner:** any

**Auto-merge:** yes

**Blocked by:** 90, 91

**Spec:** `.scratch/nudge-settings-and-expected-delivery/spec.md`
**Binding:** `docs/adr/0013-nudge-settings-per-stage-and-expected-delivery.md` decisions 4–5; ADR 0001

## What to build

The delivered nudge card gets a second button, **Not yet — set expected date**, which opens the
form from ticket 91. Once an expected date is set (from here or from the Confirmed card), the
delivered nudge stays quiet until that date, nudges on that date (or the next weekday at 9:00 if
it falls on a weekend), then every N working days again. A six-week order isn't nagged every two
weeks.

1. `src/config.py`: `ACTION_NUDGE_NOT_YET = "nudge_not_yet"`.
2. `src/blocks.py` `build_nudge_card_blocks` state `active`: add a second button
   `Not yet — set expected date`, `action_id` `config.ACTION_NUDGE_NOT_YET`, same pointer value.
   When an expected date is passed in (new optional parameter `expected: str | None`), the section
   reads `⏰ <mentions> — *<item>* was expected <Mon D>. Has this been delivered?`
3. `src/app.py`: register the ticket-91 opener for `config.ACTION_NUDGE_NOT_YET` too (same
   permission check, same view).
4. `src/nudge.py`: new pure
   `delivered_due(today: date, confirmed: date, expected: date | None, every: int) -> bool`:
   - no `expected` → `is_due(working_days_between(confirmed, today), every)`;
   - with `expected`: `first` = `expected`, moved forward to Monday if it is a Saturday or Sunday;
     `today < first` → `False`; `today == first` → `True`; else
     `is_due(working_days_between(first, today), every)`.
   `run_nudges` delivered branch uses it, with `expected` from the entry's `expected_delivery`
   (falling back to the card payload's).

## Acceptance criteria

New test file `tests/test_92_not_yet_and_pause.py`. Confirmed 2026-10-05 (serial `"46300"`),
`every` 10.

- [ ] **`delivered_due` table.** No expected: 2026-10-19 true, 2026-10-16 false. Expected 2026-11-16 (Mon): 2026-10-19 false, 2026-11-13 false, 2026-11-16 true, 2026-11-17 false, 2026-11-30 (10 working days later) true. Expected 2026-11-14 (Sat): 2026-11-16 true, 2026-11-14 false.
- [ ] **The button.** `build_nudge_card_blocks("active", ...)` has buttons `nudge_delivered` and `nudge_not_yet`; pressing `nudge_not_yet` as the requester → `views_open` with `callback_id == "expected_delivery_submit"`.
- [ ] **The run pauses and resumes.** With the entry's `expected_delivery = "2026-11-16"`: `run_nudges` on 2026-10-19 → no post; on 2026-11-16 → one nudge card whose text contains `was expected Nov 16`.
- [ ] **Pushing it back pauses again.** After a 2026-11-16 nudge, setting `expected_delivery = "2026-12-07"` → `run_nudges` on 2026-11-30 → no post.

**Tests may fake:** the Slack client, `log_writer.get_row_info`. **Must be real:** `nudge.delivered_due`, `run_nudges`, `store` and `nudge_settings` on temp files, `blocks.build_nudge_card_blocks`.

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
