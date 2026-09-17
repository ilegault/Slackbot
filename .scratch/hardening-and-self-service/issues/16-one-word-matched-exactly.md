# 16: One word, matched exactly, with a reply when it is unknown

**What to build:** The first word after the mention is matched exactly against
the canonical vocabulary and nothing else. "@Purchasing can you **check** this?"
stops attempting a full approval and an Excel write, and a word the bot does not
know gets a short reply naming the words it does.

**Blocked by:** 12

**Status:** done

**Read before starting:** `CONTEXT.md`'s **Keyword** entry,
`docs/adr/0004-assignment-replaces-claim.md` **decision 8** (binding, and the
reason mention-stripping comes first), and
`docs/adr/0001-tests-first-and-no-muted-failures.md`.

## Why

Keyword routing is a chain of substring matches. In a request thread today:

- "@Purchasing can you **check** this?" → attempts a full approval and an Excel write
- "@Purchasing waiting on **confirmation**" → marks the order confirmed
- "@Purchasing please **take** a look" → routes on `take`
- "@Purchasing the **quote**d price changed" → routes to the quote handler

The `("check", "test")` approval trigger at the tail of `dispatch_command` is the
single most dangerous line in the bot: any message containing the substring
"check" routes into an approval and a workbook write.

And an unrecognised word does nothing at all and says nothing, so a typo is
indistinguishable from the bot being down.

## Requirements, stated as requirements

1. **One new pure function in `src/text_rules.py`:**

   ```python
   def parse_keyword(stripped_text: str) -> str | None:
       """The first word of a mention-stripped message, matched exactly against the
       canonical vocabulary. None when it matches nothing."""
   ```

   Pure: no Slack client, no I/O, no state. It collapses fourteen substring checks
   into one decision.

2. **Input is mention-stripped text.** `text_rules.parse_mentions` already returns
   it. ADR 0004 decision 8 is unchanged and binding: a lowercased Slack ID is
   alphanumeric and can contain `log`, `take` or `submit`.

3. **Take the first word, lowercase it, strip surrounding punctuation, match it
   exactly** against the keyword tuples in `config.py`. Two-word admin phrases
   (`remove vendor`, `add buyer`, `promote admin`) match on the first two words.

4. **Delete the `("check", "test")` approval trigger** at the tail of
   `dispatch_command`. Delete, do not narrow.

5. **The documented aliases survive.** `config.PROCESSED_KEYWORDS` keeps
   `submitted` / `submit` / `ordered` as silent backwards-compatible aliases —
   `CONTEXT.md` says these keep working so Charlie's habits do not break, and they
   are taught nowhere. Exact matching does not remove them; it stops `submitted`
   matching **inside another word**.

6. **Add the `else` branch the chain has never had:**

   ```
   🤔 I don't know the word "checkk".

   In a request thread I understand:
      approved · assign · processed · confirmed · delivered · quote · decline

   Or use the buttons on the request message above.
   ```

   In-thread on an `app_mention`; through `slack_io.deny` (ticket 12) on anything
   carrying a `response_url`.

7. **Only when the bot was actually mentioned.** The `message` event fires on every
   channel message and must stay silent. An unknown word produces a reply only on a
   real mention.

8. **`CONTEXT.md`'s Keyword entry is updated in this ticket:** the first word is
   matched exactly, and an unknown word gets a reply.

## Acceptance criteria

- [x] `text_rules.parse_keyword` exists with the signature above and is pure
- [x] "@Purchasing can you check this?" writes nothing, calls **no** lifecycle
      handler, and produces the unknown-word reply — all three asserted
- [x] "@Purchasing please take a look" and "@Purchasing waiting on confirmation"
      likewise
- [x] `@Purchasing approved` still approves, and `@Purchasing submitted` still
      marks processed — the documented aliases survive exact matching
- [x] A message mentioning a user whose Slack ID contains `log` or `submit` routes
      on the typed word, not the ID (regression on ADR 0004 decision 8)
- [x] `@Purchasing remove buyer @user` matches as a two-word keyword, and
      `@Purchasing remove` alone does not
- [x] The string `"test"` no longer appears in any approval keyword tuple, and a
      test asserts a message containing "check" writes no row
- [x] An ordinary channel message with no mention produces **no** reply — assert on
      the absence
- [x] The unknown-word reply arrives ephemerally via `deny` when the event carries
      a `response_url`, and in-thread on an `app_mention`
- [x] `CONTEXT.md`'s Keyword entry describes exact matching and the unknown-word reply
- [x] `ruff check .`, `python scripts/check_tests_first.py` and `pytest -q` all pass

## Out of scope

- Adding or removing any word from the canonical vocabulary. `CONTEXT.md` and
  §2.4 of `.scratch/lifecycle-and-buyers/spec.md` define it; this ticket changes
  how it is matched, not what it contains.
- `remove-member`, which is a new two-word keyword. Ticket 20 adds it and relies
  on this ticket's two-word matching.
- Natural-language understanding of any kind. One word, exactly.

## Comments

### 2026-09-17

- Implemented `text_rules.parse_keyword(stripped_text: str) -> str | None`:
  - Pure function that extracts the first word (or first two words for two-word admin phrases) from mention-stripped text.
  - Strips surrounding punctuation while keeping hyphens inside words.
  - Matches exactly against `config.ALL_KEYWORD_TUPLES`.
  - Substrings inside longer words (e.g. `confirmation`, `quoted`) do not match.
- Added `text_rules.format_unknown_keyword_message(word: str | None = None) -> str`:
  - Returns friendly error message with canonical request-thread vocabulary (`approved · assign · processed · confirmed · delivered · quote · decline`).
- Updated `src/config.py`:
  - Added `APPROVAL_KEYWORDS = (TRIGGER_KEYWORD,)` containing `"approved"`.
  - Added `ALL_KEYWORD_TUPLES` grouping all keyword tuples.
- Refactored `dispatch_command` in `src/app.py`:
  - Replaced substring matching with `cmd = text_rules.parse_keyword(stripped_text)`.
  - Removed dangerous `any(w in text_lower for w in ("check", "test"))` trigger.
  - Added `else:` branch routing unknown words to `format_unknown_keyword_message`.
  - Sends unknown word replies via `slack_io.deny` when `respond` is available, and `say` in-thread on `app_mention`.
  - Ordinary channel messages without mentions remain completely silent.
- Updated `CONTEXT.md`:
  - Added exact keyword matching description and unknown-word reply behavior.
- Tests:
  - Added `tests/test_16_exact_keywords.py` with 10 comprehensive tests covering all criteria.
  - Updated AST count in `tests/test_12_denials.py` to account for the new deny call site in `dispatch_command`.
  - Verified full test gate: `ruff check .` (clean), `python scripts/check_tests_first.py` (clean), `pytest -q` (235 passed, 31 skipped).

