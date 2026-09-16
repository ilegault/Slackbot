# 09: Refresh App Home and the help text, from one source

**What to build:** Bring both user-facing explainers up to date with what the bot
actually does after ticket 08, and stop them being two copies of the same text.

**Blocked by:** 08

**Status:** ready-for-agent

Read `docs/adr/0004-assignment-replaces-claim.md` and `CONTEXT.md` first — this
ticket is where their vocabulary becomes what the lab reads.
`docs/adr/0001-tests-first-and-no-muted-failures.md` is binding.

## Why

Three things are wrong with the text a new lab member reads first.

**It teaches a button that no longer exists.** Both surfaces say *"Approve or
Decline (approvers), **Claim** (grad buyers), Mark Processed…"*.

**It tells people to mention a bot that does not exist.** Every admin line says
`@p-bot health`, `@p-bot update`, `@p-bot add-approver @user`. The app is called
**Purchasing** in Slack. `p-bot` is a word from conversation and the repo name; it
has never been the handle. Someone copying these lines types a mention that
resolves to nobody.

**It is two copies.** `blocks.py:98` (inside the `APP_HOME_VIEW` dict) and
`blocks.py:222` (inside `get_help_message`) carry near-identical strings that have
to be edited in lockstep. They have already drifted once. Editing both again is
how they drift a second time.

## Requirements, stated as requirements

1. **One source for the shared text.** The interface rule, the "move a request
   along" list and the stage definitions become module-level constants in
   `src/blocks.py`, rendered by both `APP_HOME_VIEW` and `get_help_message()`.
   `APP_HOME_VIEW` is currently a static dict — if a constant cannot be
   interpolated into it cleanly, turn it into `build_app_home_view()` and update
   the one caller. Do not solve this by editing the same sentence in two places.
2. **The handle is `@Purchasing`.** Every `@p-bot` in user-facing text becomes
   `@Purchasing`. Log lines, docstrings and module comments are out of scope —
   this is about what a lab member reads.
3. **The button list matches reality:** *Approve* or *Decline* (approvers),
   *Mark Processed*, *Mark Confirmed*, *Mark Delivered* (the assigned buyer or an
   admin), *Cancel* (approvers and admins, before processed). No Claim.
4. **Approval and assignment are explained together**, in the approver's own
   words, because this is the one thing the bot now expects to be typed rather
   than clicked:

   ```
   Approving: reply in the request thread with @Purchasing approved and
   @-mention the grad student who will handle it —
      @Dylan @Purchasing approved     (either order works)
   Forgot to name someone? The request is still approved. Any buyer can take it
   with @Purchasing assign @themselves.
   ```

5. **Keep the four stages, add the one-line clarification** that assignment is not
   a stage: `Assigned isn't a stage — it's who is handling the order.` Keep them in
   the wording `CONTEXT.md` uses. **No link to the Purchasing Log** (ADR 0002
   decision 9).
6. **The admin command list gains `add-buyer` and `remove-buyer`.** Both shipped in
   ticket 02 and neither is documented anywhere a person can see.

## Acceptance criteria

- [ ] The interface rule, the button list and the stage definitions each exist
      **once** in `src/blocks.py` and are rendered by both surfaces
- [ ] A test renders App Home and `get_help_message()` and asserts the shared
      strings are byte-identical between them — the drift guard, and it must fail
      if someone edits one copy back in
- [ ] Neither surface contains the string `Claim` or `claim`
- [ ] Neither surface contains the string `@p-bot`
- [ ] Both surfaces show the approve-and-mention example in both mention orders
- [ ] Both surfaces state that a forgotten mention still leaves the request
      approved, and how a buyer takes it
- [ ] Both surfaces list `add-buyer` and `remove-buyer`
- [ ] The four stages are present with the wording from `CONTEXT.md`, plus the
      "Assigned isn't a stage" line, and no link to the Purchasing Log
- [ ] `ruff check .`, `python scripts/check_tests_first.py` and `pytest -q` all pass

## Out of scope

- The bot's Slack app description and App Home title outside `APP_HOME_VIEW` —
  those are set in the Slack admin UI, not in this repo. If the description also
  says `p-bot`, that is a human task for Isaac.
- Renaming anything in the code from `p_bot` — the package, the spec file and the
  log file keep their names.
