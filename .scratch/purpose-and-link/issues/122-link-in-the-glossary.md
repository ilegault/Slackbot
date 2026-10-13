# 122: Link in the glossary

**Status:** done

**Runner:** any

**Auto-merge:** no

**Blocked by:** 120, 121

**Spec:** `.scratch/purpose-and-link/spec.md` (Part C, story 11)
**Binding:** `docs/adr/0007-purchase-path-and-generated-epif.md`
**Glossary:** `CONTEXT.md` — **Link** (new), **Filled EPIF**, **Quote**

## What to build

`CONTEXT.md` defines **Link**, so "where does the link live" has one answer. This ticket
changes `CONTEXT.md`, so it is held for review (`Auto-merge: no`), and nothing may be
blocked by it.

Add one entry to `CONTEXT.md`, directly after the **Quote** entry (the paragraph starting
`**Quote** — a vendor's price document`) and before **Thread files at approval**, with one
blank line on each side. Its text, exactly:

    **Link** — the product page or quote URL for a request, given in Screen 2's
    Product Page / Quote Link field. Kept apart from Purpose on the thread card, the DM
    card and the log (its own column). Only on a **Filled EPIF** is it added to the end of
    Purpose, as a last line `Link: <url>`, and not if the exact URL is already in Purpose.
    Left blank, the first URL in Purpose is used. Reading any EPIF, a Purpose whose last
    line is only a URL (with or without `Link:`) gives that URL back as the link.

(Write it as a normal paragraph, without the four-space indent.)

## Acceptance criteria

- [x] `CONTEXT.md` contains the paragraph above, word for word, starting `**Link** — the product page or quote URL for a request`. (by hand)
- [x] That paragraph sits between the **Quote** paragraph and the **Thread files at approval** paragraph. (by hand)
- [x] `git diff master -- CONTEXT.md` shows only added lines: no other line of `CONTEXT.md` changes. (by hand)
- [x] No file other than `CONTEXT.md` and this ticket file changes. (by hand)

May fake: nothing. No new test is needed for a glossary entry. The existing suite, `tests/test_59_readme_and_docs.py` included, must pass unchanged.

## Gate

Run all four, in CI's order, and all must pass:

    ruff check .
    python scripts/check_tests_first.py
    python tools/type_gate.py
    pytest --tb=short -q -n auto --dist loadfile

Tests need `SLACK_BOT_TOKEN=xoxb-test-not-a-real-token`, `SLACK_APP_TOKEN=xapp-test-not-a-real-token` and `PYTHONUTF8=1` in the environment, as `.github/workflows/tests.yml` sets.

## Comments
2026-10-13: Added the **Link** entry to `CONTEXT.md` between **Quote** and **Thread files at approval**, word for word. 7 added lines, none removed; no other file changed except this ticket. Gate green locally: ruff, tests-first, type_gate (95/95), pytest unchanged. Held for review (`Auto-merge: no`).
