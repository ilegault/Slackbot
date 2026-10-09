# 112: Files reach the buyer's DM, and the send is logged

**Status:** ready-for-agent

**Runner:** any

**Auto-merge:** yes

**Blocked by:** 111

**Spec:** `.scratch/epif-path-and-buyer-dm/spec.md` (Parts B and C, stories 8–10)
**Binding:** `docs/adr/0018-the-path-is-the-payment-method-and-the-dm-card-shows-the-request.md` (decision 3); `docs/adr/0006-bom-line-items-and-editable-posted-cards.md` (the archived BOM goes to the thread); ADR 0001; AGENTS.md §7 ("Log both ends of every request")

Blocked by 111 only because both edit `lifecycle._send_assignee_dm`.

## What to build

`slack_sdk`'s `WebClient.files_upload_v2` raises
`SlackRequestError("You cannot specify both the file and the content argument.")`
before it sends anything. Two call sites pass both arguments, so the filled EPIF, the BOM
and the quotes never reach the buyer's DM, and the archived BOM never reaches the thread.
Production log, 2026-10-05: "Could not upload archived BOM 0022_Fisher-Scientific_BOM.xlsx:
You cannot specify both the file and the content argument." The suite missed it because
its `MagicMock` client accepts any arguments. Separately, a successful buyer DM writes
nothing to the log, so "the buyer got nothing" cannot be checked.

1. `src/lifecycle.py` `_send_assignee_dm`, the `files_upload_v2` call inside the DM-upload
   loop: pass `channel`, `file=path`, `filename`, `title`, and **no** `content`. Delete the
   `with open(path, "rb") ...` read that only fed `content`. The `files_upload` fallback
   branch is unchanged.
2. `src/lifecycle.py` `upload_archived_bom`: remove `"content"` from the
   `files_upload_v2` kwargs, and delete the read that fed it. The `files_upload` fallback
   branch is unchanged.
3. `src/lifecycle.py` `_send_assignee_dm`:
   - right after `slack_io.tell(client, assignee_id, dm_text)` succeeds, log at INFO
     `"📨 Buyer DM sent to %s for row %s (%s path)"` with `assignee_id`, `row`, `route`;
   - right after `slack_io.post_dm_card` returns a non-`None` result, log at INFO
     `"📨 DM card posted to %s (card %s)"` with `assignee_id`, `card_ts`.
4. Add a `Per Ticket 112` paragraph to the module docstring saying why `content` is never
   passed alongside `file`.

## Acceptance criteria

- [ ] New `tests/test_112_uploads_and_dm_log.py` builds a **real** `slack_sdk.WebClient(token="xoxb-test-not-a-real-token")` and patches only its network methods: `files_getUploadURLExternal`, `_upload_file` and `files_completeUploadExternal` return canned successes, and `chat_postMessage`, `conversations_open` and `chat_getPermalink` return canned dicts. Calling `lifecycle._send_assignee_dm(..., route="epif", epif_path=<temp PDF>, epif_fname=..., bom_path=<temp xlsx>, bom_fname=...)` raises nothing, logs no "Could not upload" warning, and calls `files_getUploadURLExternal` once per file with each file's name.
- [ ] With the same real-client setup, `lifecycle.upload_archived_bom(client=..., channel=..., thread_ts=..., file_path=<temp xlsx>, filename=...)` raises nothing, logs no "Could not upload archived BOM" warning, and uploads the file under that name.
- [ ] With `caplog` at INFO, an EPIF-path `_send_assignee_dm` call with a buyer id and row 7 produces one record containing `📨 Buyer DM sent to <buyer id> for row 7 (epif path)` and one containing `📨 DM card posted to <buyer id>`. A Workday-path call produces `(workday path)`.
- [ ] In the **same test function** as the previous criterion (it passes on today's code alone, and the gate holds a PR whose new test passes on base): when `slack_io.tell` raises, there is no `📨 Buyer DM sent` record. The existing `Could not DM assignee` warning still appears.
- [ ] No existing test is deleted or loses assertions. Any existing assertion on these two call sites' `content=` keyword is rewritten in place to assert `file=`.

May fake: Slack's network methods, listed above. Must be real: `slack_sdk.WebClient.files_upload_v2` itself, which does the argument check under test, and real files on disk under `tmp_path`. A `MagicMock` client does not count as proof for the first two criteria.

## Gate

Run all four, in CI's order, and all must pass:

    ruff check .
    python scripts/check_tests_first.py
    python tools/type_gate.py
    pytest --tb=short -q -n auto --dist loadfile

Tests need `SLACK_BOT_TOKEN=xoxb-test-not-a-real-token`, `SLACK_APP_TOKEN=xapp-test-not-a-real-token` and `PYTHONUTF8=1` in the environment, as `.github/workflows/tests.yml` sets.

## Comments
