# 141: The BOM check shows each link and asks why a row has none

**Status:** ready-for-agent

**Runner:** any

**Auto-merge:** yes

**Blocked by:** 140

**Spec:** `.scratch/item-links/spec.md` (Implementation Decisions: BOM check view, BOM check submit)
**Binding:** `docs/adr/0020-every-item-has-a-link-or-a-reason.md` (decisions 3, 5); `docs/adr/0019-boms-come-in-through-the-lab-template-and-are-read.md` (decision 5); `docs/adr/0001-tests-first-and-no-muted-failures.md`
**Glossary:** `CONTEXT.md` — **Item link**, **No-link reason**, **BOM check**

## What to build

On the **BOM check** screen each row shows its **item link** as a clickable site name, and
each row with neither a link nor a **no-link reason** asks the requester to pick
**No web page** or **Covered by another row's link**. Continue is refused until every such
row has a pick. The picks travel with the rows into the draft BOM posted in the thread.
There is one check view and one submit handler, so Screen 2, Add items, Edit, Replace BOM
and the Workday details form all get this with no per-route code.

Also, decided by the developer on 2026-11-02 (not in the spec): **a BOM with exactly one
row is refused on the check screen.** A one-row BOM never gets a draft or an archived BOM
(`bom.needs_bom` needs two items), so its link would reach purchasing nowhere.

1. **`src/bom.py`** — add the pure `link_site(url: str) -> str`: the URL's host
   (`urllib.parse.urlsplit(url).hostname`) with one leading `www.` removed; the URL itself
   if there is no host.
2. **`src/blocks.py` `_bom_row_line`** — append ` — <{url}|{site}>` when the item has a
   `link` of 2,000 characters or fewer, ` — {site}` (plain, not linked) when longer (a
   section block holds 3,000 characters), and ` — no link` when there is none. A row with a
   `no_link_reason` and no link shows ` — {reason}` instead of `no link`.
3. **`src/blocks.py` `build_bom_check_view`** — the preview sections are packed so no
   section's text exceeds 3,000 characters (start a new section when the next line would
   cross it, and still at most 10 rows per section). When `problems` is empty, after the
   problems block add, for every item (all rows, not only the previewed ones) whose `link`
   and `no_link_reason` are both empty, one input block:
   - `block_id`: `f"block_no_link_{item['row']}"`, `optional: True` (Slack enforces
     non-optional inputs in the client before submit, which would block a re-upload submit;
     the handler enforces the rule instead),
   - label: `f"Row {row}: {name[:60]} has no link. Why?"`,
   - element: `radio_buttons`, `action_id` `no_link_reason`, exactly two options with values
     `no_web_page` and `covered_by_other_row` and texts `config.NO_LINK_REASONS[0]` and
     `[1]`.
   Store the list of those row numbers in `private_metadata` as `no_link_rows`.
   When `problems` is non-empty, add `send_bom_template_block()` directly after the problems
   block, so an old-template upload offers the new template.
4. **`src/lifecycle.py` `read_bom_file`** — after the reader, when there are no problems and
   exactly one item, problems become
   `["This BOM has one item. Leave the BOM field empty and give that item's link on the form instead."]`.
5. **`src/lifecycle.py`** — add `apply_no_link_reasons(view_id: str | None, picks: dict[int, str]) -> bool`:
   sets `no_link_reason` on the items cached in `_BOM_READ_CACHE[view_id]` whose `row` is a
   key of `picks`; returns False when there is no cache entry for the view.
6. **`src/app.py` `handle_bom_check_submit`** — after the existing `bom_ok` refusal and
   before the `origin` branch: for each row in `meta.get("no_link_rows") or []`, read
   `values[f"block_no_link_{row}"]["no_link_reason"]["selected_option"]`; every unpicked
   row gets `errors[block_id] = "Pick why this row has no link."` and the submit is answered
   with `response_action="errors"`. Otherwise map the option values to the
   `config.NO_LINK_REASONS` phrases and call `lifecycle.apply_no_link_reasons`; on False,
   answer with the existing "This form timed out. Close it and submit again." error on
   `block_bom_reupload`. A submit carrying a re-uploaded file keeps going down the existing
   re-read branch untouched (it comes first), and the redrawn view starts with no picks.

## Acceptance criteria

New file `tests/test_141_no_link_reasons.py`. Drive it through `app.handle_stage2_submit` /
`app.handle_bom_check_submit` and the other routes' submit handlers with the fake client of
`tests/test_134_screen2_bom_check.py` (`world` fixture: a `MagicMock` client,
`slack_io.download_file` monkeypatched to return real bytes built with
`bom.build_bom_workbook`, `app._run_in_background` run inline). May be faked: the Slack
client and file download. Must be real: `bom.read_bom_template`, `bom.build_bom_workbook`,
`blocks.build_bom_check_view` and `lifecycle._BOM_READ_CACHE`.

- [ ] `test_check_view_shows_site_names_and_one_input_per_unlinked_row` — a 3-row BOM (row 6 linked to `https://www.mcmaster.com/91251A540`, rows 7 and 8 unlinked): the view passed to `client.views_update` contains `<https://www.mcmaster.com/91251A540|mcmaster.com>`, `no link` twice, input blocks `block_no_link_7` and `block_no_link_8` each with exactly the two option texts, no `block_no_link_6`, and every section's text is ≤ 3,000 characters.
- [ ] `test_continue_refused_until_every_reason_is_picked` — submitting the check view with only row 7 picked returns `response_action == "errors"` with `"block_no_link_8": "Pick why this row has no link."` and nothing posted to the purchasing channel; picking both continues to posting.
- [ ] `test_picked_reasons_reach_the_draft_bom` — after the passing submit above, the bytes given to `client.files_upload_v2` (the draft) read back with `bom.read_bom_template` give row 7 `no_link_reason == "No web page"` and row 8 `"Covered by another row's link"`, and row 6 its link.
- [ ] `test_every_bom_route_reaches_the_reason_inputs` — Add items, Edit, Replace BOM and Workday details (set up as in `test_135_edit_and_add_items_bom` and `test_137_replace_bom`) each produce a check view containing `block_no_link_7` for the same BOM.
- [ ] `test_old_template_and_one_row_boms_are_refused` — an upload with `config.BOM_OLD_TEMPLATE_HEADERS` shows the old-template sentence and a block with `block_id == "block_bom_template"`; a clean one-row BOM shows the one-item sentence and Continue is refused.
- [ ] Existing tests that break because they upload one-row BOMs or assert the old row line are rewritten in place under their existing names; none deleted. (no test: existing tests rewritten in place; the full suite passing is the proof)

## Gate

    ruff check .
    python scripts/check_tests_first.py
    python tools/type_gate.py
    pytest --tb=short -q -n auto --dist loadfile --durations=25

## Out of scope

Screen 2's one-item link field (142). Approval and card metadata (143, 144). BOMs dropped
straight into a thread: no link check there (ADR 0020 decision 7). A "same as row N"
pointer. Showing full URLs in Slack.

## Comments
