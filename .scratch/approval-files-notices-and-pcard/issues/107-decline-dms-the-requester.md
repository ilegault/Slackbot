# 107: A decline DMs the requester

**Status:** ready-for-agent

**Runner:** any

**Auto-merge:** yes

**Blocked by:** 106

**Spec:** `.scratch/approval-files-notices-and-pcard/spec.md` (Part B, stories 21–22)
**Binding:** `docs/adr/0016-one-rule-for-who-is-told.md` (decision 4); `docs/adr/0003-decline-and-cancel.md` (decisions 2–3 as amended: no reason, no row, no log entry); ADR 0001
**Glossary:** `CONTEXT.md` — **Decline**

## What to build

`lifecycle.handle_decline(client, channel, msg_ts, user_id, req_data, history)` updates the
card to "declined" and flags the request-log entry. It sends no DM. After the card update,
call `slack_io.notify` with:

- `actor_id=user_id` (the decliner), `requester_id=req_data.get("user_id")`, `requester_fix=True`
  (so the requester always receives it), `channel=channel`, `link_ts=msg_ts` (the link goes to
  the card).
- `text` exactly:
  `Your request for *{item}* ({vendor}, {price}) was declined by {decliner name}.`
  `{item}` and `{vendor}` come from `req_data["parsed"]` when present, otherwise from
  `req_data` itself (the same fallback `handle_epif_processing` uses for `posted_payload`).
  `{price}` is formatted `$1,234.50`. `{decliner name}` is the `user_name` the function
  already resolves. `notify` appends the thread link.

Because `notify` also DMs the actor, the decliner receives the same DM. That is acceptable and
matches ADR 0016 decision 2 ("the person who acted").

Update the `handle_decline` docstring: it no longer says "no DM is sent".

## Acceptance criteria

- [ ] New `tests/test_107_decline_dm.py`: decline a posted card whose payload `user_id` is `U_REQ`, with decliner `U_APPROVER`. A DM goes to `U_REQ` whose text starts with the exact sentence above, including the item, vendor and formatted price.
- [ ] A decliner who is also the requester gets exactly one DM.
- [ ] No row is written. The temp workbook's row count is unchanged, and the request-log entry is flagged `declined=True` exactly as `tests/test_93_posted_cards_logged.py::test_decline_flags_entry` asserts.
- [ ] The existing decline tests in `tests/test_05_decline_cancel.py` pass unchanged, or are rewritten **in place, same name** where one asserted that no DM is sent.

May fake: the Slack client. Must be real: `handle_decline`, `notify`, the store on its isolated temp path.

## Gate

Run all four, in CI's order, and all must pass:

    ruff check .
    python scripts/check_tests_first.py
    python tools/type_gate.py
    pytest --tb=short -q -n auto --dist loadfile

Tests need `SLACK_BOT_TOKEN=xoxb-test-not-a-real-token`, `SLACK_APP_TOKEN=xapp-test-not-a-real-token` and `PYTHONUTF8=1` in the environment, as `.github/workflows/tests.yml` sets.

## Comments
