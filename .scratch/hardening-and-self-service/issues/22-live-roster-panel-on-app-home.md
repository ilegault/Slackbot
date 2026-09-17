# 22: A live roster panel on App Home

**What to build:** App Home stops being a static command list. It shows the name
you are registered under, which of the three roles you hold, and a button that
opens the `/roster-set-name` modal. If you are not registered, it leads with that.

**Blocked by:** 19, 20

**Status:** ready-for-agent

**Read before starting:** `tests/test_09_app_home_help.py` — it already asserts
App Home and `/purchasing-help` cannot drift, and it is the seam here.
`docs/adr/0001-tests-first-and-no-muted-failures.md` is binding.

## Why

Ticket 09 refreshed App Home from one source, which fixed the drift. But the page
still tells everyone the same thing, so a lab member cannot check the name they
are registered under without running a command — and someone who is not
registered at all sees a command list rather than the one thing they need to do.

This ticket goes last because it renders what tickets 19 and 20 built.

## Requirements, stated as requirements

1. **`blocks.build_app_home_view()` gains a `user_id` parameter** and a panel
   **above** the existing static content showing:
   - the name this user is registered under, or that they are not registered yet;
   - which of the three roles they hold (approver, admin, buyer);
   - a button opening the `/roster-set-name` modal from ticket 19.

2. **Not registered is the interesting case.** The panel **leads with the fix**,
   because that is the first thing that person needs. It does not bury the
   registration prompt under a role list that is empty anyway.

3. **`blocks.py` already imports `roster`**, and blocks may import storage under
   the layering rule. It still holds **no Slack client** and makes **no API call**.

4. **`_ADMIN_COMMANDS` gains `remove-member`**, and `_SLASH_COMMANDS` gains
   whatever ticket 19 changed about `/roster-set-name`. Both surfaces update from
   the **one** constant — never a second copy pasted into either function.

5. **Every new or changed roster command is reflected in both surfaces.** That is
   what the drift test in `tests/test_09_app_home_help.py` is for; extend it rather
   than working around it.

## Acceptance criteria

- [ ] `build_app_home_view(user_id)` for a **registered** user shows that user's
      name — asserted on the **specific name**, not on block count
- [ ] For an **unregistered** user it shows the registration prompt, and that
      prompt appears above the static command content
- [ ] The panel shows the roles the user holds, and shows them correctly for a user
      holding all three and for a user holding none
- [ ] The panel's button opens the ticket-19 modal — asserted on the `action_id` /
      callback, not on a screenshot
- [ ] `remove-member` appears in **both** `build_app_home_view()` and
      `get_help_message()`, and a test asserts the shared constant is the only place
      it is written
- [ ] `build_app_home_view` makes no Slack API call and holds no client
- [ ] The existing drift test still passes and now covers the changed commands
- [ ] `ruff check .`, `python scripts/check_tests_first.py` and `pytest -q` all pass

## Out of scope

- A link to the Purchasing Log on App Home. Decided against; do not add one.
- Any admin-facing roster editing panel on App Home. Roster management stays on
  the `@Purchasing` keyword pairs.
- Showing other people's registrations. The panel is about the viewer.
