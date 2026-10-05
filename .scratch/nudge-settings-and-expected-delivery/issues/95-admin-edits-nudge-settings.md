# 95: Admin edits nudge settings from App Home

**Status:** done

**Runner:** any

**Auto-merge:** yes

**Blocked by:** 87

**Spec:** `.scratch/nudge-settings-and-expected-delivery/spec.md`
**Binding:** `docs/adr/0013-nudge-settings-per-stage-and-expected-delivery.md` decision 3; ADR 0001

## What to build

An admin can change the four nudges without touching the server: App Home shows them an **Edit
nudge settings** button that opens a form, pre-filled from the current settings, with on/off,
"every N working days" and DM/Channel for each nudge. Saving writes `nudge_settings.json` and the
next 9:00 run uses it. Nobody else sees the button, and a non-admin submit is refused.

1. `src/config.py`: `ACTION_OPEN_NUDGE_SETTINGS = "open_nudge_settings"`,
   `NUDGE_SETTINGS_CALLBACK_ID = "nudge_settings_submit"`.
2. `src/blocks.py` `build_app_home_view`: when `user_id` is an admin (same check the function
   already uses for the Roles line), add after the Admin Operations section an `actions` block
   with one button `Edit nudge settings`, `action_id` `config.ACTION_OPEN_NUDGE_SETTINGS`.
3. `src/blocks.py`: new `build_nudge_settings_view(settings: dict) -> dict`, `callback_id`
   `config.NUDGE_SETTINGS_CALLBACK_ID`, title `Nudge settings`. For each stage `s` in
   `approved`, `processed`, `confirmed`, `delivered`, a header/section naming it and three `input`
   blocks:
   - `block_<s>_enabled`: optional `checkboxes`, `action_id` `enabled`, one option `on` (`On`),
     ticked when enabled;
   - `block_<s>_every`: `number_input`, `action_id` `every`, `is_decimal_allowed` false,
     `min_value` `"1"`, `initial_value` the current N, label `Every N working days`;
   - `block_<s>_send`: optional `checkboxes`, `action_id` `send`, options `dm` (`DM`) and
     `channel` (`Channel (thread reply also sent to the channel)`), ticked per the settings.
4. `src/app.py`: `@app.action(config.ACTION_OPEN_NUDGE_SETTINGS)` → non-admin: `slack_io.tell` the
   user `🔒 Only admins can change nudge settings.` and open nothing; admin:
   `views_open(... build_nudge_settings_view(nudge_settings.load(...)))`.
   `@app.view(config.NUDGE_SETTINGS_CALLBACK_ID)` → non-admin:
   `ack(response_action="errors", errors={"block_approved_enabled": "Only admins can change nudge settings."})`.
   Parse into the settings shape, run `nudge_settings.validate`, and map its keys to block ids
   (`<s>_send` → `block_<s>_send`, `<s>_every` → `block_<s>_every`) in
   `ack(response_action="errors", ...)`. Valid → `ack()`, `nudge_settings.save(...)`,
   `views_publish` the admin's App Home, and post a line to `config.ADMIN_ALERT_CHANNEL` naming who
   changed the settings.

## Acceptance criteria

New test file `tests/test_95_nudge_settings_form.py`; temp roster (admin `U_ADM`, non-admin
`U_X`) and temp `nudge_settings.SETTINGS_PATH`; prior art `tests/test_22_live_roster_panel.py`
for App Home and `tests/test_19_roster_set_name.py` for a view submission.

- [x] **Only admins see the button.** `build_app_home_view("U_ADM")` contains a button with `action_id == "open_nudge_settings"`; `build_app_home_view("U_X")` does not.
- [x] **The form is pre-filled.** `build_nudge_settings_view(DEFAULTS)` has the 12 block ids `block_<s>_enabled|every|send`; `block_delivered_every` `initial_value == "10"`; `block_delivered_send` has only `channel` in `initial_options`; `block_approved_enabled` has no `initial_options`.
- [x] **Saving.** `U_ADM` submitting `delivered` every `15`, DM+Channel → `ack()` with no errors; `nudge_settings.load()["delivered"] == {"enabled": True, "every": 15, "dm": True, "channel": True}`; `views_publish` called for `U_ADM`; one post to the admin alert channel containing `<@U_ADM>`.
- [x] **Validation.** `processed` on with neither DM nor Channel → `errors == {"block_processed_send": "Pick DM, Channel or both."}` and the file is unchanged; `every` `0` → an error on `block_<s>_every`.
- [x] **Non-admins refused.** `U_X` clicking the button → a DM containing `Only admins` and no `views_open`; `U_X` submitting → the refusal error and the file unchanged.

**Tests may fake:** the Slack client. **Must be real:** `blocks`, both handlers, `nudge_settings` on the temp file, the roster on a temp file.

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

2026-10-05: Added config ids, admin-only App Home button, `blocks.build_nudge_settings_view`, and `handle_open_nudge_settings_action` / `handle_nudge_settings_submit` in app.py. All five criteria are covered by `tests/test_95_nudge_settings_form.py`. `tests/test_22_live_roster_panel.py::_extract_all_text` now handles button elements whose text is an object (harness defect; assertions unchanged).
