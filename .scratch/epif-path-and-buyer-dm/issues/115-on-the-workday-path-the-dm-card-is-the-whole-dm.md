# 115: On the Workday path the DM card is the whole DM

**Status:** ready-for-agent

**Runner:** any

**Auto-merge:** yes

**Blocked by:** 112, 114

**Spec:** `.scratch/epif-path-and-buyer-dm/spec.md` (Part D, stories 11–12)
**Binding:** `docs/adr/0018-the-path-is-the-payment-method-and-the-dm-card-shows-the-request.md` (decision 3); `docs/adr/0010-linked-cards-and-direct-message-help.md` (decision 2)
**Glossary:** `CONTEXT.md` — **DM card**

## What to build

A buyer assigned a Workday-path request gets **one** DM: the DM card headed "Place this in
Workday", with every request line, the History and the Mark Processed button. The
separate "Place this in Workday:" text message goes away. A buyer assigned an EPIF-path
request still gets the email draft, then the files, then the DM card. The DM card now
carries the History and the path header.

1. `src/lifecycle.py` `_send_assignee_dm` gains `history: list | None = None`. It passes
   `history=history` and `route=route` to `blocks.build_dm_card_blocks`.
2. In `_send_assignee_dm`, when `route == "workday"`:
   - Do not call `slack_io.tell`. Post the DM card as today (`slack_io.post_dm_card`).
     After it succeeds, log ticket 112's `"📨 Buyer DM sent to %s for row %s (%s path)"`
     line, then the `"📨 DM card posted …"` line.
   - When `card_ts` is missing, call `slack_io.tell` with
     `"\n".join(blocks.request_summary_lines(request or {"parsed": parsed}, state or "approved"))`,
     and log a WARNING `"No card_ts; sent the Workday DM as text to %s"`.

   Delete the old Workday `dm_text` block (`Place this in Workday:\n• *Item:* …`).
3. When `route == "epif"`, `_send_assignee_dm` behaves as after ticket 112: the draft
   message, then the uploads, then the DM card, which now gets `history` and `route`.
4. Callers pass the History:
   - `finalize_purchase_request`'s `on_success` passes `history=hist`;
   - `handle_assign` passes `history=history`. Its `history` already has the new
     `Assigned to …` / `Reassigned to …` line appended.
5. Update the `_send_assignee_dm` docstring (ADR 0018 decision 3).

## Acceptance criteria

- [ ] New `tests/test_115_workday_dm_is_the_card.py`: a Workday-path approval through `lifecycle.finalize_purchase_request` (request `payment_method="Workday"`, buyer set, `card_ts` known) sends exactly **one** `chat_postMessage` to the buyer's id. That call has `blocks`, its section starts with `🛒 *Place this in Workday*`, it contains `• *Total:*` and `• *Row:*`, and a `context` block holds `Approved by` and `Assigned to`. No call to the buyer has text starting with `Place this in Workday:`.
- [ ] Same file: an EPIF-path approval (`payment_method="P-card"`) sends the buyer the draft message (text contains `Send this email to purchasing`) and then a DM card whose section starts with `📧 *Email the EPIF to purchasing*`, in that order.
- [ ] Same file: `lifecycle.handle_assign` on an approved Workday-path card sends the new buyer one card-only DM whose History block contains the `Assigned to` line.
- [ ] Same file, **same test function** as the first criterion (it passes on today's code alone): calling `_send_assignee_dm(route="workday", card_ts=None, ...)` sends one plain-text DM containing `• *Item:*` and logs the `No card_ts` warning.
- [ ] Rewritten in place, keeping the same test names and number of assertions:
  - in `tests/test_38_workday_path_approval.py`, the Workday DM assertions now read the buyer's single DM card blocks (section starts with `🛒 *Place this in Workday*`, contains `• *Item:*`, `• *Vendor:*`, `• *Total:* $149.99`, `• *Link:*`, `• *Row:* 21`, and no `Subject:`);
  - in `tests/test_08_assignment.py`, the `Place this in Workday:` text-call assertion reads the card instead.

  No test is deleted.

May fake: the Slack client (`MagicMock`), the lock queue (synchronous, as the `sync_queue` fixture in `tests/test_45_epif_approval_archives.py`), `log_writer.get_row_info`. Must be real: `_send_assignee_dm`, `blocks.build_dm_card_blocks`, `blocks.request_summary_lines`, `interview.get_request_route`, `finalize_purchase_request`, `handle_assign`.

## Gate

Run all four, in CI's order, and all must pass:

    ruff check .
    python scripts/check_tests_first.py
    python tools/type_gate.py
    pytest --tb=short -q -n auto --dist loadfile

Tests need `SLACK_BOT_TOKEN=xoxb-test-not-a-real-token`, `SLACK_APP_TOKEN=xapp-test-not-a-real-token` and `PYTHONUTF8=1` in the environment, as `.github/workflows/tests.yml` sets.

## Comments
