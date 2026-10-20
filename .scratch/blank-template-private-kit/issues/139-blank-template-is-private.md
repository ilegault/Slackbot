# 139: `/blank-template` sends the template kit privately

**Status:** done

**Runner:** any

**Auto-merge:** yes

**Blocked by:** 138

**Spec:** `.scratch/blank-template-private-kit/spec.md` (decisions 2–7)
**Binding:** `docs/adr/0002-request-lifecycle-and-surfaces.md`; `docs/adr/0016-one-rule-for-who-is-told.md`; `docs/adr/0019-boms-come-in-through-the-lab-template-and-are-read.md`; `docs/adr/0001-tests-first-and-no-muted-failures.md`; AGENTS.md invariant 5 (replies)
**Glossary:** `CONTEXT.md` — **Template kit**, **BOM template**, **DM**, **Alert channel**

## What to build

Today `/blank-template` posts the guide and the EPIF template publicly in the channel it is
typed in, and DMs the BOM template separately. After this ticket the whole kit goes to the
asker's DM as one message, and the channel they typed in shows only a note that only they
can see.

1. **`src/ops.py`** — replace `handle_template_command` with
   `send_template_kit(client, user_id: str) -> str | None`. Delete `handle_template_command`
   (ticket 138 removed its only other caller). `send_template_kit`:
   - Checks `config.EPIF_TEMPLATE_PATH` and `config.BOM_TEMPLATE_PATH` each the way
     `handle_template_command` checks the EPIF today (blank → reason `"not set"`, not a file
     → reason `"does not exist"`). For each unusable one, call
     `slack_io.alert_admins(client, text_rules.storage_problem_message(<SETTING>, <value or "">, <reason>))`,
     as `ops.send_bom_template` already does.
   - Opens the DM with `client.conversations_open(users=user_id)["channel"]["id"]`, as
     `ops.send_bom_template` does.
   - Builds the message text: the guide (below), then one line per missing file, exactly
     `⚠️ The blank EPIF template could not be attached. An admin has been told.` and/or
     `⚠️ The BOM template could not be attached. An admin has been told.`
   - If at least one file is usable: **one** `client.files_upload_v2(channel=<dm>, initial_comment=<text>, file_uploads=[...])`
     call, EPIF first. Each entry is `{"file": <path>, "filename": <name>, "title": <name>}`,
     with names `EPIF_TEMPLATE_HIRST.pdf` and `HIRST_LAB_BOM_TEMPLATE.xlsx`. If neither is
     usable: one `client.chat_postMessage(channel=<dm>, text=<text>)`.
   - Returns the DM channel id. Any exception from `conversations_open`, `files_upload_v2`
     or `chat_postMessage` is caught, logged with `log.warning`, and returns `None`.
   - It never posts to any channel other than the DM and the alert channel. It is a plain
     function of `(client, user_id)` with no `say` and no channel argument, so the "never
     public" rule can be tested without Bolt.
2. **The guide text** (the `initial_comment` before any missing-file lines), exactly:

       📄 *Hirst Lab Manual EPIF Submission Kit:*

       1. Open the attached `EPIF_TEMPLATE_HIRST.pdf` in Adobe Acrobat or your PDF editor.
       2. Fill in the required fields: *What*, *Why / URL*, *Amount*, *Vendor*, *Vendor Email*, *Date*, *Room*, *Project ID*, and tick *1 Category* + *Payment Method*.
       3. *Two or more items?* Also fill in the attached `HIRST_LAB_BOM_TEMPLATE.xlsx`. One vendor per BOM, and its total must equal the EPIF *Amount*.
       4. Post your completed PDF (and BOM, if you have one) in a thread in the purchasing channel and tag APPROVER for approval.
       5. Once approved, the Purchasing bot will validate and log your request automatically!

   `APPROVER` stands for the person's name that today's step 3 of the guide in
   `ops.handle_template_command` uses ("…and tag <name> for approval"). Copy that name
   exactly. Do not substitute a role word.
