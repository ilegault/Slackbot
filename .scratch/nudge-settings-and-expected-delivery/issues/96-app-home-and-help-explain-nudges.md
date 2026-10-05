# 96: App Home and help explain nudges

**Status:** in-progress

**Runner:** any

**Auto-merge:** yes

**Blocked by:** 87, 89

**Spec:** `.scratch/nudge-settings-and-expected-delivery/spec.md`
**Binding:** `docs/adr/0013-nudge-settings-per-stage-and-expected-delivery.md` decision 3, 6; ADR 0001

## What to build

Everyone can see when the bot will chase them. App Home and `/purchasing-help` get a **Nudges**
section built from the live settings, so the words always match what the bot does. The stage
text also says the requester can mark Delivered.

1. `src/blocks.py`: new pure `nudge_summary_text(settings: dict) -> str`, one line per stage in
   this order, using exactly these templates (`<how>` = `by DM to <who>`, `in the channel`, or
   `by DM to <who> and in the channel`):
   - `• *Approved* — every <N> working days a card waits for approval, <how>` (who = `the approvers`)
   - `• *Processed* — every <N> working days after approval until processed, <how>` (who = `the buyer`)
   - `• *Confirmed* — every <N> working days after processing until confirmed, <how>` (who = `the buyer`)
   - `• *Delivered* — every <N> working days after confirmation until delivered, <how>, with a Delivered button. Set an expected delivery date to pause it until then.` (who = `the buyer and the requester`)
   - a disabled stage → `• *<Stage>* — off`
   followed by `_Working days are Monday–Friday. Checked weekdays at 9:00._`
   Use `N working day` (singular) when N is 1.
2. `src/blocks.py` `build_app_home_view`: add a header `⏰ Nudges` and a section with
   `nudge_summary_text(nudge_settings.load())` after **Request Stages**. `get_help_message` includes
   the same text, so the two surfaces cannot drift (the rule `blocks.py` already states for its
   shared constants).
3. `src/blocks.py` `_BUTTON_LIST`: the fragment
   `*Mark Processed*, *Mark Confirmed*, and *Mark Delivered* (the assigned buyer or an admin)`
   becomes `*Mark Processed* and *Mark Confirmed* (the assigned buyer or an admin), *Mark Delivered* (also the requester)`.
   `_STAGE_DEFINITIONS` `Delivered` line gains ` The requester can mark this too.`

## Acceptance criteria

New test file `tests/test_96_nudges_explained.py`; temp `nudge_settings.SETTINGS_PATH`.

- [ ] **Defaults rendered.** `nudge_summary_text(DEFAULTS)` contains `*Approved* — off`, `*Processed* — every 3 working days after approval until processed, by DM to the buyer`, `*Confirmed* — every 5 working days`, and `*Delivered* — every 10 working days after confirmation until delivered, in the channel`.
- [ ] **Both, and singular.** `processed = {"enabled": true, "every": 1, "dm": true, "channel": true}` → `every 1 working day after approval until processed, by DM to the buyer and in the channel`.
- [ ] **Live on App Home and in help.** With a settings file setting `delivered.every` to 15, `build_app_home_view("U_X")` contains a header `⏰ Nudges` and the text `every 15 working days after confirmation`; `get_help_message()` contains the same `nudge_summary_text` output verbatim.
- [ ] **Requester and Delivered.** App Home and help text contain `*Mark Delivered* (also the requester)` and `The requester can mark this too.` Existing App Home/help tests that assert the old wording are updated in place.

**Tests may fake:** nothing. **Must be real:** `blocks`, `nudge_settings` on the temp file, the roster on a temp file.

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
