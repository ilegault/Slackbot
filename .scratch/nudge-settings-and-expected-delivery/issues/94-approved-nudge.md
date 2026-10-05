# 94: Approved nudge

**Status:** in-progress

**Runner:** any

**Auto-merge:** yes

**Blocked by:** 87, 93

**Spec:** `.scratch/nudge-settings-and-expected-delivery/spec.md`
**Binding:** `docs/adr/0013-nudge-settings-per-stage-and-expected-delivery.md` decisions 1, 2, 4, 7; ADR 0001

## What to build

When an admin turns it on (it ships **off**), the **approved** nudge reminds the approvers about a
posted card nobody has approved: every N working days from posting, by DM with a link to the card,
and/or a thread reply also sent to the channel. It stops as soon as the card is approved, declined
or superseded.

1. `src/nudge.py` `run_nudges`: for an entry with `posted_at`, no `approved_at`, and none of
   `declined` / `superseded` / `cancelled`; `approved.enabled` true;
   `is_due(working_days_between(posted_at date, today), approved.every)`; and the thread card
   (`slack_io.get_card_by_ts`) still in state `posted`:
   - `dm` → to each ID in `roster.get_approvers()`:
     `⏰ *<item>* from <requester> has been waiting for approval for <n> working days: <permalink>`
     (permalink from `client.chat_getPermalink(channel=..., message_ts=card_ts)`, as the processed
     nudge gets it; no buttons);
   - `channel` → thread reply with `reply_broadcast=True`:
     `⏰ <@A1> <@A2> — this request has been waiting for approval for <n> working days.`;
   - `store.update(id, last_nudged=today.isoformat())`.
   A card no longer `posted` (approved by keyword before the log caught up, etc.) → skip.

## Acceptance criteria

New test file `tests/test_94_approved_nudge.py`; temp log, settings and roster (approvers `U_A1`,
`U_A2`); entry posted Monday 2026-10-05 with a `posted` thread card; settings with
`approved = {"enabled": true, "every": 3, "dm": true, "channel": false}` unless stated.

- [ ] **Off by default.** With no settings file, 2026-10-08 → nothing posted.
- [ ] **Day 3 DMs every approver.** 2026-10-07 → nothing. 2026-10-08 → one DM each to `U_A1` and `U_A2` containing `waiting for approval for 3 working days` and the fake permalink; no `actions` block; no thread post.
- [ ] **Channel option.** `dm` false, `channel` true → day 3: one thread post with `reply_broadcast=True` containing `<@U_A1>` and `<@U_A2>`; no DMs.
- [ ] **Stops.** Each on day 3 → nothing: `declined: true`; `superseded: true`; `approved_at` set; thread card state `approved`; `last_nudged` already today.
- [ ] **Day 6 repeats.** 2026-10-13 → the DMs again.

**Tests may fake:** the Slack client, `log_writer.get_row_info`. **Must be real:** `nudge`, `nudge_settings`, `store` and `roster` on temp files.

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