3. **`src/app.py`, `handle_blank_template_command`** — the signature becomes
   `(ack, body, respond, client)` (Bolt injects by name). It acks first, then calls
   `ops.send_template_kit(client, body["user_id"])`. Delete the local `say` helper.
   - Returns `None`: `slack_io.deny(respond, "⚠️ I couldn't DM you the templates. Ask an admin.")`.
   - Returns a DM id equal to `body.get("channel_id")` (the command was typed in the asker's
     own DM with the bot): no note.
   - Any other DM id: `slack_io.deny(respond, "📬 Sent the EPIF and BOM templates to <https://slack.com/app_redirect?channel=<dm>|your DM>.")`.
   - Use `respond`, never `chat_postEphemeral`. `chat_postEphemeral` fails outside channels
     the bot is in, and `tests/test_regression_guards.py::test_zero_chat_post_ephemeral_call_sites_in_src`
     pins zero call sites.
4. **`src/blocks.py`, `_SLASH_COMMANDS`** — the `/blank-template` line becomes exactly
   ``• `/blank-template` — DMs you the blank EPIF PDF and the lab BOM template, with instructions.\n``.
   App Home (`build_app_home_view`) and `get_help_message` both render `_SLASH_COMMANDS`, so
   both pick it up.
5. **Docstrings** — `send_template_kit` gets a WHY THIS EXISTS block citing this ticket and
   the spec. Update the reference to `ops.handle_template_command` in the `src/path_validator.py`
   module docstring to `ops.send_template_kit`.

## Acceptance criteria

All new tests go in the new file `tests/test_139_template_kit.py`. The fake client's
`conversations_open` returns `{"channel": {"id": "D_ASKER"}}`. `config.ADMIN_ALERT_CHANNEL`
is monkeypatched to `"C_ADMIN"`.

- [x] `test_kit_is_one_dm_with_both_files`: with `EPIF_TEMPLATE_PATH` pointing at a temp PDF
  and `BOM_TEMPLATE_PATH` left at the committed template, `ops.send_template_kit(client, "U1")`
  returns `"D_ASKER"`. There is exactly one `files_upload_v2` call, with `channel == "D_ASKER"`
  and `[u["filename"] for u in file_uploads] == ["EPIF_TEMPLATE_HIRST.pdf", "HIRST_LAB_BOM_TEMPLATE.xlsx"]`.
  Its `initial_comment` contains `Hirst Lab Manual EPIF Submission Kit`, `Two or more items?`
  and `HIRST_LAB_BOM_TEMPLATE.xlsx`, and contains no `could not be attached`. `chat_postMessage`
  is not called.
- [x] `test_command_in_a_channel_is_private`: call
  `app.handle_blank_template_command(ack, {"channel_id": "C_PURCH", "user_id": "U1"}, respond, client)`
  with both files real. No `chat_postMessage` or `files_upload_v2` call on the fake client has
  `channel == "C_PURCH"`. `respond` is called once with `response_type="ephemeral"` and text
  containing `Sent the EPIF and BOM templates to` and
  `https://slack.com/app_redirect?channel=D_ASKER`.
- [x] `test_note_only_skipped_in_own_bot_dm`: the same call with `channel_id="D_ASKER"` makes
  the upload and does not call `respond`. With `channel_id="D_SOMEONE_ELSE"` (a DM with
  another person), `respond` is called once with the note.
- [x] `test_missing_template_still_sends_the_rest`:
  - With `BOM_TEMPLATE_PATH` set to a missing temp path, there is one upload carrying only
    `EPIF_TEMPLATE_HIRST.pdf`. Its `initial_comment` contains
    `⚠️ The BOM template could not be attached. An admin has been told.` There is exactly one
    `chat_postMessage` to `C_ADMIN`, with
    `text == text_rules.storage_problem_message("BOM_TEMPLATE_PATH", <that path>, "does not exist")`.
  - With `EPIF_TEMPLATE_PATH = ""` as well, there are zero uploads and one `chat_postMessage` to
    `D_ASKER` whose text contains the guide heading and both missing-file lines. There are two
    `chat_postMessage` calls to `C_ADMIN`, naming `EPIF_TEMPLATE_PATH` (`not set`) and
    `BOM_TEMPLATE_PATH`.
