# 144: Item links leave the card's metadata

**Status:** in-progress

**Runner:** any

**Auto-merge:** yes

**Blocked by:** 143

**Spec:** `.scratch/item-links/spec.md` (Implementation Decisions: Links leave the card's metadata)
**Binding:** `docs/adr/0020-every-item-has-a-link-or-a-reason.md` (decision 5; supersedes ADR 0006 decision 5 for item links); `docs/adr/0006-bom-line-items-and-editable-posted-cards.md`; `docs/adr/0001-tests-first-and-no-muted-failures.md`
**Glossary:** `CONTEXT.md` — **Item link**, **No-link reason**, **Line item**

## What to build

Line items stored in a card message's Slack metadata no longer carry `link` (or the
reader's `row` number). Slack documents no size for message metadata, only a
`metadata_too_large` error, so a 50-row BOM with long links must never go there. Links live
in the draft BOM file in the thread; ticket 143 reads them back at approval. That's why this
ticket must land after 143.

**This must stay true:** the draft BOM is built from the **unstripped** items. Strip only
the copy written into `metadata`, never the list handed to `upload_draft_bom`, or the links
are lost for good.

1. **`src/bom.py`** — add the pure `items_for_card(items: list[dict] | None) -> list[dict]`:
   copies of the items without the keys `link` and `row`; every other key (including
   `no_link_reason`) kept.
2. **`src/lifecycle.py`** — every assignment of items into a payload that becomes card
   metadata goes through `bom.items_for_card`:
   - `finalize_purchase_request`: `req_payload["items"] = items` and
     `req_payload["items"] = bom_read["items"]`;
   - `handle_replace_bom`: `new_payload["items"] = items`;
   - `_process_interview_completion`: `req_payload["items"] = items`;
   - `handle_items_update`: `new_payload["items"] = items`;
   - `handle_request_edit`: `new_payload["items"] = items`.
   Find any other with `grep -n '"items"\] = ' src/lifecycle.py` and treat it the same way
   if it feeds a `metadata=` write. `src/store.py` is not Slack metadata; leave it.
3. **`src/lifecycle.py` `handle_request_edit`** — compare `bom.items_for_card(old_items)`
   with `bom.items_for_card(items)` when calling `bom.describe_changes`, so an Edit that
   doesn't touch the BOM no longer differs only by links. Let `fresh = any("link" in i for i in items)`
   (items read from a newly uploaded file carry the key; items from metadata never do).
   When `fresh` and `describe_changes` gave no `items…` fragment, append the fragment
   `"BOM re-uploaded"`. Re-post the draft BOM when `(items_changed or fresh) and bom.needs_bom(items)`,
   passing the unstripped `items`.

## Acceptance criteria

New file `tests/test_144_links_leave_metadata.py`, reusing the fake-client setups of
`tests/test_134_screen2_bom_check.py`, `tests/test_135_edit_and_add_items_bom.py`,
`tests/test_137_replace_bom.py` and `tests/test_29_approval_archives_bom.py`. May be faked:
the Slack client, downloads (real bytes from `bom.build_bom_workbook`), the clock. Must be
real: the reader, the builder, the workbook and archive writes on temporary copies. Each
test asserts on the `metadata=` argument actually passed to `client.chat_postMessage` /
`client.chat_update`.

- [ ] `test_posted_card_metadata_has_no_links_but_the_draft_does` — Screen 2 with a linked 3-row BOM: no item in the posted card's `metadata["event_payload"]["items"]` has a `link` or `row` key, and the draft BOM bytes passed to `files_upload_v2` read back with the links.
- [ ] `test_add_items_and_edit_keep_links_out_of_metadata` — Add items and Edit with a new linked BOM: same assertion on the `chat_update` metadata; each re-posts a draft carrying the new links.
- [ ] `test_edit_with_only_new_links_reposts_the_draft` — Edit with a BOM whose rows equal the card's but whose links differ: the thread edit line contains `BOM re-uploaded`, and a new draft with the new links is uploaded.
- [ ] `test_approval_and_replace_bom_keep_links_out_of_metadata` — approving that card (draft present in the thread, as in ticket 143's tests) and then Replace BOM: neither card's metadata items carry `link`, and the archived BOM has the draft's links (approval) and the new file's links (Replace BOM).
- [ ] Existing tests that asserted `link` inside card metadata items are rewritten in place under their existing names to assert its absence; none deleted. (no test: existing tests rewritten in place; the full suite passing is the proof)

## Gate

    ruff check .
    python scripts/check_tests_first.py
    python tools/type_gate.py
    pytest --tb=short -q -n auto --dist loadfile --durations=25

## Out of scope

Migrating cards posted before this lands (their items keep their links; ticket 143 handles
them). `src/store.py`. The request-level `link` field of a one-item request (it is one
short URL on `parsed`, not a line item).

## Comments
