# 35: Warn once when a typed vendor is really a listed one

**Status:** done

**Blocked by:** 34

Spec: Implementation Decision 1 (near-miss check). Binding: ADR 0007 decision 3.

**What to build:** A requester picks "None of these — this will be an EPIF order" and
types `fisher scientific`. Screen 1 stops them once with *"Did you mean Fisher
Scientific? Pick it from the list — it's a Workday vendor. Submit again to keep this as
an EPIF order."* If they submit again with the same name, the request goes ahead on the
EPIF path. A vendor that isn't close to any listed one is never stopped.

- [x] Matching is done by a pure function in `interview` that takes the typed name and the listed names and returns a listed name or none. It is pure (no Slack, no roster read) so it can be tested on plain strings.
- [x] It matches if the names are equal after lowercasing, removing punctuation and whitespace, and dropping trailing `inc`, `llc`, `ltd`, `co`, `corp`, `corporation` or `company`. Otherwise it matches only on a `difflib.SequenceMatcher` ratio ≥ 0.85.
- [x] The first submit returns a field error on the custom-vendor block naming the listed vendor, and records the typed name in the view's private metadata. *(Shown as a warning block directly under the custom-vendor field, not a Slack field error — see Comments.)*
- [x] A second submit with the same typed name proceeds on the EPIF path. A different typed name is checked afresh.
- [x] Scenario tests through the real Screen 1 view handler: `fisher scientific`, `Fisher Scientific, Inc.` and `Fisher Scientfic` are each warned once, then pass on resubmit. `Winford` is never warned.
- [x] Full gate green (all four commands).

## Comments

**2026-09-24 — done (implemented in PR #38, gaps closed in review).**
Built: `interview.check_near_miss_vendor` (pure; normalises case, punctuation,
whitespace and trailing company suffixes, then `difflib` ratio ≥
`config.NEAR_MISS_VENDOR_RATIO`); Screen 1 handler warns once per typed name and
records it as `warned_vendor` in private metadata; `blocks.with_near_miss_warning`
places a single warning under the vendor-name field.

Deviation from criterion 3: Slack's `errors` response cannot change
`private_metadata`, so a field error and the stored name can't travel in one
response. The warning is sent in an `update` response as a block directly under the
field instead. The ticket asked for both; only this form is possible in one response.

Review fixes: the warning was pinned to the top of the form and never replaced, so
typing a name close to a second vendor still showed "Did you mean <first>?"; now
replaced each time. The screen-level tests only checked that the form moved on, which
the warning also does; they now assert the Screen 2 view on the EPIF path with no
warning, round-tripping the view the bot actually returns
(`tests/test_35_warn_near_miss_vendor.py`).
