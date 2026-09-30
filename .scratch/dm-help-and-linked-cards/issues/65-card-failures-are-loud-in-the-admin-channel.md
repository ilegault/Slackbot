# 65: A missing or failed card is reported loudly to the admin channel

**Status:** ready-for-agent

**Runner:** any

**Auto-merge:** yes

**Blocked by:** 64

**Spec:** `.scratch/dm-help-and-linked-cards/spec.md` (items 5–6)
**Binding:** `docs/adr/0010-linked-cards-and-direct-message-help.md` decision 7, `AGENTS.md` §7 ("Log both ends of every request"), ADR 0001

## What to build

When a dropped EPIF never produced a card, nothing told anyone why: `lifecycle.handle_epif_drop`
returns with only a log line on several failures. Make every failure that should have
produced a card visible in the **admin alert channel** (`config.ADMIN_ALERT_CHANNEL`), with
enough to act on.

1. `slack_io.alert_admins(client, text: str) -> bool`: posts `text` to
   `config.ADMIN_ALERT_CHANNEL` with `client.chat_postMessage`; returns `True` when posted;
   returns `False` and logs a WARNING — never raises — when the channel is unset, `client`
   is `None`, or the post raises. Do not touch `log_writer._notify_admin_alert`.
2. `text_rules.format_card_failure_alert(step: str, channel: str, thread_ts: str, file_name: str | None, error: str) -> str`
   — pure. First line `⚠️ *Purchase card problem*`, then one line each:
   `• *Step:* <step>`, `• *Channel:* <#<channel>>`, `• *Thread:* <thread_ts>`,
   `• *File:* <file_name>` (omit the line when `None`), `• *Error:* <error>`.
3. In `handle_epif_drop`, call `alert_admins(client, format_card_failure_alert(...))` for:
   an EPIF-named PDF that fails to download or parse (step `"parse the dropped EPIF"`;
   the requester DM stays); an EPIF-named PDF that raises an unexpected error (same
   step); and **any** parsed EPIF whose card post raises (step `"post the approval card"`).
   "EPIF-named" is the existing test `"epif" in file_name.lower()`; a non-EPIF PDF that
   fails to parse stays silent by design (log only).
4. In `finalize_purchase_request` `on_success`, alert when the card update raises (step
   `"update the approval card"`) and when ticket 64's fallback card post raises (step
   `"post the approval card"`). The errors stay logged at ERROR as well.
5. Each exit of `handle_epif_drop` logs one INFO line beginning `drop exit:`, ending with
   the reason exactly: `parse failed`, `parse failed (not an EPIF name, ignored)`,
   `unexpected error`, `card posted`, `card post failed`.

## Acceptance criteria

- [ ] **`alert_admins` never raises.** In `tests/test_65_loud_card_failures.py`: with the
  channel set and a working client it posts once to that channel and returns `True`; with
  the channel set to `""` it returns `False` and posts nothing; with `chat_postMessage`
  raising it returns `False` and no exception escapes (`monkeypatch.setattr(config, "ADMIN_ALERT_CHANNEL", …)`).
- [ ] **The message carries what an admin needs.** `format_card_failure_alert("post the approval card", "C1", "111.222", "EPIF_x.pdf", "boom")`
  contains each of `post the approval card`, `C1`, `111.222`, `EPIF_x.pdf`, `boom`; with
  `file_name=None` it contains no `File:` line.
- [ ] **A dropped EPIF whose card cannot be posted alerts.** Real `lifecycle.handle_epif_drop`
  with `slack_io.download` and `epif_parser.parse_epif` returning a valid parsed EPIF (copy the
  parsed dict from `tests/test_46_epif_path_dm_attaches_epif.py`'s `_valid_request`) and
  `chat_postMessage` raising for the card: exactly one `chat_postMessage` to the alert channel
  whose text contains the file name and the exception text, and `caplog` has an INFO record
  ending `drop exit: card post failed`. A successful drop logs `drop exit: card posted` and
  posts **nothing** to the alert channel (absence asserted).
- [ ] **A non-EPIF PDF that will not parse stays silent.** `notes.pdf` whose parse raises
  `RuntimeError`: no message to the alert channel, and an INFO record ending
  `drop exit: parse failed (not an EPIF name, ignored)`. `EPIF_notes.pdf` with the same
  error: one alert message and an INFO record ending `drop exit: parse failed`.
- [ ] **A failed card update at approval alerts and does not undo the approval.** Real
  `finalize_purchase_request` (fixtures as ticket 64's test) with an existing card and
  `chat_update` raising: one alert message containing `update the approval card`, the row
  recorder still called once, the buyer's DM still sent.

**Tests may fake:** the Slack client, `slack_io.download`, `epif_parser.parse_epif` (its output
is the input under test, not the code under test). **Must be real:** `handle_epif_drop`,
`finalize_purchase_request`, `alert_admins`, `format_card_failure_alert`.

## Gate

Run in this order, exactly as CI does (`.github/workflows/tests.yml`). Zero failures before
you push. If `tools/type_gate.py` exists on `master` when you start, also run
`python tools/type_gate.py` after `check_tests_first.py`, and use
`pytest --tb=short -q -n auto --dist loadfile` in place of the last line.

```
ruff check .
python scripts/check_tests_first.py
pytest -q --tb=short --durations=25
```

## Comments

