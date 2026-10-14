# 133: "Send me the BOM template" button, and /blank-template sends it too

**Status:** in-progress

**Runner:** any

**Auto-merge:** yes

**Blocked by:** 121

**Spec:** `.scratch/bom-template-and-epif-date/spec.md` (Part E, stories 30–31, 64)
**Binding:** `docs/adr/0019-boms-come-in-through-the-lab-template-and-are-read.md`; `docs/adr/0001-tests-first-and-no-muted-failures.md`; AGENTS.md invariant 5 (replies)
**Glossary:** `CONTEXT.md` — **BOM template**, **DM**

## What to build

Requesters need to learn the template exists at the moment they need it.

- **The button.** Beside the BOM file field on interview Screen 2 there is a button
  **Send me the BOM template**. Clicking it DMs the requester `HIRST_LAB_BOM_TEMPLATE.xlsx`.
  The form stays open.
- **The hint.** The BOM field's hint reads `Two or more items? Fill in the lab BOM template.`
- **`/blank-template`** posts the BOM template as well as the EPIF.

1. **`config`**: `ACTION_SEND_BOM_TEMPLATE = "send_bom_template"`.
2. **`blocks`** — wherever the BOM file field is built (`block_bom`), add an `actions` block
   directly after it, with that button. Set the field hint text.
3. **`ops.send_bom_template(client, user_id) -> bool`** — opens the DM with
   `conversations_open` and uploads `config.BOM_TEMPLATE_PATH` with `files_upload_v2`.
   - If the file is missing, it alerts admins with `text_rules.storage_problem_message`, as
     `ops.handle_template_command` does for the EPIF.
   - The new action listener in `app` acks and calls it. It never calls
     `views_update`/`views_open`, so the form is untouched.
4. **`ops.handle_template_command`** also calls `send_bom_template` for the user.
5. **`p_bot.spec`** — add `templates/HIRST_LAB_BOM_TEMPLATE.xlsx` to `datas` so the executable
   build carries it. Confirm `config.BOM_TEMPLATE_PATH` resolves inside the bundle the same
   way `roster.json` does.

## Acceptance criteria

- [ ] New file `tests/test_133_send_bom_template.py`, `test_screen2_offers_the_template`:
  - `blocks.build_stage2_view` (new-request meta) has an element with `action_id == "send_bom_template"` in the block directly after `block_bom`.
  - The `block_bom` hint contains `lab BOM template`.
- [ ] `test_button_dms_the_template`: dispatching the action through the real Bolt app's listener registry (find the listener as `tests/test_15_purchasing_channel.py` or an existing action test does) results in:
  - one `files_upload_v2` whose `filename` is `HIRST_LAB_BOM_TEMPLATE.xlsx`, to the DM channel the fake `conversations_open` returned;
  - zero `views_update` and zero `views_open` calls.
- [ ] `test_blank_template_sends_both`: `ops.handle_template_command` uploads both the EPIF template and `HIRST_LAB_BOM_TEMPLATE.xlsx`.
- [ ] `test_missing_template_alerts_admin`: with `config.BOM_TEMPLATE_PATH` pointing at a missing file, the click uploads nothing and posts one admin alert naming `BOM_TEMPLATE_PATH`.

May fake: the Slack client. Must be real: the committed template file (assert the uploaded `file` path exists and opens with openpyxl), the real Bolt listener registry.

## Gate

Run all four, in CI's order, and all must pass:

    ruff check .
    python scripts/check_tests_first.py
    python tools/type_gate.py
    pytest --tb=short -q -n auto --dist loadfile

Tests need `SLACK_BOT_TOKEN=xoxb-test-not-a-real-token`, `SLACK_APP_TOKEN=xapp-test-not-a-real-token` and `PYTHONUTF8=1` in the environment, as `.github/workflows/tests.yml` sets.

The gate holds a PR that adds a new test which already passes on today's code. Where a ticket says checks share one test function, keep them together so the function fails on the base commit.

## Comments
