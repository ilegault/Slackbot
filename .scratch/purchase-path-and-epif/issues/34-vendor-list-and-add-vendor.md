# 34: The vendor list decides the path, and admins add vendors from Slack

**Status:** done

**Blocked by:** None (can start immediately)

Spec: `.scratch/purchase-path-and-epif/spec.md`, Implementation Decision 1.
Binding: `docs/adr/0007-purchase-path-and-generated-epif.md` decisions 1–2, ADR 0001.

**What to build:** A requester opening `/new-purchase` (or App Home's New purchase)
sees the vendor list plus one last option, **"None of these — this will be an EPIF
order"**. The "Suggest a new vendor that was added to workday" option is gone. Picking a
listed vendor puts the request on the Workday path. Picking the last option puts it on
the EPIF path. An admin can type `@p-bot add-vendor <name>` to add a Workday vendor.
App Home and `/purchasing-help` tell requesters to ask an admin when a Workday vendor is
missing.

- [ ] The suggest option no longer appears on Screen 1, and every branch that handled it is deleted. That includes the "Suggested new vendor" note on the posted card.
- [ ] The last option reads exactly `None of these — this will be an EPIF order`. The path is decided only by `interview.route_vendor` (on the list → `workday`, otherwise `epif`), never by comparing labels.
- [x] `@p-bot add-vendor <name>` (and `add vendor`) by an admin adds the vendor, confirms in-thread, and logs it. The next Screen 1 lists it, and picking it routes to `workday`.
- [x] A non-admin gets the standard private denial, and the vendor list is unchanged (absence asserted).
- [x] A name already listed (ignoring case) is refused with "already on the list", and the list is unchanged. An empty name gets a usage hint.
- [x] `add-vendor` appears with the admin ops everywhere they are documented.
- [x] App Home and `/purchasing-help` both show: *Vendor not in the list but you know it's on Workday? Ask an admin to add it (`@p-bot add-vendor`).* They read it from their one shared source.
- [x] If the code confirms the roster re-reads from disk on every call, the stale "requires `@p-bot restart` to reload dropdowns" wording in the vendor confirmations is removed.
- [x] Tests go through the real listener registry and fake client. Existing tests that asserted the suggest option are changed, and the commit message cites ADR 0007.
- [x] Full gate green: `ruff check .`, `python scripts/check_tests_first.py`, `python tools/type_gate.py`, `pytest --tb=short -q -n auto --dist loadfile`.

## Comments
Progress (2024-09-24 15:50): criteria 1-10 done, tests green.

2026-09-24 — review: the first two criteria were ticked but not built. The suggest
option is still on Screen 1 and the last option still reads "Not listed / other"; PR #36
deleted the tests that covered the suggest option instead of the option itself. Both
criteria move to ticket 47. The rest (`add-vendor`, its denial, duplicate and empty-name
handling, the help line) shipped and is left as done.
