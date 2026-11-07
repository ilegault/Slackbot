# 145: The Log link rule, the App Home button and the silent click

**Status:** ready-for-agent

**Runner:** any

**Auto-merge:** yes

**Blocked by:** None (can start immediately)

**Spec:** `.scratch/log-link/spec.md` (Implementation Decisions: The setting, What counts as set, Shared text in `blocks`, Read at render time, App Home, The warning, The click)
**Binding:** `docs/adr/0021-app-home-and-help-link-the-purchasing-log.md` (decisions 1–4); `docs/adr/0009-keywords-storage-settings-and-the-bot-name.md` (the six storage settings stay six); `docs/adr/0001-tests-first-and-no-muted-failures.md`
**Glossary:** `CONTEXT.md` — **Log link** (distinct from **Link** and **Item link**)

## What to build

App Home's Welcome section carries an **Open Purchasing Log** button that opens the
**Log link** in the browser. When the setting is missing or is not a web address, the
button is replaced by the sentence "The Purchasing Log link isn't set up yet. Ask an
admin." and a bad value is logged. Clicking the button is acknowledged and the bot does
nothing else. This ticket also lays down the setting, the pure rule and the two shared
strings that tickets 146 and 147 reuse.

1. **`src/config.py`** — directly after the `HEALTHCHECK_URL` line, add
   `PURCHASING_LOG_URL = os.environ.get("PURCHASING_LOG_URL", "").strip()` with a one-line
   comment naming ADR 0021. Do **not** add it to `STORAGE_SETTINGS`. In the
   "Action IDs for Block Kit elements" group, add
   `ACTION_OPEN_PURCHASING_LOG = "open_purchasing_log"`.
2. **`src/text_rules.py`** — add the public pure function
   `log_link_url(raw: str | None) -> str | None`: `None` for `None`; otherwise strip the
   ends; return the stripped text only if it starts with `http://` or `https://`
   (case-insensitive) and contains no whitespace character; else `None`. No `https://` is
   prepended (unlike `bom.normalize_link`). No logging, no `config` read — the caller
   passes the raw value. It must stay pure because App Home, help and the health screen
   must all give the same answer and it has to be testable without Slack.
3. **`src/blocks.py`** — next to the other shared text constants at the top
   (`_INTERFACE_RULE`, `_STAGE_DEFINITIONS`, …) add
   `_LOG_LINK_LABEL = "Open Purchasing Log"` and
   `_LOG_LINK_NOT_SET = "The Purchasing Log link isn't set up yet. Ask an admin."`.
   Add `import logging` and a module logger `log = logging.getLogger(__name__)`.
   Add the private helper `_log_link() -> str | None` that reads
   `config.PURCHASING_LOG_URL` **at call time** (never cached at import), passes it to
   `text_rules.log_link_url`, and when the raw value is non-empty but the rule returns
   `None` logs exactly one `log.warning(...)` whose message contains
   `PURCHASING_LOG_URL` and the words `not a web address`. An empty raw value logs
   nothing.
4. **`src/blocks.py` `build_app_home_view`** — the Welcome section (the section right
   after the "Hirst Lab Purchasing Bot" header) calls `_log_link()` once. When it returns
   a URL, the section gains
   `"accessory": {"type": "button", "text": {"type": "plain_text", "text": _LOG_LINK_LABEL, "emoji": True}, "url": <the URL>, "action_id": config.ACTION_OPEN_PURCHASING_LOG}`.
   When it returns `None`, the section has no accessory and its mrkdwn text gets
   `"\n\n" + _LOG_LINK_NOT_SET` appended after `_INTERFACE_RULE`. The existing Welcome
   wording is otherwise unchanged (including the sentence that mentions OneDrive).
5. **`src/app.py`** — beside `handle_open_nudge_settings_action`, add
   `@app.action(config.ACTION_OPEN_PURCHASING_LOG)` on
   `def handle_open_purchasing_log_action(ack, body) -> None:` which calls `ack()` and
   then at most one `log.debug(...)`. No client parameter, no post, no view update, no DM.
   Slack sends a `block_actions` payload even for a link button and shows an error
   triangle on it if the payload is not acknowledged.

