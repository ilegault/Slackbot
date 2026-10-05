# 87: Nudge settings file drives the processed nudge

**Status:** ready-for-agent

**Runner:** any

**Auto-merge:** yes

**Blocked by:** None (can start immediately)

**Deletes tests:** tests/test_78_nudge_assigned.py::test_day_6_broadcast_day_9_dm_only, tests/test_79_nudge_unassigned.py::test_day_6_broadcast, tests/test_79_nudge_unassigned.py::test_nothing_after

**Spec:** `.scratch/nudge-settings-and-expected-delivery/spec.md`
**Binding:** `docs/adr/0013-nudge-settings-per-stage-and-expected-delivery.md` decisions 2–3; `docs/adr/0011-buyers-hand-off-requests-and-the-request-log.md` decision 4 (amended); ADR 0001

## What to build

The processed nudge stops being hardcoded (3, 6 with a channel post, then every 3) and follows a
settings file instead: on or off, every N working days, by DM and/or by a thread reply also
sent to the channel. With the shipped defaults it is "every 3 working days, DM only". An
unassigned request gets its thread line every N days until someone is assigned, instead of only
on days 3 and 6. Later tickets add the other three nudges to the same file.

1. New module `src/nudge_settings.py`:
   - `SETTINGS_PATH = os.path.join(config.BASE_DIR, "nudge_settings.json")`.
   - `DEFAULTS` exactly:
     `{"approved": {"enabled": False, "every": 3, "dm": True, "channel": False}, "processed": {"enabled": True, "every": 3, "dm": True, "channel": False}, "confirmed": {"enabled": True, "every": 5, "dm": True, "channel": False}, "delivered": {"enabled": True, "every": 10, "dm": False, "channel": True}}`.
   - `load(alert_callback=None) -> dict`: missing file → a deep copy of `DEFAULTS`; unreadable or
     non-object JSON → defaults, log at ERROR, and call `alert_callback` once with text naming
     `nudge_settings.json`; a missing stage key, or a stage whose `every` is not an int ≥ 1, takes
     that stage's default.
   - `validate(settings) -> dict[str, str]`: per stage, `"Pick DM, Channel or both."` under key
     `"<stage>_send"` when enabled with neither; `"Whole number, 1 or more."` under
     `"<stage>_every"` when `every` is not an int ≥ 1.
   - `save(settings) -> None`: atomic temp-file + `os.replace`, as `nudge._write_last_run` does.
   - Add `nudge_settings.json` to `.gitignore` beside `nudge_run.json`.
2. `src/nudge.py`: new pure `is_due(n: int, every: int) -> bool` → `n >= every and n % every == 0`.
   `run_nudges` loads the settings once per run with
   `nudge_settings.load(alert_callback=lambda m: slack_io.alert_admins(client, m))`.
3. `src/nudge.py` `run_nudges`, processed nudge (the existing two paths):
   - `processed.enabled` false → skip both paths.
   - **Assigned:** act when `is_due(n, every)`. `dm` true → today's DM-card re-post, unchanged.
     `channel` true → the existing broadcast reply
     `⏰ <@buyer> — this request was approved <n> working days ago and isn't marked Processed yet.`
     Remove the day-6-only rule.
   - **Unassigned:** act when `is_due(n, every)` with no upper limit. One thread line with the
     existing text; `reply_broadcast=True` only when `channel` is true. Remove the
     `n not in (3, 6)` rule.

## Acceptance criteria

New test file `tests/test_87_nudge_settings.py`; `nudge_settings.SETTINGS_PATH` and
`store.STORE_PATH` monkeypatched to temp files; existing fake-client helpers from
`tests/test_78_nudge_assigned.py`.

- [ ] **Loading.** No file → `load()` == `DEFAULTS`; file containing `not json` → defaults and the alert callback called once with text containing `nudge_settings.json`; file `{"processed": {"enabled": true, "every": 0, "dm": true, "channel": false}}` → `processed.every == 3` and the other three stages equal their defaults; `save(x)` then `load()` == `x`. `.gitignore` contains a line `nudge_settings.json`.
- [ ] **`is_due` and `validate`.** `is_due(2,3)` false, `(3,3)` true, `(6,3)` true, `(7,3)` false, `(0,3)` false. `validate` on `processed` enabled with `dm` and `channel` false returns `{"processed_send": "Pick DM, Channel or both."}`.
- [ ] **Defaults: DM every 3, no channel.** Rewrite in place `test_day_2_nothing_day_3_dm_only` (unchanged expectations) and add `test_default_day_6_and_9_dm_only`: day 6 and day 9 → one DM each, no `reply_broadcast` anywhere.
- [ ] **Settings change behaviour.** Settings file with `processed = {"enabled": true, "every": 2, "dm": false, "channel": true}` → day 2: exactly one post with `reply_broadcast=True` containing `<@buyer>`, no DM to the buyer; with `enabled: false` → day 3: no `chat_postMessage` at all.
- [ ] **Unassigned repeats.** In `tests/test_79_nudge_unassigned.py`, rewrite in place `test_day_3_unassigned_nudge` (unchanged) and add `test_unassigned_repeats_every_n`: defaults, day 6 and day 9 → one thread line each naming every buyer, no `reply_broadcast`; with `processed.channel` true → day 3 line has `reply_broadcast=True`.

**Tests may fake:** the Slack client, `log_writer.get_row_info`. **Must be real:** `nudge_settings` on the temp file, `nudge.run_nudges`, `store` on the temp file, `blocks`.

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
