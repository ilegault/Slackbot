# 106: One `notify` function; approval-path error DMs use it

**Status:** ready-for-agent

**Runner:** any

**Auto-merge:** yes

**Blocked by:** 105

**Spec:** `.scratch/approval-files-notices-and-pcard/spec.md` (Part B, stories 17–20)
**Binding:** `docs/adr/0016-one-rule-for-who-is-told.md` (decisions 1–3); AGENTS.md invariant 5 (`respond` for slash/button replies is unchanged); ADR 0001
**Glossary:** `CONTEXT.md` — **Request**, **Approver**, **Requester**

## What to build

Each request-related error DM picks its own recipient. One of them DM'd the bot itself.
Add one function and route the approval-path error DMs through it.

1. `src/slack_io.py` — new function:

       notify(client, *, actor_id: str | None, requester_id: str | None = None,
              requester_fix: bool = False, text: str, channel: str, link_ts: str) -> list[str]

   Recipients: `actor_id`, plus `requester_id` when `requester_fix` is True. Remove
   `None`, remove the bot's own id (`bot_user_id(client)` from ticket 100), and de-duplicate,
   keeping order. If that leaves nobody and `actor_id` is a person, use `actor_id`. The
   recipient decision is a separate **pure** helper,
   `notice_recipients(actor_id, requester_id, requester_fix, bot_id) -> list[str]`, so the
   rule can be tested without a client. Each recipient gets `text +
   f"\n<{permalink}|Open the thread>"`, with the permalink from
   `client.chat_getPermalink(channel=channel, message_ts=link_ts)["permalink"]`. If that
   call raises, send `text` alone and log a warning. Return the ids DM'd.
2. Replace these `slack_io.tell` calls in `src/lifecycle.py`. Every thread reply next to them
   stays.
   - `finalize_purchase_request`, the items-total failure and the validation failure:
     `actor_id=approver or notify_target`, `requester_id=notify_target`,
     `requester_fix=True`, `link_ts=thread_ts`.
   - `handle_epif_processing`, the parse-failure branch (`FlattenedPdfError`/`RuntimeError`):
     `actor_id=approver`, `requester_id=poster`, `requester_fix=True`.
   - `handle_epif_drop`, the parse-failure DM and the "can't be approved yet" DM from ticket
     102: `actor_id=user_id`, `requester_id=user_id`, `requester_fix=True`.

## Acceptance criteria

- [ ] New `tests/test_106_notify.py`. Table tests on `notice_recipients`: actor only; actor + requester with `requester_fix`; requester ignored without `requester_fix`; requester == actor → one id; requester == bot id → actor only; actor == bot id and requester None → `[]`.
- [ ] `notify` with a fake client: each DM's text ends with `<https://x/p|Open the thread>` when `chat_getPermalink` returns `{"permalink": "https://x/p"}`. When `chat_getPermalink` raises, the DM is still sent without the link.
- [ ] Regression for the 2026-10-05 failure: `handle_epif_processing` is called with `approver="U_APPROVER"`. The thread's only PDF is a flattened file named `X_EPIF.pdf` posted by the bot's own id (fake `auth_test` returns it). Exactly one DM is sent, to `U_APPROVER`, and none to the bot id.
- [ ] Approving a card whose data fails `validators.validate` DMs both the approver and the requester (two `chat_postMessage` calls with those `channel`s), and still posts the "Not logged" thread reply.
- [ ] `grep -n "slack_io.tell(" src/lifecycle.py` no longer lists the call sites named in step 2. Assert this in a test that reads the source file, as `tests/test_14_approve_payload.py::test_source_scan_no_sales_at_vendor_com_in_src` does.

May fake: the Slack client (`auth_test`, `chat_getPermalink`, `chat_postMessage`). Must be real: `notice_recipients`, `notify`, and the lifecycle functions under change.

## Gate

Run all four, in CI's order, and all must pass:

    ruff check .
    python scripts/check_tests_first.py
    python tools/type_gate.py
    pytest --tb=short -q -n auto --dist loadfile

Tests need `SLACK_BOT_TOKEN=xoxb-test-not-a-real-token`, `SLACK_APP_TOKEN=xapp-test-not-a-real-token` and `PYTHONUTF8=1` in the environment, as `.github/workflows/tests.yml` sets.

## Comments
