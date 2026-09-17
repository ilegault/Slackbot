# 22: A live roster panel on App Home

**What to build:** App Home stops being a static command list. It shows the name
you are registered under, which of the three roles you hold, and a button that
opens the `/roster-set-name` modal. If you are not registered, it leads with that.

**Blocked by:** 19, 20

**Status:** done

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

- [x] `build_app_home_view(user_id)` for a **registered** user shows that user's
      name — asserted on the **specific name**, not on block count
- [x] For an **unregistered** user it shows the registration prompt, and that
      prompt appears above the static command content
- [x] The panel shows the roles the user holds, and shows them correctly for a user
      holding all three and for a user holding none
- [x] The panel's button opens the ticket-19 modal — asserted on the `action_id` /
      callback, not on a screenshot
- [x] `remove-member` appears in **both** `build_app_home_view()` and
      `get_help_message()`, and a test asserts the shared constant is the only place
      it is written
- [x] `build_app_home_view` makes no Slack API call and holds no client
- [x] The existing drift test still passes and now covers the changed commands
- [x] `ruff check .`, `python scripts/check_tests_first.py` and `pytest -q` all pass

## Out of scope

- A link to the Purchasing Log on App Home. Decided against; do not add one.
- Any admin-facing roster editing panel on App Home. Roster management stays on
  the `@Purchasing` keyword pairs.
- Showing other people's registrations. The panel is about the viewer.

## Comments

### 2026-09-17 Implementation Summary

- **Live Roster Profile Panel**:
  - Enhanced `blocks.build_app_home_view(user_id=None)` to construct a profile panel placed above static command content.
  - For registered users: displays their registered name (`roster.get_requesters()`) and active roles (`roster.is_admin`, `roster.is_approver`, `roster.is_buyer`). Accessory button provides "Update Name".
  - For unregistered users: leads immediately with registration instructions and an action button ("Register in Roster", `style="primary"`), without burying the prompt under empty role sections.
  - Button uses `action_id=config.ACTION_OPEN_ROSTER_SET_NAME` (`"open_roster_set_name"`).
  - Preserved pure presentation layer: holds no Slack client, makes zero API calls.
- **Roster & Config Constants**:
  - Defined `config.ACTION_OPEN_ROSTER_SET_NAME = "open_roster_set_name"`.
  - Added role helper accessors `roster.is_admin` and `roster.is_approver` to match `roster.is_buyer`.
- **Shared App Home & Help Command Constants**:
  - Added `remove-member` to `blocks._ADMIN_COMMANDS`.
  - Updated `blocks._SLASH_COMMANDS` description for `/roster-set-name` to reflect ticket 19's register, correct, or rename functionality.
- **Action & Event Listeners in `src/app.py`**:
  - Registered `@app.action(config.ACTION_OPEN_ROSTER_SET_NAME)` with `handle_open_roster_set_name_action` to open `blocks.build_roster_set_name_view`.
  - Updated `@app.event("app_home_opened")` to pass `user_id=user_id` to `blocks.build_app_home_view`.
- **Tests**:
  - Created `tests/test_22_live_roster_panel.py` covering: registered user specific name display, unregistered user prompt placement above static content, roles list for all-three and none, action button existence, modal opening on click with callback verification, pure builder invariant, and `app_home_opened` event handling.
  - Extended `tests/test_09_app_home_help.py` with drift checks for `_SLASH_COMMANDS`, `remove-member` presence across both surfaces, and AST verification that `remove-member` only exists in `_ADMIN_COMMANDS` within `blocks.py`.
- **Gate Results**:
  - `ruff check .`: clean
  - `python scripts/check_tests_first.py`: clean
  - `pytest -q`: 274 passed, 31 skipped (zero failures)
