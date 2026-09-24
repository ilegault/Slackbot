# 35: Warn once when a typed vendor is really a listed one

**Status:** ready-for-agent

**Blocked by:** 34

Spec: Implementation Decision 1 (near-miss check). Binding: ADR 0007 decision 3.

**What to build:** A requester picks "None of these — this will be an EPIF order" and
types `fisher scientific`. Screen 1 stops them once with *"Did you mean Fisher
Scientific? Pick it from the list — it's a Workday vendor. Submit again to keep this as
an EPIF order."* If they submit again with the same name, the request goes ahead on the
EPIF path. A vendor that isn't close to any listed one is never stopped.

- [ ] Matching is done by a pure function in `interview` that takes the typed name and the listed names and returns a listed name or none. It is pure (no Slack, no roster read) so it can be tested on plain strings.
- [ ] It matches if the names are equal after lowercasing, removing punctuation and whitespace, and dropping trailing `inc`, `llc`, `ltd`, `co`, `corp`, `corporation` or `company`. Otherwise it matches only on a `difflib.SequenceMatcher` ratio ≥ 0.85.
- [ ] The first submit returns a field error on the custom-vendor block naming the listed vendor, and records the typed name in the view's private metadata.
- [ ] A second submit with the same typed name proceeds on the EPIF path. A different typed name is checked afresh.
- [ ] Scenario tests through the real Screen 1 view handler: `fisher scientific`, `Fisher Scientific, Inc.` and `Fisher Scientfic` are each warned once, then pass on resubmit. `Winford` is never warned.
- [ ] Full gate green (all four commands).

## Comments
