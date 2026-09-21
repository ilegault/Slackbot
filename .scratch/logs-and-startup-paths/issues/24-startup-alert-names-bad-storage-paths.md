# 24: The startup alert names bad storage paths

**What to build:** When the bot boots with a storage path that is unset, still
holds a template placeholder, is the wrong kind of thing or doesn't exist, the
startup alert in the alert channel turns orange. It lists each bad setting with
its value and the reason. The bot still boots. A healthy boot looks exactly as it
does today. The setup guide stops showing a placeholder that looks like the bot
fills it in.

**Blocked by:** None (can start immediately)

**Status:** ready-for-agent

**Read before starting:** `.scratch/logs-and-startup-paths/spec.md`, Part B
(decisions B1–B3) and the Part B testing decisions. Also
`docs/adr/0001-tests-first-and-no-muted-failures.md` (binding). Copy reply
strings from the spec exactly.

## Why

On 2026-09-21 the server's `.env` still held `C:\Users\USERNAME\…` for all four
storage paths. The bot posted "🟢 P-Bot Online & Ready" and nobody noticed until
a real approval failed with `FileNotFoundError`.

## Acceptance criteria

- [ ] `path_validator` gains a pure check that reads `config` at call time and returns one problem per bad path (setting name, value, reason), or an empty list. It covers `PURCHASING_LOG_PATH` (must be a file), `EPIFS_DIR`, `CONFIRMATIONS_DIR` and `QUOTES_DIR` (must be folders), in that order
- [ ] Reasons are checked in order and only the first match is reported: `not set` → `still contains a template placeholder` (any component exactly `USERNAME`, or containing `<` or `>`, split on both `\` and `/`) → `exists but is not a file` / `exists but is not a folder` → `does not exist`
- [ ] `send_startup_alert` logs each problem at ERROR **before** the early return for no channel or no client, so problems are recorded even when no alert can be sent
- [ ] If there are no problems, the posted alert is unchanged. If there are any, the header becomes `🟠 P-Bot Online — storage paths need attention`, the problems section and the closing line from B2 come straight after the header-and-fields section, and the fallback `text` carries the same lines
- [ ] Bad paths never stop the bot from booting. `main()` is unchanged. The interactive prompt functions in `path_validator` are unchanged
- [ ] In `docs/SETUP.md`, every `C:\Users\USERNAME\…` becomes `C:\Users\<your-windows-account>\…`, with the sentence from B3 directly under the `.env` block. The `example` strings in `STORAGE_PATHS` get the same substitution
- [ ] `tests/test_24_startup_storage_check.py` covers every case in the spec's Part B testing list. It uses real files and folders in `tmp_path`, a `MagicMock` client and `caplog` for the no-channel case, and asserts on the blocks and text that were posted
- [ ] `ruff check .`, `python scripts/check_tests_first.py` and `pytest -q` all pass

## Out of scope

- Refusing to boot, pre-checking approvals, or changing `@Purchasing health`
- `TEMPLATE_DIR`, and expanding `%USERNAME%` or `~`
- The mislabelled `Log Path:` fallback line. Leave it alone
- Fixing the production `.env`. That's ticket 25

## Comments
