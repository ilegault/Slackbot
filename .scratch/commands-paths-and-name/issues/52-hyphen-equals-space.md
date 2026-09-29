# 52: A hyphen and a space are the same in two-word commands

**Status:** in-progress

**Runner:** any

**Auto-merge:** yes

**Blocked by:** None (can start immediately)

**Spec:** `.scratch/commands-paths-and-name/spec.md`
**Binding:** `docs/adr/0009-keywords-storage-settings-and-the-bot-name.md` decision 1, ADR 0001

## What to build

`@Purchasing remove-vendor Thorlabs` is not recognised because
`config.REMOVE_VENDOR_KEYWORDS` is `("remove vendor", "delete vendor")`, and
`ops.handle_remove_vendor` re-parses the raw text with its own regex
`(?:remove vendor|delete vendor)\s+(.+)`. Other two-word commands list both spellings
by hand. Make the rule structural instead.

1. `text_rules.parse_keyword` (pure, in the domain layer) normalises `-` and a space
   to the same thing when matching two-word phrases, so `remove-vendor`,
   `remove vendor`, `add-vendor`, `add vendor`, `blank-epif`, `blank epif`,
   `promote-admin`, `promote admin` each resolve to **one canonical keyword**. For admin
   ops the canonical form is the hyphen form (`remove-vendor`). A first token that
   itself contains a hyphen (`remove-vendor`) is split on the hyphen for matching.
2. Keyword tuples in `src/config.py` list one spelling per phrase: the hyphen form for
   admin ops, the existing form for lifecycle phrases (`package confirmed`). Remove the
   now-redundant duplicates (`"add-vendor"` next to `"add vendor"`, etc.). Keep
   `delete vendor` as the silent alias it is (it becomes `delete-vendor`).
3. Add a pure function in `src/text_rules.py` that returns the text after the matched
   keyword, whichever spelling was typed:
   `keyword_argument(stripped_text: str, keyword: str) -> str`.
   `ops.handle_add_vendor` and `ops.handle_remove_vendor` use it for the vendor name and
   drop their own regexes.
4. `blocks.get_help_message` shows `@Purchasing remove-vendor <name>` (today it says
   `remove vendor`). `blocks.build_app_home_view` and the help message each gain one
   line, verbatim: `Two-word commands work with a hyphen or a space: remove-vendor = remove vendor.`
   (the two command words in backticks).

## Acceptance criteria

- [ ] **Both spellings, every two-word keyword.** In `tests/test_52_hyphen_equals_space.py`,
  iterate over every multi-word phrase in `config.ALL_KEYWORD_TUPLES` and assert
  `parse_keyword` returns the same canonical value for the hyphen spelling and the space
  spelling, followed by an argument (`remove-vendor Thorlabs`, `remove vendor Thorlabs`).
  Iterate over the real tuples — do not hand-list phrases — so a phrase added later is
  covered.
- [ ] **Rewrite in place:** `tests/test_16_exact_keywords.py::test_parse_keyword_exists_and_is_pure`
  asserts `parse_keyword("remove vendor") == "remove-vendor"` (it asserts the space form
  today). Same test name; no other assertion in it is removed.
- [ ] **The vendor really goes.** Drive the real `app.dispatch_command` as an admin with
  `@Purchasing remove-vendor Temporary Vendor Inc` against a temp roster seeded with that
  vendor; assert the temp roster file no longer lists it. Repeat with the space spelling on
  a fresh temp roster. Repeat both for `add-vendor`, asserting the vendor is now in the
  file. Fake only the Slack client.
- [ ] **`keyword_argument` is pure and tested directly**: hyphen spelling, space spelling,
  extra spaces, and a keyword with no argument (returns `""`).
- [ ] **Help and App Home.** The help text contains `remove-vendor` and not
  `remove vendor <`; both the help text and the App Home view text contain the
  hyphen-or-space line. Build them with their real builders.

## Gate

Run in this order, exactly as CI does. Zero failures before you push.

```
ruff check .
python scripts/check_tests_first.py
pytest -q --tb=short --durations=25
```

## Comments

