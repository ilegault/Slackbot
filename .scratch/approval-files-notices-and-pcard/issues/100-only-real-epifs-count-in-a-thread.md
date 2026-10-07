# 100: Only real EPIFs count when a thread is searched

**Status:** ready-for-agent

**Claimed-by:** box

**Runner:** any

**Auto-merge:** yes

**Blocked by:** None (can start immediately)

**Spec:** `.scratch/approval-files-notices-and-pcard/spec.md` (Part A, stories 8–11 groundwork)
**Binding:** `docs/adr/0015-approval-reads-the-card-or-the-threads-files-by-role.md` (decisions 2 and 4); ADR 0012 decision 2; ADR 0001
**Glossary:** `CONTEXT.md` — **EPIF**, **Quote**, **Thread files at approval**

## What to build

`slack_io.find_epif_in_thread` returns the newest file ending `.pdf` in the thread. It doesn't
check who posted the file or whether it is a form. So `@Purchasing approved` in a thread where
someone dropped a quote tries to read the quote as an EPIF and fails. Replace that rule with a
pure classifier.

1. `src/epif_parser.py` — new **pure** function `is_epif_form(fields: dict) -> bool`. It is
   true when both `"Amount of Purchase"` and `"Vendor"` are keys of `fields` (the field
   names `parse_epif` already reads).
2. `src/slack_io.py` — new function `bot_user_id(client) -> str | None`. Move the cached
   `client.auth_test()` lookup from `src/app.py` `get_bot_user_id` into it. `get_bot_user_id`
   keeps its signature, keeps the `context` shortcut, and otherwise returns
   `slack_io.bot_user_id(client)`.
3. `src/slack_io.py` — new **pure** function (no client; it must stay pure so every
   row of the classification table can be tested on plain dicts):

       classify_thread_files(messages: list[dict], bot_user_id: str | None,
                             read_fields: Callable[[dict], dict]) -> dict[str, list[dict]]

   It returns the keys `"epifs"`, `"boms"`, `"quotes"`, `"flattened_epifs"`. Each value is
   oldest-first and holds dicts `{"file": <file obj>, "user": <poster id>, "ts": <message ts>}`.
   Rules, in this order, per file of each message:
   - Skip the message if its `user == bot_user_id` or it has a `bot_id`.
   - Skip the message if it is an `@Purchasing quote` command: its text contains
     `<@{bot_user_id}>`, and after removing that mention, the stripped lowercased text starts
     with an entry of `config.QUOTE_KEYWORDS`.
   - Name ends `.xlsx` or `.csv` (case-insensitive) → `"boms"`.
   - Name ends `.pdf`: `fields = read_fields(file)`. If `epif_parser.is_epif_form(fields)` →
     `"epifs"`. Otherwise, if `fields` is empty and `"epif"` is in the lowercased name →
     `"flattened_epifs"`. Otherwise → `"quotes"`.
   - Anything else (images, etc.) is skipped.
4. `slack_io.find_epif_in_thread(client, channel, thread_ts)` keeps its signature and return
   shape `(file_obj, poster)`. It fetches replies, calls `classify_thread_files` with
   `bot_user_id(client)` and a `read_fields` that downloads with `download` and returns
   `epif_parser.read_fields(bytes)`, or `{}` on `FlattenedPdfError`. It returns the newest
   `"epifs"` entry, else the newest `"flattened_epifs"` entry (so the existing
   flattened-PDF error still reaches the uploader), else `(None, None)`.

## Acceptance criteria

- [ ] `tests/test_100_thread_file_classifier.py` tests `is_epif_form` with the field names from the real fixture `tests/fixtures/EPIF_TEMPLATE_HIRST.pdf` (read with `epif_parser.read_fields`) → True, and with `{}` and `{"Total": "1"}` → False.
- [ ] The same file tests `classify_thread_files` on plain message dicts and a fake `read_fields`, one test per rule: a bot-posted PDF (by `user` and by `bot_id`) is skipped; a person's EPIF → `epifs`; a person's form-less PDF named `Quote 27732.pdf` → `quotes`; a form-less `Smith_EPIF.pdf` → `flattened_epifs`; `bom.xlsx` and `BOM.CSV` → `boms`; a `.png` is skipped; a PDF on a `<@BOT> quote` message is skipped; order is oldest-first.
- [ ] Driving `lifecycle.handle_epif_processing` from the `@Purchasing approved` keyword (no `card_ts`, no `posted_payload`), with a fake client whose thread holds only a person's form-less `Quote.pdf` (a real blank PDF built with `pypdf.PdfWriter`), posts the bare-thread approval reply ("No EPIF in this thread…", as `tests/test_40_bare_thread_approval.py::test_bare_thread_approval_posts_reply_and_card` asserts). No text starting `Error processing` is posted.
- [ ] A thread holding a person's EPIF followed by a newer person's quote PDF approves the EPIF. Assert the row's vendor comes from the EPIF.
- [ ] `app.get_bot_user_id` still passes its existing tests. `slack_io.bot_user_id` calls `auth_test` once across two calls (cached).

May fake: the Slack client and file downloads (return fixture bytes). Must be real: `classify_thread_files`, `is_epif_form`, `epif_parser.read_fields` on real PDF bytes in criteria 1, 3 and 4.

## Gate

Run all four, in CI's order, and all must pass:

    ruff check .
    python scripts/check_tests_first.py
    python tools/type_gate.py
    pytest --tb=short -q -n auto --dist loadfile

Tests need `SLACK_BOT_TOKEN=xoxb-test-not-a-real-token`, `SLACK_APP_TOKEN=xapp-test-not-a-real-token` and `PYTHONUTF8=1` in the environment, as `.github/workflows/tests.yml` sets.

## Comments
