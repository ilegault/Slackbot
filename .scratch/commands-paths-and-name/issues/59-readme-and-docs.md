# 59: README and docs describe the current bot

**Status:** in-progress

**Runner:** any

**Auto-merge:** yes

**Blocked by:** 52

**Spec:** `.scratch/commands-paths-and-name/spec.md`
**Binding:** `docs/adr/0009-keywords-storage-settings-and-the-bot-name.md` decision 8, ADR 0001

## What to build

`README.md` is out of date: it says `@p-bot`, teaches `claim` (now **assign**) and
`submitted` (now **processed**), and lists no admin roster or vendor commands. Rewrite
it for the current bot and rename the bot throughout `docs/` — except `docs/adr/`,
which is a historical record and is not edited.

1. `README.md`: title `Purchasing bot (Hirst Lab)`. Command list uses `@Purchasing` and
   the canonical words from `CONTEXT.md`: `approved`, `assign`, `processed`,
   `confirmed`, `delivered`, `quote`, `decline`, `help`, `health`/`status`, `queue`,
   `logs [n|all|rejections]`, `update`, `restart`, `promote-admin`, `add-approver`,
   `remove-approver`, `add-buyer`, `remove-buyer`, `remove-member`, `add-vendor`,
   `remove-vendor`, plus the slash commands registered in `src/app.py`
   (`/new-purchase`, `/purchasing-help`, `/blank-template`, `/roster-list`,
   `/roster-set-name`). One line: two-word commands work with a hyphen or a space. List
   the six storage settings from `config.STORAGE_SETTINGS` (after ticket 54 — if 54 has
   not landed, list the six names from `CONTEXT.md` **Storage setting**).
2. `docs/*.md` (top level of `docs/`, and `docs/agents/`): "P-Bot" → "the Purchasing
   bot", `@p-bot` → `@Purchasing`. File names (`p_bot.log`, `p_bot.spec`, the exe) stay.

This is docs-only; declare `[no-test-needed: docs only]` if the tests-first check asks.

## Acceptance criteria

- [ ] `README.md` contains none of `@p-bot`, `P-Bot`, `claim`, `submitted`
  (case-insensitive, whole words).
- [ ] Every slash command registered with `@app.command(...)` in `src/app.py` appears in
  `README.md` (check by reading the decorators, not a hand list).
- [ ] Every canonical admin keyword in `config.ALL_KEYWORD_TUPLES` that the help text
  marks *(Admin Only)* appears in `README.md` in its hyphen form.
- [ ] No file under `docs/` outside `docs/adr/` contains `@p-bot` or `P-Bot`; nothing under
  `docs/adr/` is modified (`git diff --stat master -- docs/adr` is empty).
- [ ] `p_bot.log` and `p_bot.spec` are still named where the docs describe the build and logs.

## Gate

Run in this order, exactly as CI does. Zero failures before you push.

```
ruff check .
python scripts/check_tests_first.py
pytest -q --tb=short --durations=25
```

## Comments

