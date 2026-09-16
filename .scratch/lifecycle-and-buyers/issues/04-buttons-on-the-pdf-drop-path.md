# 04: Buttons on the PDF-drop path

**What to build:** Post `build_request_blocks("posted", …)` from the EPIF-PDF path
too, so a dropped PDF produces the same Approve button as a modal submission.

**Blocked by:** 01

**Status:** ready-for-agent

Read `docs/adr/0002-request-lifecycle-and-surfaces.md` decisions 1 and 2 first.
`docs/adr/0001-tests-first-and-no-muted-failures.md` is binding.

## Why

`build_request_blocks` is only ever called from the modal-submission path and from
the button handlers themselves. A request that arrives as an **EPIF PDF dropped
into a channel thread** gets no buttons at all — the approver has to fall back to
typing `@p-bot approved`.

Two different experiences for the same task, with nothing explaining the
difference. This is the half of T3 that did not land, and it is the live source of
approver confusion: Charlie sees buttons on some requests and not others and has
no way to tell which he is looking at.

## Requirements

- **Build the payload where the PDF is parsed**, not inside the block builder. The
  PDF path's request payload has to match the shape `build_request_blocks` already
  expects (`parsed`, `requester`, `user_id`, `is_pending_name`); reshaping it
  inside the builder would give the builder two input shapes to know about.
- **Do not duplicate lifecycle logic.** The existing action handlers already
  delegate to the shared handlers and should work unchanged. If they do not, say so
  rather than writing a second path.
- **The `@p-bot approved` keyword still works** on a PDF request. It is an
  undocumented alias, not a removed feature.

## Acceptance criteria

- [ ] An EPIF PDF dropped in a channel thread produces a bot post carrying a
      `req_approve` button, identical in shape to the modal path's post
- [ ] The PDF path's request payload is built where the PDF is parsed, and
      `build_request_blocks` is unchanged
- [ ] Clicking Approve as an approver on a PDF request writes the row, rewrites the
      message with a history line and a Claim button, and behaves exactly as a
      modal request does
- [ ] Clicking Approve as a non-approver gets an ephemeral denial, the message is
      unchanged, and nothing is written to Excel
- [ ] `@p-bot approved` on a PDF request still works
- [ ] No lifecycle logic is duplicated: the button handler calls the same
      `handle_epif_processing` the keyword branch calls
- [ ] A test asserts a PDF dropped in a thread produces a message carrying a
      `req_approve` button
- [ ] A test walks a PDF request from `posted` to `delivered` through the buttons
      and asserts the same Excel writes as the modal path produces
- [ ] `ruff check .`, `python scripts/check_tests_first.py` and `pytest -q` all pass

## Comments
