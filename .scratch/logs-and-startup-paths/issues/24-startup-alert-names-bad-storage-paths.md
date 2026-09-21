# 24: The startup alert names bad storage paths

**What to build:** When the bot boots with a storage path that is unset, still
holds a template placeholder, is the wrong kind of thing or doesn't exist, the
startup alert in the alert channel turns orange. It lists each bad setting with
its value and the reason. The bot still boots. A healthy boot looks exactly as it
does today. The setup guide stops showing a placeholder that looks like the bot
fills it in.

**Blocked by:** None (can start immediately)

**Status:** done

**Read before starting:** `.scratch/logs-and-startup-paths/spec.md`, Part B
(decisions B1–B3) and the Part B testing decisions. Also
`docs/adr/0001-tests-first-and-no-muted-failures.md` (binding). Copy reply
strings from the spec exactly.

## Why

On 2026-09-21 the server's `.env` still held `C:\Users\USERNAME\…` for all four
storage paths. The bot posted "🟢 P-Bot Online & Ready" and nobody noticed until
a real approval failed with `FileNotFoundError`.

## Acceptance criteria

- [x] `path_validator` gains a pure check that reads `config` at call time and returns one problem per bad path (setting name, value, reason), or an empty list. It covers `PURCHASING_LOG_PATH` (must be a file), `EPIFS_DIR`, `CONFIRMATIONS_DIR` and `QUOTES_DIR` (must be folders), in that order
- [x] Reasons are checked in order and only the first match is reported: `not set` → `still contains a template placeholder` (any component exactly `USERNAME`, or containing `<` or `>`, split on both `\` and `/`) → `exists but is not a file` / `exists but is not a folder` → `does not exist`
- [x] `send_startup_alert` logs each problem at ERROR **before** the early return for no channel or no client, so problems are recorded even when no alert can be sent
- [x] If there are no problems, the posted alert is unchanged. If there are any, the header becomes `🟠 P-Bot Online — storage paths need attention`, the problems section and the closing line from B2 come straight after the header-and-fields section, and the fallback `text` carries the same lines
- [x] Bad paths never stop the bot from booting. `main()` is unchanged. The interactive prompt functions in `path_validator` are unchanged
- [x] In `docs/SETUP.md`, every `C:\Users\USERNAME\…` becomes `C:\Users\<your-windows-account>\…`, with the sentence from B3 directly under the `.env` block. The `example` strings in `STORAGE_PATHS` get the same substitution
- [x] `tests/test_24_startup_storage_check.py` covers every case in the spec's Part B testing list. It uses real files and folders in `tmp_path`, a `MagicMock` client and `caplog` for the no-channel case, and asserts on the blocks and text that were posted
- [x] `ruff check .`, `python scripts/check_tests_first.py` and `pytest -q` all pass

## Out of scope

- Refusing to boot, pre-checking approvals, or changing `@Purchasing health`
- `TEMPLATE_DIR`, and expanding `%USERNAME%` or `~`
- The mislabelled `Log Path:` fallback line. Leave it alone
- Fixing the production `.env`. That's ticket 25

## Comments

### 2026-09-21 — Implementation summary
- Implemented `check_storage_paths()` in `src/path_validator.py` as a pure function checking `PURCHASING_LOG_PATH`, `EPIFS_DIR`, `CONFIRMATIONS_DIR`, and `QUOTES_DIR` in order against the required reasons (`not set`, `still contains a template placeholder`, wrong kind `exists but is not a file` / `exists but is not a folder`, and `does not exist`).
- Updated `src/heartbeat.py:send_startup_alert()` to check storage paths and log problems at ERROR before early returns. If problems exist, the header turns orange (`🟠 P-Bot Online — storage paths need attention`), and the problems list with the warning message is inserted both into the Block Kit blocks and the fallback notification text.
- Updated `docs/SETUP.md` and `STORAGE_PATHS` in `src/path_validator.py` to replace `USERNAME` with `<your-windows-account>` and included the explanatory note under `.env`.
- Added test suite in `tests/test_24_startup_storage_check.py` covering all pure path validation scenarios, alert formatting, fallback text, and ERROR logging when the alert channel is missing.
- Verified all gate checks pass cleanly: ruff, check_tests_first, and pytest suite (299 passed).
