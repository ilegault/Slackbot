# 53: "Did you mean …?" for an unknown word

**Status:** done

**Runner:** any

**Auto-merge:** yes

**Blocked by:** 51, 52

**Spec:** `.scratch/commands-paths-and-name/spec.md`
**Binding:** `docs/adr/0009-keywords-storage-settings-and-the-bot-name.md` decision 3, ADR 0001

## What to build

After 51, an unknown word gets `text_rules.format_unknown_keyword_message` in the
thread. That text lists lifecycle words only and does not help with a typo. Make the
reply teach the right command, publicly, in the thread (so later readers learn too).

1. Add to `src/config.py`: `KEYWORD_SUGGESTION_CUTOFF = 0.75` and a tuple
   `ADMIN_ONLY_KEYWORDS` naming the canonical admin keywords (the ones the help text
   marks *(Admin Only)*: `promote-admin`, `add-approver`, `remove-approver`,
   `add-buyer`, `remove-buyer`, `remove-member`, `add-vendor`, `remove-vendor`,
   `update`, `restart`, `logs`).
2. Add a pure function to `src/text_rules.py`:
   `closest_keyword(word: str, vocabulary: Sequence[str]) -> str | None` using
   `difflib.get_close_matches(word, vocabulary, n=1, cutoff=config.KEYWORD_SUGGESTION_CUTOFF)`.
   The vocabulary is every canonical keyword from `config.ALL_KEYWORD_TUPLES` (hyphen
   form, per 52). The unknown word is normalised the same way `parse_keyword` does
   (hyphen = space), and the first two tokens are tried as a phrase before the first
   token alone, so `remve vendor` and `remve-vendor` both suggest `remove-vendor`.
3. Rewrite `format_unknown_keyword_message(word, suggestion)`:
   - with a suggestion: `🤔 I don't know "<word>". Did you mean \`@Purchasing <suggestion>\`?`
     followed by ` _(admin only)_` when the suggestion is in `ADMIN_ONLY_KEYWORDS`;
   - without: `🤔 I don't know "<word>". Send \`@Purchasing help\` for the list of commands.`
4. `dispatch_command`'s unknown-word branch passes the suggestion in.

## Acceptance criteria

- [x] **`closest_keyword` is tested directly** in `tests/test_53_did_you_mean.py`:
  `remve-vendor` → `remove-vendor`; `remve vendor` → `remove-vendor`; `aprooved` →
  `approved`; `flurb` → `None`; `banana` → `None`. Use the real vocabulary from
  `config`, not a test list.
- [x] **The reply through the real listener.** Invoke the real `app_mention` listener
  (as ticket 51's test does) with `<@BOT> remve-vendor Thorlabs`: one `say`, in the
  thread, text contains `@Purchasing remove-vendor` and `admin only`. And the temp
  roster still lists `Thorlabs` if seeded with it (assert nothing was removed).
- [x] **No close match.** `<@BOT> flurb`: one `say` containing `@Purchasing help` and not
  containing `Did you mean`.
- [x] **A lifecycle suggestion is not marked admin-only**: `aprooved` → the reply
  contains `@Purchasing approved` and not `admin only`.
- [x] The cutoff lives only in `config.KEYWORD_SUGGESTION_CUTOFF`; no numeric literal
  cutoff in `text_rules.py`.

## Gate

Run in this order, exactly as CI does. Zero failures before you push.

```
ruff check .
python scripts/check_tests_first.py
pytest -q --tb=short --durations=25
```

## Comments

### Landed — 2026-09-29
- Added `KEYWORD_SUGGESTION_CUTOFF = 0.75`, `ADMIN_ONLY_KEYWORDS`, and `CANONICAL_KEYWORDS` to `src/config.py`.
- Implemented pure `closest_keyword` and rewritten `format_unknown_keyword_message` in `src/text_rules.py` with difflib matching and admin-only marking.
- Updated `src/app.py` `dispatch_command` unknown word branch to resolve closest keyword suggestion and pass it to `format_unknown_keyword_message`.
- Updated `tests/test_16_exact_keywords.py` assertions for the new unknown-word reply format.
- Added comprehensive unit and listener integration tests in `tests/test_53_did_you_mean.py` verifying criteria 1–5.
