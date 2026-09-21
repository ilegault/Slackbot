# 23: Full logs from Slack, in the alert channel only

**What to build:** An admin in the alert channel asks for logs and gets exactly
what they asked for. `@Purchasing logs 500` returns 500 lines. It posts inline
if it fits and as a file in the thread if it doesn't, and nothing is dropped
without the reply saying so. `@Purchasing logs all` and
`@Purchasing logs rejections` send the whole current `p_bot.log` or
`rejections.log` as a file. Asked for anywhere else, the bot sends no log
content and replies with a link to the alert channel.

**Blocked by:** None (can start immediately)

**Status:** done

**Read before starting:** `.scratch/logs-and-startup-paths/spec.md`, Part A
(decisions A1–A8) and the Part A testing decisions. Also `CONTEXT.md` (**Admin**,
**Keyword**, **Alert channel**) and
`docs/adr/0001-tests-first-and-no-muted-failures.md` (binding). The spec is the
source of truth for every reply string and filename. Copy them from it and don't
paraphrase.

## Why

Today `logs [n]` clamps to 100 lines without saying so, then trims to the last
2,800 characters, which is about fifteen lines. The reply is still headed "Last
100 lines". `rejections.log` can't be read remotely at all. Isaac has to walk to
the server to see what went wrong.

## Acceptance criteria

- [x] Every `logs`/`log` form checks, in this order: caller is an admin (existing padlock reply otherwise), `ADMIN_ALERT_CHANNEL` is set ("unavailable" reply otherwise), and the message is in the alert channel (a reply containing `<#ALERT_CHANNEL>` otherwise). When any check fails, no log text is posted and `files_upload_v2` is not called
- [x] The word after the keyword chooses the form: nothing → 30 lines; *n* → *n* lines, with no upper cap and values below 1 raised to 1; `all` and `rejections` match case-insensitively; anything else gets the unknown-option reply and nothing more
- [x] A masked tail of ≤ 2,800 characters posts inline under a header that gives the actual line count *k*. A longer one uploads as `p_bot_last_{k}_lines.log`. The 100-line clamp and the 2,800-character trim are both gone
- [x] `logs all` uploads `p_bot.log` and `logs rejections` uploads `rejections.log`. Only the current file is sent, not the rotated copies
- [x] Uploads go through `files_upload_v2` with `content=` set to the masked text, in the message's channel and thread, with `title` equal to the filename. There's no legacy `files_upload` fallback
- [x] All three forms mask text through a single function. `get_tail_logs` keeps its signature, minus the clamp
- [x] A missing file, a read error and an upload error each get the reply the spec gives in A7, posted in the thread, and none of them uploads anything
- [x] The help source used by App Home and the help reply lists the three `logs` lines from A8. `CONTEXT.md` **Alert channel** gains the one sentence from A8
- [x] `tests/test_23_logs_from_slack.py` covers every case in the spec's Part A testing list. It drives `app.dispatch_command` with real files in `tmp_path` and asserts on the reply text or the upload's channel, thread, filename and content. It never asserts on which internal function was called
- [x] `test_dispatch_logs_restricted_to_admins` changes on purpose, and only by setting `config.ADMIN_ALERT_CHANNEL = "C123"`. Its assertion is untouched, and the change is recorded under `## Comments`
- [x] `test_get_tail_logs_and_token_masking` passes unchanged
- [x] `ruff check .`, `python scripts/check_tests_first.py` and `pytest -q` all pass

## Out of scope

- Rotated logs (`p_bot.log.1` … `.5`)
- A separate logs-channel setting. The alert channel is the logs channel
- Coding around `missing_scope`. If an upload fails for lack of `files:write`,
  mark this ticket `blocked` and say so. Adding the scope is a human task
- Anything in Part B (ticket 24)

## Comments

### 2026-09-21

- Implemented full log access from Slack restricted to the alert channel:
  - Added `admin.mask_sensitive_tokens(text: str)` as unified token and webhook URL masking function.
  - Added `admin.read_log_file(path: str, n: Optional[int] = None) -> Tuple[str, int]` supporting tail and whole-file reads, removing arbitrary 100-line clamp.
  - Updated `admin.get_tail_logs` to use `read_log_file` without the 100 clamp, maintaining backward compatibility.
  - Updated `ops.handle_logs` with 3-tier gate: admin check -> `ADMIN_ALERT_CHANNEL` configured -> message channel matches alert channel.
  - Implemented form selection: default 30 lines, `n` lines (>= 1, no cap), `all` (`p_bot.log`), `rejections` (`rejections.log`), and unknown option reply.
  - Delivery mode: inline when masked text <= 2,800 chars with actual line count `k` in header; uploaded via `client.files_upload_v2` when > 2,800 chars or whole file.
  - Handled errors: missing file, read failure, upload failure without uploading unmasked content or fallback.
  - Updated `_ADMIN_COMMANDS` in `src/blocks.py` with 3 logs commands, and updated `CONTEXT.md` **Alert channel** definition.
- Tests:
  - Added `tests/test_23_logs_from_slack.py` covering all 12 spec cases with 14 unit tests driving `app.dispatch_command`.
  - Updated `test_dispatch_logs_restricted_to_admins` in `tests/test_monitoring_and_queue.py` on purpose to set `config.ADMIN_ALERT_CHANNEL = "C123"` so admin call in channel `C123` succeeds under the new alert channel check; assertion untouched.
  - Verified `test_get_tail_logs_and_token_masking` passes unchanged.
  - Full local gate passed cleanly:
    - `ruff check .`: 0 errors
    - `python scripts/check_tests_first.py`: OK
    - `pytest -q`: 288 passed, 31 skipped in 290s.
