# 55: The health screen shows all six storage paths

**Status:** ready-for-agent

**Runner:** any

**Auto-merge:** yes

**Blocked by:** 54

**Spec:** `.scratch/commands-paths-and-name/spec.md`
**Binding:** `docs/adr/0009-keywords-storage-settings-and-the-bot-name.md` decision 5, ADR 0001

## What to build

`@Purchasing health` (`ops.handle_health_status` → `admin.get_system_health` →
`admin.build_health_blocks`) checks four locations, omits `BOMS_DIR` and
`EPIF_TEMPLATE_PATH`, shows no paths, and keeps its own list. Make it read
`config.STORAGE_SETTINGS` (ticket 54) and show every setting in full. Anyone may run
it; do not add a permission check.

1. `admin.get_system_health` returns `"storage"`: a list, one entry per
   `config.STORAGE_SETTINGS` item, in that order, each
   `{"setting", "path", "kind", "source", "exists", "writable", "locked"}` where `source`
   is `".env"` when the value is non-empty and `"not set"` when empty. Reuse
   `admin.check_path_health` for the checks. Drop the four separate `workbook` /
   `epifs` / `confirmations` / `quotes` keys.
2. `admin.build_health_blocks` renders one line per entry:
   `• *<SETTING>* — <status icon + word> — <source>` then the path on the next line in
   code format, or `_not set_` when empty. Status words stay as today (`✅ Ready &
   Writable`, `❌ Missing`, `⚠️ Read-Only`, `⏳ Locked in Excel`) plus `⚪ Not set`.
   If the text would exceed Slack's 3 000-character section limit, split across more
   than one section block (six long OneDrive paths can approach it).

## Acceptance criteria

- [ ] **All six, from the one list.** In `tests/test_55_health_paths.py`: point five
  settings at real temp paths and leave `BOMS_DIR` empty. Build the blocks with the real
  `build_health_blocks(get_system_health())`. Assert all six setting names appear, both
  of two chosen real temp paths appear verbatim, and the `BOMS_DIR` line says `Not set`
  and `not set`. Fake only the queue status if needed.
- [ ] **Driven by the list.** Monkeypatch `config.STORAGE_SETTINGS` to add a seventh entry;
  assert it appears in the blocks. Fails if the health screen keeps its own list.
- [ ] **A missing path shows as missing, with its path.** Point `QUOTES_DIR` at a
  non-existent temp path: its line contains `Missing` and that path.
- [ ] **Long paths fit.** Six settings each set to a 300-character path: every section
  block's text is ≤ 3 000 characters and all six paths still appear.
- [ ] **Rewrite in place:**
  `tests/test_monitoring_and_queue.py::test_get_system_health_and_build_blocks` asserts
  the new `storage` shape instead of the four old keys. Same test name. (Its header-text
  assertion is left for ticket 58.)

## Gate

Run in this order, exactly as CI does. Zero failures before you push.

```
ruff check .
python scripts/check_tests_first.py
pytest -q --tb=short --durations=25
```

## Comments