- [x] `test_dm_failure_is_private_and_help_line`:
  - With `client.conversations_open.side_effect = Exception("cannot_dm_bot")`, calling the
    handler with `channel_id="C_PURCH"` makes no `chat_postMessage` or `files_upload_v2` call
    with `channel == "C_PURCH"`. `respond` is called once, ephemeral, with text containing
    `I couldn't DM you the templates. Ask an admin.`
  - `blocks.get_help_message()` contains
    `` `/blank-template` — DMs you the blank EPIF PDF and the lab BOM template, with instructions.``
- [x] Existing tests that pinned the public behaviour are rewritten in place, same names, to assert
  the new behaviour through `ops.send_template_kit` or the handler (new argument order
  `(ack, body, respond, client)`); none is skipped or xfailed: `test_blank_template_sends_both`,
  `test_startup_and_blank_template_agree_missing_and_real`, `test_blank_template_uses_storage_problem_message`,
  `test_scanned_surfaces_contain_no_p_bot_and_have_purchasing_bot`, `test_template_command`,
  `test_every_command_acks_before_client_calls`, `test_no_slash_command_calls_chat_post_ephemeral`,
  `test_slash_commands_ack_before_client_and_never_call_post_ephemeral`. Per file:

  - `tests/test_133_send_bom_template.py::test_blank_template_sends_both`: one upload whose `file_uploads` names both files.
  - `tests/test_54_storage_settings.py::test_startup_and_blank_template_agree_missing_and_real`:
    - Missing path: the startup check names `EPIF_TEMPLATE_PATH`, and the admin alert text contains `EPIF_TEMPLATE_PATH`, the missing path and `An admin needs to fix the server's .env.`
    - Real path: the single upload's first `file_uploads` entry has `file == str(real_pdf)`.
  - `tests/test_56_storage_problems.py::test_blank_template_uses_storage_problem_message`: the admin alert text equals `storage_problem_message(...)` for the missing case and the unset case.
  - `tests/test_58_bot_name.py::test_scanned_surfaces_contain_no_p_bot_and_have_purchasing_bot`, section 8: read the guide from the upload's `initial_comment`.
  - `tests/test_onboarding_and_commands.py`:
    - `::test_template_command`: rewrite against `ops.send_template_kit`.
    - `::test_every_command_acks_before_client_calls` and `::test_no_slash_command_calls_chat_post_ephemeral`: patch `ops.send_template_kit` instead of `ops.handle_template_command`, and pass `respond`.
  - `tests/test_regression_guards.py::test_slash_commands_ack_before_client_and_never_call_post_ephemeral`: the `/blank-template` row becomes `uses_client=True, uses_respond=True` (the loop's existing `else` branch calls `handler(ack, body, respond, client)`).

May fake: the Slack client, `ack` and `respond`. Must be real: `ops.send_template_kit`,
`app.handle_blank_template_command`, `slack_io.alert_admins`, `slack_io.deny`,
`text_rules.storage_problem_message`, the committed `templates/HIRST_LAB_BOM_TEMPLATE.xlsx`,
and real temp files for the EPIF template.

## Gate

Run all four, in CI's order, and all must pass:

    ruff check .
    python scripts/check_tests_first.py
    python tools/type_gate.py
    pytest --tb=short -q -n auto --dist loadfile

Tests need `SLACK_BOT_TOKEN=xoxb-test-not-a-real-token`, `SLACK_APP_TOKEN=xapp-test-not-a-real-token` and `PYTHONUTF8=1` in the environment, as `.github/workflows/tests.yml` sets.

The gate holds a PR that adds a new test which already passes on today's code. Every new
test above calls `ops.send_template_kit` or asserts the new help line, so each fails on
today's code.

## Comments
Done 2026-10-20: added ops.send_template_kit (one DM, both files, guide as initial_comment), removed handle_template_command, rewired /blank-template to respond + private note, updated _SLASH_COMMANDS and path_validator docstring. New tests in tests/test_139_template_kit.py; 9 older tests rewritten in place (none skipped). Gate green: ruff, tests-first, type_gate (ratchet 95), pytest 888 passed. Not deployed: the developer runs @Purchasing update after merge.