## Acceptance criteria

New file `tests/test_145_log_link_app_home.py`. Set the setting only with
`monkeypatch.setattr(config, "PURCHASING_LOG_URL", ...)` — never a real `.env`. The roster
may be faked as `tests/test_22_live_roster_panel.py` fakes it; `blocks.build_app_home_view`,
`blocks._log_link` and `text_rules.log_link_url` must be the real ones.

- [ ] `test_app_home_button_opens_the_log_link` — with `https://example.sharepoint.com/:x:/r/log?e=1`, the section after the header has `accessory["type"] == "button"`, `accessory["url"]` equal to that exact string, `accessory["text"]["text"] == blocks._LOG_LINK_LABEL == "Open Purchasing Log"`, `accessory["action_id"] == config.ACTION_OPEN_PURCHASING_LOG`; with `HTTP://example.org/log` (upper-case scheme) the `url` is that string unchanged; with `"  https://example.org/log  "` the `url` is `https://example.org/log`.
- [ ] `test_app_home_not_set_shows_the_sentence_and_no_url` — parametrized over `""`, `"www.example.com/log"`, `"C:\\Users\\x\\Purchasing-Log.xlsx"`, `"https://exa mple.com"`: walking every block and every nested dict of the view finds no `"url"` key, the Welcome section has no `accessory`, and its text contains `blocks._LOG_LINK_NOT_SET`, which equals `"The Purchasing Log link isn't set up yet. Ask an admin."`.
- [ ] `test_app_home_reads_the_setting_at_render_time` — build the view with `""`, then set `https://example.org/log` and build again in the same test: the first has no `url` key anywhere, the second's Welcome `accessory["url"] == "https://example.org/log"`.
- [ ] `test_malformed_setting_warns_and_empty_does_not` — with `caplog` at `WARNING`: building the view with `www.example.com/log` produces exactly one `WARNING` record whose message contains `PURCHASING_LOG_URL`; building with `""` produces no `WARNING` record mentioning `PURCHASING_LOG_URL`.
- [ ] `test_log_link_click_is_acked_and_silent` — find the listener in `app.app._listeners` whose `ack_function is app.handle_open_purchasing_log_action` (prior art: `tests/test_62_ignore_slack_events.py`); assert `listener.matches(req=BoltRequest(body=body, mode="socket_mode"), resp=BoltResponse(status=200))` is `True` for a `block_actions` body whose `actions[0]["action_id"] == config.ACTION_OPEN_PURCHASING_LOG` and `False` for `action_id == "start_purchase_interview"` (`from slack_bolt import BoltRequest, BoltResponse`); the handler's parameters (`inspect.signature`) are exactly `ack, body`, so it has no Slack client to call; with `slack_io.tell`, `slack_io.deny` and `slack_io.alert_admins` monkeypatched to `MagicMock`s, calling `app.handle_open_purchasing_log_action(ack=ack, body=body)` with a `MagicMock` `ack` calls `ack` exactly once and none of the three mocks.
- [ ] `test_log_link_is_not_a_storage_setting` — `"PURCHASING_LOG_URL"` appears in no entry of `config.STORAGE_SETTINGS` and `len(config.STORAGE_SETTINGS) == 6`.

No existing test is deleted, skipped or marked xfail. If an existing App Home test breaks, fix the code, not the test.

## Gate

    ruff check .
    python scripts/check_tests_first.py
    python tools/type_gate.py
    pytest --tb=short -q -n auto --dist loadfile --durations=25

## Out of scope

`/purchasing-help` (ticket 146). The health screen and `docs/SETUP.md` (ticket 147).
Thread cards, buyer DMs, the DM card, nudges, the email draft. Rewording the rest of App
Home. Editing `docs/adr/`, `CONTEXT.md` or `AGENTS.md`.

## Comments

