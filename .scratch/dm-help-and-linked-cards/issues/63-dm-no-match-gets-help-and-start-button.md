# 63: A DM the bot cannot read gets the help text and a Start button

**Status:** in-progress

**Runner:** any

**Auto-merge:** yes

**Blocked by:** 53, 62

**Spec:** `.scratch/dm-help-and-linked-cards/spec.md` (items 2–3)
**Binding:** `docs/adr/0010-linked-cards-and-direct-message-help.md` decision 5 (amends `docs/adr/0009-keywords-storage-settings-and-the-bot-name.md` decision 3 for DMs only), ADR 0001

## What to build

A lab member's first DM is often a sentence with a link, not a keyword. After 51 and 53
the bot answers it `I don't know "I"` plus a pointer to `@Purchasing help`. In a **DM
only**, when the first word has no close match (ticket 53's `text_rules.closest_keyword`
returns `None`), the bot instead replies with one message: a **Start a purchase request**
button above the full help text. In a channel mention, and in a DM with a close match,
behaviour is exactly ticket 53's.

1. `dispatch_command` in `src/app.py` gains `is_dm: bool = False`. `on_direct_message`
   passes `is_dm=True`; `on_mention` does not.
2. Add a pure function `blocks.chunk_mrkdwn(text: str, limit: int = 2900) -> list[str]`:
   split on blank lines, pack paragraphs into chunks of at most `limit` characters (a
   section block holds 3000), never return an empty chunk, and split a single paragraph
   longer than `limit` on line breaks.
3. Add `blocks.build_dm_help_blocks() -> list`: a section with the text
   `🤔 I can't read free-form requests, but here is what I can do. To start a purchase, press the button below.`;
   an `actions` block with one primary button, text `Start a purchase request`,
   `action_id` `start_purchase_interview` (copy the element from `build_app_home_view`,
   which uses the same action id); a divider; then one section per chunk of
   `chunk_mrkdwn(get_help_message())`.
4. In the unknown-word branch, when `is_dm` and there is no suggestion, call
   `say(text=blocks.get_help_message(), blocks=blocks.build_dm_help_blocks(), thread_ts=thread_ts)`
   once. The button opens a blank form: **nothing from the DM is carried into it.**

## Acceptance criteria

- [ ] **`chunk_mrkdwn` is tested directly** in `tests/test_63_dm_help.py`: the real
  `blocks.get_help_message()` yields chunks that are each at most 2900 characters, none
  empty, and whose paragraphs joined by a blank line equal the original text with
  surrounding whitespace stripped; a synthetic 7 000-character text of short lines does the
  same; a single 4 000-character line is split (no chunk over the limit).
- [ ] **A sentence in a DM gets help and the button.** Drive the real `message` listener
  (`app.on_direct_message`, as ticket 62's test does) with
  `{"user": "U1", "channel": "D1", "channel_type": "im", "ts": "1.1", "text": "I want to purchase this: <https://example.com/x?a=1&amp;b=2|example.com/x>"}`:
  exactly one `say`; its `blocks` contain an `actions` block whose button has
  `action_id == "start_purchase_interview"`, and a section whose text contains the first
  heading line of `blocks.get_help_message()`.
- [ ] **A near-miss in a DM keeps ticket 53's reply.** `remve-vendor Thorlabs` in a DM: one
  `say` whose text contains `@Purchasing remove-vendor` and whose `blocks` argument is
  absent or contains no `actions` block (absence asserted).
- [ ] **A channel mention is unchanged.** `<@BOT> flurb` through the real `app_mention`
  listener: one `say` containing `@Purchasing help`, with no `blocks` and no
  `start_purchase_interview` anywhere in the call (absence asserted).
- [ ] **The button opens a blank form.** Call `app.handle_start_purchase_interview` with a
  body shaped like a click in a DM (`channel.id` `D1`, a `trigger_id`, no `container.thread_ts`,
  and a `message.text` containing `https://example.com/x`): `client.views_open` is called
  once with that `trigger_id`, and `json.dumps` of the opened view does not contain
  `example.com`.

**Tests may fake:** the Slack client and `say`. **Must be real:** `dispatch_command`, the
listeners, `text_rules`, `blocks`, and the roster (a temp copy, as `tests/test_regression_guards.py` sets up).

## Gate

Run in this order, exactly as CI does (`.github/workflows/tests.yml`). Zero failures before
you push. If `tools/type_gate.py` exists on `master` when you start, also run
`python tools/type_gate.py` after `check_tests_first.py`, and use
`pytest --tb=short -q -n auto --dist loadfile` in place of the last line.

```
ruff check .
python scripts/check_tests_first.py
pytest -q --tb=short --durations=25
```

## Comments

