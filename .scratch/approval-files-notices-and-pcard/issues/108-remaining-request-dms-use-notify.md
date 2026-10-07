# 108: The remaining request error DMs use `notify`

**Status:** ready-for-agent

**Runner:** any

**Auto-merge:** yes

**Blocked by:** 106

**Spec:** `.scratch/approval-files-notices-and-pcard/spec.md` (Part B, Implementation Decisions)
**Binding:** `docs/adr/0016-one-rule-for-who-is-told.md` (decisions 1–3); ADR 0001
**Glossary:** `CONTEXT.md` — **Quote**, **Edit**

## What to build

Move the last two request-related error DMs in `src/lifecycle.py` to `slack_io.notify`
(ticket 106). Their thread replies are unchanged.

1. `post_attachments_to_thread`: the `slack_io.tell(client, requester_id, msg)` sent when a
   quote fails to attach becomes
   `notify(client, actor_id=requester_id, requester_id=requester_id, requester_fix=True, text=msg, channel=channel, link_ts=thread_ts)`.
2. `handle_items_update`: the refusal ("⚠️ This purchase request has already been approved
   and line items can no longer be edited."), currently `slack_io.tell(client, user_id, ...)`,
   becomes `notify(client, actor_id=user_id, text=<same text>, channel=channel, link_ts=card_ts)`.

Do not touch: the assignee email-draft DM in `_send_assignee_dm`, the submission confirmation
("has been sent to the purchasing channel awaiting approval"), and every `tell` in
`src/app.py` and `src/ops.py`. None of these are request error notices.

## Acceptance criteria

- [ ] New `tests/test_108_remaining_notices.py`: a quote whose `files_info` raises produces a thread line naming the file (unchanged) and a DM to the requester ending with the `Open the thread` link.
- [ ] The edit refusal on an approved card DMs the clicking user with the same text plus the link.
- [ ] A source-scan test (as in ticket 106) shows `src/lifecycle.py` keeps exactly two `slack_io.tell(` calls: the assignee DM and the submission confirmation.
- [ ] `tests/test_81_quotes_on_new_purchase.py` passes unchanged.

May fake: the Slack client. Must be real: `notify` and the two lifecycle functions.

## Gate

Run all four, in CI's order, and all must pass:

    ruff check .
    python scripts/check_tests_first.py
    python tools/type_gate.py
    pytest --tb=short -q -n auto --dist loadfile

Tests need `SLACK_BOT_TOKEN=xoxb-test-not-a-real-token`, `SLACK_APP_TOKEN=xapp-test-not-a-real-token` and `PYTHONUTF8=1` in the environment, as `.github/workflows/tests.yml` sets.

## Comments
