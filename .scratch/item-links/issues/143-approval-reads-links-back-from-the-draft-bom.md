# 143: Approval reads the item links back from the draft BOM

**Status:** in-progress

**Runner:** any

**Auto-merge:** yes

**Blocked by:** 140

**Spec:** `.scratch/item-links/spec.md` (Implementation Decisions: Approval reads links from the draft)
**Binding:** `docs/adr/0020-every-item-has-a-link-or-a-reason.md` (decisions 5, 6); `docs/adr/0015-approval-reads-the-card-or-the-threads-files-by-role.md`; `docs/adr/0019-boms-come-in-through-the-lab-template-and-are-read.md` (decisions 6–8); `docs/adr/0001-tests-first-and-no-muted-failures.md`
**Glossary:** `CONTEXT.md` — **Item link**, **No-link reason**, **Off-template BOM**, **Thread files at approval**

## What to build

At approval of a card whose line items carry no `link` key (ticket 144 will strip links
from card metadata), the bot finds its own newest draft BOM in the thread, reads the
item links and no-link reasons from it, and builds the archived BOM with them. If the draft
is gone, can't be downloaded, or doesn't match the card's items, approval still goes ahead
with a link-less BOM, and the thread asks the requester for **Replace BOM**, exactly as an
**Off-template BOM** does today.

**The spec says to reuse the thread-file listing. That doesn't work:**
`slack_io.classify_thread_files` skips every bot-posted message (its Rule 1), and the draft
is bot-posted. So this ticket adds its own small lookup and reuses only the download.

1. **`src/slack_io.py`** — add `newest_bot_draft_bom(client, channel: str, thread_ts: str) -> dict | None`.
   Call `client.conversations_replies(channel=channel, ts=thread_ts, limit=200)`. Keep only
   messages posted by the bot (`msg.get("user") == bot_user_id(client)` or `msg.get("bot_id")`),
   take their `files` whose `name` starts with `"DRAFT_HIRST_LAB_BOM_"`, and return the file
   object from the message with the largest `float(ts)`. Any exception → log a warning and
   return `None`. Put this right after `thread_files`.
2. **`src/bom.py`** — add the pure `merge_links(card_items: list[dict], draft_items: list[dict]) -> list[dict] | None`.
   Returns None unless both lists are the same length and, at each position, the names
   (`name` or `item_name`, stripped) are equal and the quantities (`quantity` or `qty`, as
   int) are equal. Otherwise returns copies of the card items with `link` and
   `no_link_reason` taken from the draft item at the same position.
3. **`src/lifecycle.py` `finalize_purchase_request`, inside `write_action`** — right after
   `build_items` is set and before the `if attached_boms:` block: when `card_ts` is set,
   `build_items is not None`, `attached_boms` is empty, and no item in `build_items` has a
   `"link"` key:
   - `draft = slack_io.newest_bot_draft_bom(client, channel, thread_ts)`; if found,
     `slack_io.download_file(draft)` → `bom.read_bom_template` → `bom.merge_links(build_items, draft_items)`
     (any exception during download/read counts as not found);
   - a merged list replaces `build_items`;
   - otherwise set `bom_read["problem"] = "I couldn't recover the item links from the draft BOM in this thread"`
     and log a warning naming the row. Do **not** set `bom_read["items"]`. The existing code
     then stores `off_template_bom`/`off_template_problem` on the card payload (so the DM card
     shows its flag line) and posts the existing "⚠️ … this BOM isn't ready for purchasing: … Use *Replace BOM*…"
     message. Reuse both; write no new wording.
   Items that already carry a `link` key (cards posted before ticket 144, or fresh items from
   the bare-thread Workday details form) skip this step untouched.

## Acceptance criteria

New file `tests/test_143_approval_reads_the_draft.py`, through
`lifecycle.finalize_purchase_request` with `card_ts` set, using the `temp_workbook`,
`temp_boms_dir` (or the `dirs` fixture of `tests/test_136_thread_bom.py`) and `sync_queue`
fixtures as `tests/test_29_approval_archives_bom.py` does. The fake client's
`conversations_replies` returns a thread holding a bot message (`user` = the id
`client.auth_test` returns) with a draft file; `slack_io.download_file` is monkeypatched to
return real bytes from `bom.build_bom_workbook`. May be faked: the Slack client, the
download, the clock. Must be real: the reader, the builder, the workbook row write and the
archive written to the temporary BOMs folder.

- [ ] `test_archived_bom_has_the_drafts_links_and_reasons` — card items (three, no `link` key) + a draft whose rows carry one link and the two reasons: the archived `.xlsx` in the BOMs folder, opened with openpyxl, has that URL as the hyperlink of row 6's Link and Item cells and the two reason texts in rows 7 and 8's Link cells.
- [ ] `test_newest_bot_draft_wins_and_requester_files_are_ignored` — two bot drafts with different links (ts `1.1`, `1.2`) and a requester-posted file also named `DRAFT_HIRST_LAB_BOM_x.xlsx`: the archive carries the links of the ts `1.2` draft.
- [ ] `test_missing_draft_still_approves_and_asks_for_replace_bom` — no draft in the thread: the log row is written, the archived BOM has no hyperlink in any Link cell, the approved card's metadata payload has `off_template_bom is True`, and a thread message contains `Replace BOM` and `couldn't recover the item links`.
- [ ] `test_mismatched_draft_is_refused` — a draft whose second row's quantity differs from the card: same outcome as the missing draft.
- [ ] `test_items_with_links_skip_the_lookup` — card items that carry `link` keys and a bot draft in the thread with *different* links: the archive carries the card items' links, not the draft's (proves cards posted before ticket 144 still work).

## Gate

    ruff check .
    python scripts/check_tests_first.py
    python tools/type_gate.py
    pytest --tb=short -q -n auto --dist loadfile --durations=25

## Out of scope

Stripping links from card metadata (144). Replace BOM itself (already reads links from its
own upload). BOMs dropped in the thread (`card_ts` is None there; unchanged). Visiting links.

## Comments
