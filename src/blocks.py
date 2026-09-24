"""Block Kit builders and view definitions for Slack UI.

WHY THIS EXISTS:
----------------
Constructs Slack Block Kit dictionaries and view payloads for App Home, modals,
and message cards. Pure presentation layer that takes dictionaries/metadata
and returns list/dict Block Kit structures.
ADR 0005: The posted card carries a buyer picker (users_select) in the same
actions block as Approve and Decline, allowing approvers to pick a buyer directly
without typing a mention.
Ticket 22: App Home renders a live roster profile panel (build_app_home_view)
displaying the user's registered name, held roles (admin, approver, buyer), and a
direct button opening the /roster-set-name modal. Unregistered users lead with registration instructions.
Ticket 27: Adds build_items_view for line items modal and renders Add items / Edit items button on posted source=='epif' cards.
Ticket 28: Screen 2 (build_stage2_view) renders an optional multiline Line items input with format/shipping hint and 1500-char limit.

Imports:
    - bom, config, interview, roster, text_rules
May NOT import:
    - Slack SDK / Bolt (holds no client, makes no API calls)
    - storage writers (log_writer, queue_worker)
    - lifecycle/ops handlers
"""
import json
from datetime import datetime

try:
    from . import bom, config, interview, roster
except ImportError:
    import bom
    import config
    import interview
    import roster

# ---------------------------------------------------------------------------
# Shared text constants — the single source for content rendered by both
# build_app_home_view() and get_help_message().  Edit here; never paste a
# second copy into either function.
# ---------------------------------------------------------------------------

_INTERFACE_RULE = (
    "> *Rule:* If the action needs a target, it's a button on that target. "
    "If it doesn't, it's a slash command."
)

_BUTTON_LIST = (
    "• Click the action buttons on the request message: *Approve* (approvers) or *Decline* (approvers and buyers), "
    "*Mark Processed*, *Mark Confirmed*, and *Mark Delivered* (the assigned buyer or an admin).\n"
    "• Approvers and admins may also *Cancel* an approved request before it is processed.\n"
    "• Drop quote files or confirmation receipts directly into the thread to attach them.\n\n"
    "*Approving:* reply in the request thread with `@Purchasing approved` and `@`-mention "
    "the grad student who will handle it —\n"
    "```\n"
    "@Dylan @Purchasing approved     ← either order works\n"
    "@Purchasing approved @Dylan\n"
    "```\n"
    "Forgot to name someone? The request is still approved. "
    "Any buyer can take it with `@Purchasing assign @themselves`."
)

_STAGE_DEFINITIONS = (
    "A purchase request moves through four stages after approval:\n"
    "• *Approved* — Charlie has agreed to spend the money; the row is written to the purchasing log.\n"
    "• *Processed* — The request has gone to the purchasing team (Workday / ShopUW).\n"
    "• *Confirmed* — The order is confirmed by the vendor.\n"
    "• *Delivered* — The package is in the lab.\n\n"
    "_Assigned isn't a stage — it's who is handling the order._"
)

_ADMIN_COMMANDS = (
    "• `@Purchasing health` / `@Purchasing status` — View system health, host uptime, and storage status.\n"
    "• `@Purchasing queue` — View Excel lock write queue status.\n"
    "• `@Purchasing logs [n]` — _(Admin Only, alert channel)_ Last *n* lines (default 30); long output arrives as a file.\n"
    "• `@Purchasing logs all` — _(Admin Only, alert channel)_ The whole current log file.\n"
    "• `@Purchasing logs rejections` — _(Admin Only, alert channel)_ The whole rejections log.\n"
    "• `@Purchasing update` — _(Admin Only)_ Pull latest git code and restart bot.\n"
    "• `@Purchasing restart` — _(Admin Only)_ Gracefully restart the bot process.\n"
    "• `@Purchasing promote-admin @user` — _(Admin Only)_ Propose promoting a user to bot administrator.\n"
    "• `@Purchasing add-approver @user` — _(Admin Only)_ Add a user to the approver list.\n"
    "• `@Purchasing remove-approver @user` — _(Admin Only)_ Remove a user from the approver list.\n"
    "• `@Purchasing add-buyer @user` — _(Admin Only)_ Add a user to the buyers list.\n"
    "• `@Purchasing remove-buyer @user` — _(Admin Only)_ Remove a user from the buyers list.\n"
    "• `@Purchasing remove-member @user` — _(Admin Only)_ Remove a user from the lab roster and all roles.\n"
    "• `@Purchasing add-vendor <name>` — _(Admin Only)_ Add a vendor to the Workday catalog list.\n"
    "• `@Purchasing remove vendor <name>` — _(Admin Only)_ Remove a vendor from the Workday catalog list."
)

_SLASH_COMMANDS = (
    "• `/new-purchase` — Open the guided purchasing modal to submit an order request.\n"
    "• `/purchasing-help` — Display this help and command reference.\n"
    "• `/blank-template` — Download the blank EPIF PDF template and instructions.\n"
    "• `/roster-list` — List registered lab members and Workday catalog vendors.\n"
    "• `/roster-set-name` — Register in the lab roster, correct your name, or request a rename."
    "\n\n_Vendor not in the list but you know it's on Workday? Ask an admin to add it (`@Purchasing add-vendor`)._"
)

# --- App Home Block Kit View --------------------------------------------------


def build_app_home_view(user_id: str | None = None) -> dict:
    """Build the App Home Block Kit view dict.

    WHY THIS EXISTS:
    ----------------
    Constructs the App Home tab for the user.
    Ticket 09: Unified shared constants with get_help_message() so the two surfaces cannot drift.
    Ticket 22: Added live roster profile panel showing user's registered name, held roles
    (approver, admin, buyer), and a direct button opening the /roster-set-name modal.
    Unregistered users lead with registration instructions above the static command content.
    Holds no Slack client and makes no API calls (pure presentation layer).
    """
    registered_name = None
    if user_id and hasattr(roster, "get_requesters"):
        requesters = roster.get_requesters()
        registered_name = requesters.get(user_id)

    roles = []
    if user_id:
        if hasattr(roster, "is_admin") and roster.is_admin(user_id):
            roles.append("Admin")
        elif hasattr(roster, "get_admins") and user_id in roster.get_admins():
            roles.append("Admin")

        if hasattr(roster, "is_approver") and roster.is_approver(user_id):
            roles.append("Approver")
        elif hasattr(roster, "get_approvers") and user_id in roster.get_approvers():
            roles.append("Approver")

        if hasattr(roster, "is_buyer") and roster.is_buyer(user_id):
            roles.append("Buyer")
        elif hasattr(roster, "get_buyers") and user_id in roster.get_buyers():
            roles.append("Buyer")

    roles_str = ", ".join(roles) if roles else "None"

    action_id = getattr(config, "ACTION_OPEN_ROSTER_SET_NAME", "open_roster_set_name")
    if registered_name:
        profile_text = (
            f"👤 *Your Lab Profile*\n"
            f"• *Registered Name:* {registered_name}\n"
            f"• *Roles:* {roles_str}"
        )
        profile_button = {
            "type": "button",
            "text": {"type": "plain_text", "text": "Update Name", "emoji": True},
            "action_id": action_id,
        }
    else:
        profile_text = (
            "⚠️ *You are not registered in the lab roster yet.*\n"
            "Register your name so your purchase requests can be approved and tracked.\n"
            f"• *Roles:* {roles_str}"
        )
        profile_button = {
            "type": "button",
            "text": {"type": "plain_text", "text": "Register in Roster", "emoji": True},
            "style": "primary",
            "action_id": action_id,
        }

    profile_block = {
        "type": "section",
        "text": {
            "type": "mrkdwn",
            "text": profile_text,
        },
        "accessory": profile_button,
    }

    return {
        "type": "home",
        "blocks": [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": "Hirst Lab Purchasing Bot",
                    "emoji": True,
                },
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": (
                        "Welcome! *Purchasing* automates logging, tracking, and archiving lab purchase requests "
                        "directly to `Purchasing-Log.xlsx` and OneDrive.\n\n"
                        + _INTERFACE_RULE
                    ),
                },
            },
            {"type": "divider"},
            profile_block,
            {"type": "divider"},
            {
                "type": "header",
                "text": {"type": "plain_text", "text": "🛒 Start Something", "emoji": True},
            },
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": _SLASH_COMMANDS},
                "accessory": {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "New Purchase Request", "emoji": True},
                    "style": "primary",
                    "action_id": "start_purchase_interview",
                },
            },
            {"type": "divider"},
            {
                "type": "header",
                "text": {"type": "plain_text", "text": "🔄 Move a Request Along", "emoji": True},
            },
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": _BUTTON_LIST},
            },
            {"type": "divider"},
            {
                "type": "header",
                "text": {"type": "plain_text", "text": "📋 Request Stages", "emoji": True},
            },
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": _STAGE_DEFINITIONS},
            },
            {"type": "divider"},
            {
                "type": "header",
                "text": {"type": "plain_text", "text": "⚙️ Admin Operations", "emoji": True},
            },
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": _ADMIN_COMMANDS},
            },
            {"type": "divider"},
            {
                "type": "header",
                "text": {"type": "plain_text", "text": "⚠️ Common Issues & Troubleshooting", "emoji": True},
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": (
                        "• *Excel Locked:* If `Purchasing-Log.xlsx` is open in Excel, Purchasing automatically "
                        "queues your update and writes it immediately once closed.\n"
                        "• *Validation Rejections:* Make sure all required fields in the EPIF form are filled.\n"
                        "• *Price Mismatch:* If the final invoice or checkout total differs from the initial "
                        "estimate, contact your purchase approver or lab buyer.\n"
                        "• *File Attachments:* For confirmations and quotes, ensure you attach the file in the "
                        "request thread."
                    ),
                },
            },
            {"type": "divider"},
            {
                "type": "header",
                "text": {"type": "plain_text", "text": "💬 Questions, Feedback & Complaints", "emoji": True},
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": "Bot maintained by: *Isaac Legault*\n\nIf you experience any bugs, errors, or have suggestions/complaints, please feel free to DM me directly on Slack.",
                },
            },
            {
                "type": "context",
                "elements": [{"type": "mrkdwn", "text": "Hirst Lab Automation • Report issues to Isaac Legault"}],
            },
        ],
    }


def get_help_message() -> str:
    """Command guide rendered by /purchasing-help.

    Uses the same module-level constants as build_app_home_view() so the two
    surfaces cannot drift.  Edit the constants above; never add a second copy
    of a sentence here.
    """
    return (
        "🤖 *Hirst Lab Purchasing Bot*\n\n"
        + _INTERFACE_RULE + "\n\n"
        "*🛒 Start something (Slash Commands):*\n"
        + _SLASH_COMMANDS + "\n\n"
        "*🔄 Move a request along (Buttons on the message):*\n"
        + _BUTTON_LIST + "\n\n"
        "*📋 Request Stages:*\n"
        + _STAGE_DEFINITIONS + "\n\n"
        "*⚙️ Admins (`@Purchasing <command>`):*\n"
        + _ADMIN_COMMANDS
    )


def build_request_blocks(
    state: str,
    request: dict,
    history: list | None = None,
    requester: str | None = None,
    items: list[dict] | None = None,
) -> list:
    """Generate Block Kit blocks for a purchase request at a given lifecycle state.

    States: posted -> approved -> processed -> confirmed -> delivered
    Terminal states with no buttons: declined, cancelled, delivered, superseded.
    """
    parsed = request.get("parsed", request)
    requester = requester or request.get("requester")
    user_id = request.get("user_id")
    is_pending_name = request.get("is_pending_name", False)

    if items is None:
        items = request.get("items")

    display_name = f"{requester} (pending name confirmation)" if is_pending_name else (requester or (f"<@{user_id}>" if user_id else "Requester"))

    item = parsed.get("item_description", "Item")
    price = parsed.get("total_price")
    if isinstance(price, (int, float)):
        price_str = f"${price:,.2f}"
    elif price:
        price_str = str(price)
        if not price_str.startswith("$"):
            price_str = f"${price_str}"
    else:
        price_str = "$0.00"

    vendor = parsed.get("vendor", "Vendor")
    payment_method = parsed.get("payment_method", "Workday")
    category = parsed.get("category", "")
    project_id = parsed.get("project_id", "")
    fund = parsed.get("fund", "")
    delivery_room = parsed.get("delivery_room", "")
    purpose = parsed.get("purpose", "")
    suggest_note = request.get("suggest_note", "")

    summary_lines = [
        f"🛒 *New Purchase Request from {display_name}:*",
        f"• *Item:* {item}",
        f"• *Total:* {price_str}",
        f"• *Vendor:* {vendor} ({payment_method})",
        f"• *Category:* {category}",
        f"• *Project ID / Fund:* {project_id} (Fund {fund})",
        f"• *Delivery Room:* {delivery_room}",
        f"• *Purpose:* {purpose}",
    ]
    link = parsed.get("link")
    if link:
        summary_lines.append(f"• *Link:* {link}")
    assignee_id = request.get("assignee_id")
    assignee = request.get("assignee")
    if assignee_id:
        buyer_str = f"<@{assignee_id}> ({assignee})" if assignee else f"<@{assignee_id}>"
        summary_lines.append(f"• *Buyer:* {buyer_str}")
    elif assignee:
        summary_lines.append(f"• *Buyer:* {assignee}")
    elif state != "posted":
        summary_lines.append("• *Buyer:* ⚠️ _Unassigned_")

    if items and bom.needs_bom(items):
        summary_lines.append(f"📋 {len(items)} line items (BOM attached in thread)")

    if suggest_note:
        summary_lines.append(suggest_note)

    blocks = [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "\n".join(summary_lines),
            },
        }
    ]

    if history:
        hist_text = "\n".join(f"• {h}" for h in history)
        blocks.append({
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": f"*History:*\n{hist_text}",
                }
            ],
        })

    if state == "waiting_for_details":
        blocks.append({
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": "Approved — waiting for details",
                }
            ],
        })
        safe_req = {k: v for k, v in request.items() if k not in ("items", "shipping")}
        if "parsed" in safe_req and isinstance(safe_req["parsed"], dict):
            safe_req["parsed"] = {k: v for k, v in safe_req["parsed"].items() if k not in ("items", "shipping")}
        btn_value = json.dumps(
            {
                "state": state,
                "requester": requester,
                "thread_ts": request.get("thread_ts"),
                "request": safe_req,
                "history": history or [],
            },
            default=str,
        )
        blocks.append({
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Fill in details", "emoji": True},
                    "action_id": "req_fill_details",
                    "value": btn_value,
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "This needs an EPIF", "emoji": True},
                    "action_id": "req_needs_epif",
                    "value": btn_value,
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Cancel", "emoji": True},
                    "style": "danger",
                    "action_id": "req_cancel",
                    "value": btn_value,
                }
            ]
        })
        return blocks

    if state == "superseded":
        blocks.append({
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": "Superseded by a newer EPIF below",
                }
            ],
        })
        return blocks

    # Primary (next-step) button for each non-terminal state.
    primary_buttons = {
        "posted": ("Approve", "req_approve"),
        "approved": ("Mark Processed", "req_processed"),
        "processed": ("Mark Confirmed", "req_confirmed"),
        "confirmed": ("Mark Delivered", "req_delivered"),
    }

    # Secondary destructive button shown alongside the primary (Decline or Cancel).
    # Not shown for processed/confirmed/delivered — cancel is refused after processed (ADR 0003 decision 5).
    secondary_buttons = {
        "posted": ("Decline", "req_decline"),
        "approved": ("Cancel", "req_cancel"),
    }

    if state in primary_buttons:
        btn_label, btn_action_id = primary_buttons[state]
        safe_req = {k: v for k, v in request.items() if k not in ("items", "shipping")}
        if "parsed" in safe_req and isinstance(safe_req["parsed"], dict):
            safe_req["parsed"] = {k: v for k, v in safe_req["parsed"].items() if k not in ("items", "shipping")}
        btn_value = json.dumps(
            {
                "state": state,
                "requester": requester,
                "thread_ts": request.get("thread_ts"),
                "request": safe_req,
                "history": history or [],
            },
            default=str,
        )
        elements = [
            {
                "type": "button",
                "text": {"type": "plain_text", "text": btn_label, "emoji": True},
                "style": "primary",
                "action_id": btn_action_id,
                "value": btn_value,
            }
        ]
        if state in secondary_buttons:
            sec_label, sec_action_id = secondary_buttons[state]
            elements.append({
                "type": "button",
                "text": {"type": "plain_text", "text": sec_label, "emoji": True},
                "style": "danger",
                "action_id": sec_action_id,
                "value": btn_value,
            })
        if state == "posted":
            source = request.get("source")
            if source == "epif":
                btn_items_label = "Edit items" if (items and len(items) > 0) else "Add items"
                elements.append({
                    "type": "button",
                    "text": {"type": "plain_text", "text": btn_items_label, "emoji": True},
                    "action_id": config.ACTION_REQ_ITEMS,
                    "value": btn_value,
                })
            elif source == "modal":
                elements.append({
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Edit", "emoji": True},
                    "action_id": config.ACTION_REQ_EDIT,
                    "value": btn_value,
                })
            picker_elem = {
                "type": "users_select",
                "action_id": config.ACTION_REQ_ASSIGN_SELECT,
                "placeholder": {"type": "plain_text", "text": "Assign a buyer (optional)"},
            }
            if assignee_id:
                picker_elem["initial_user"] = assignee_id
            elements.append(picker_elem)
        blocks.append({
            "type": "actions",
            "elements": elements,
        })

    return blocks


def build_items_view(
    channel: str,
    thread_ts: str,
    card_ts: str,
    items: list[dict] | None = None,
    shipping: float = 0.0,
    initial_text: str | None = None,
) -> dict:
    """Generate Block Kit modal for adding or editing line items on a purchase request."""
    if initial_text is None and items:
        initial_text = bom.format_line_items(items, shipping)

    element = {
        "type": "plain_text_input",
        "action_id": "action_line_items",
        "multiline": True,
        "placeholder": {
            "type": "plain_text",
            "text": "qty | name | part # | unit price | link | description\nshipping | 24.50",
        },
    }
    if initial_text:
        element["initial_value"] = initial_text

    blocks_list = [
        {
            "type": "input",
            "block_id": "block_line_items",
            "element": element,
            "label": {"type": "plain_text", "text": "Line items"},
            "hint": {
                "type": "plain_text",
                "text": (
                    "One item per line (pipe or tab separated): "
                    "qty | name | part # | unit price | link | description. "
                    "Optional line: shipping | <amount>"
                ),
            },
        }
    ]

    return {
        "type": "modal",
        "callback_id": config.ITEMS_CALLBACK_ID,
        "title": {"type": "plain_text", "text": "Line Items"[:24]},
        "submit": {"type": "plain_text", "text": "Save items"},
        "close": {"type": "plain_text", "text": "Cancel"},
        "private_metadata": json.dumps({
            "channel": channel,
            "thread_ts": thread_ts,
            "card_ts": card_ts,
        }),
        "blocks": blocks_list,
    }


def build_stage1_view(prefill_name_field: bool = False, resolved_name: str | None = None, user_id: str | None = None) -> dict:
    """Generate Screen 1 (Which path?) Block Kit modal."""
    vendors = sorted(roster.get_vendors() if hasattr(roster, "get_vendors") else config.WORKDAY_VENDORS)
    vendor_options = [
        {"text": {"type": "plain_text", "text": v[:75]}, "value": v}
        for v in vendors
    ]
    vendor_options.append({"text": {"type": "plain_text", "text": config.VENDOR_SUGGEST_OPTION[:75]}, "value": config.VENDOR_SUGGEST_OPTION})
    vendor_options.append({"text": {"type": "plain_text", "text": config.VENDOR_OTHER_OPTION[:75]}, "value": config.VENDOR_OTHER_OPTION})

    blocks = []
    if prefill_name_field:
        blocks.append({
            "type": "input",
            "block_id": "block_proposed_name",
            "element": {
                "type": "plain_text_input",
                "action_id": "proposed_name",
                "placeholder": {"type": "plain_text", "text": "e.g. Alex, Casey, Dylan"},
            },
            "label": {"type": "plain_text", "text": "What would you like your name to appear as?"},
        })

    blocks.append({
        "type": "context",
        "elements": [
            {
                "type": "mrkdwn",
                "text": "💡 *Fast path vs Full EPIF:* Listed vendors are pre-approved UW Workday punch-out vendors (skips EPIF paperwork). For any other vendor, choose *Not listed / other*.",
            }
        ],
    })

    blocks.append({
        "type": "input",
        "block_id": "block_vendor",
        "element": {
            "type": "static_select",
            "action_id": "vendor_select",
            "placeholder": {"type": "plain_text", "text": "Select punchout vendor or option"},
            "options": vendor_options,
        },
        "label": {"type": "plain_text", "text": "Who are you buying from?"},
    })

    blocks.append({
        "type": "input",
        "block_id": "block_vendor_custom",
        "optional": True,
        "element": {
            "type": "plain_text_input",
            "action_id": "vendor_custom",
            "placeholder": {"type": "plain_text", "text": "Enter vendor name"},
        },
        "label": {"type": "plain_text", "text": "Vendor Name (if Other or Suggested)"},
    })

    return {
        "type": "modal",
        "callback_id": config.STAGE1_CALLBACK_ID,
        "title": {"type": "plain_text", "text": "New Purchase"},
        "submit": {"type": "plain_text", "text": "Next"},
        "close": {"type": "plain_text", "text": "Cancel"},
        "private_metadata": json.dumps({"resolved_name": resolved_name, "user_id": user_id}),
        "blocks": blocks,
    }


NEAR_MISS_WARNING_BLOCK_ID = "block_near_miss_warning"


def with_near_miss_warning(view_blocks: list[dict], matched_vendor: str) -> list[dict]:
    """Return Screen 1's blocks with one near-miss warning under the vendor name field.

    WHY THIS EXISTS: ticket 35 / ADR 0007 decision 3. The warning has to travel in the
    same response that stores the warned name in private_metadata, and Slack's
    `errors` response cannot change private_metadata, so the warning is a block in an
    `update` response instead of a field error. Any earlier warning is dropped first:
    keeping the old block once left "Did you mean A?" showing after the requester
    typed a name close to B. Pure: returns a new list, never mutates its input.
    """
    warning = {
        "type": "context",
        "block_id": NEAR_MISS_WARNING_BLOCK_ID,
        "elements": [
            {
                "type": "mrkdwn",
                "text": (
                    f":warning: Did you mean *{matched_vendor}*? Pick it from the list — "
                    "it's a Workday vendor. Submit again to keep this as an EPIF order."
                ),
            }
        ],
    }
    kept = [b for b in view_blocks if b.get("block_id") != NEAR_MISS_WARNING_BLOCK_ID]
    for i, block in enumerate(kept):
        if block.get("block_id") == "block_vendor_custom":
            return kept[: i + 1] + [warning] + kept[i + 1 :]
    return [warning] + kept


def _select_initial_option(value: str | None, options: list) -> dict | None:
    """Return the matching initial_option dict for a static_select, or None."""
    if not value:
        return None
    for opt in options:
        if opt.get("value") == value:
            return opt
    return None


def build_stage2_view(meta: dict) -> dict:
    """Generate Screen 2 (Details) Block Kit modal shaped by Screen 1 route.

    When meta['is_edit'] is True, the view becomes an edit form:
    - callback_id switches to EDIT_CALLBACK_ID
    - title is 'Edit Request' and submit is 'Save changes'
    - all fields are pre-filled from meta values
    - asset ID and Name of System fields are included (required when the
      selected category needs them, validated at submit time)
    - vendor and route are shown as read-only context, not editable inputs

    Ticket 28: Line items box added with 1500-char cap.
    Ticket 32: Pre-fill / edit mode added.
    """
    is_edit = bool(meta.get("is_edit"))
    v_choice = meta.get("vendor_choice") or ""
    v_custom = meta.get("vendor_custom") or ""
    suggest_opt = getattr(config, "VENDOR_SUGGEST_OPTION", "Suggest a new vendor that was added to workday")
    other_opt = getattr(config, "VENDOR_OTHER_OPTION", "Not listed / other")
    if v_choice in (suggest_opt, other_opt) and v_custom:
        vendor_display = v_custom
    else:
        vendor_display = v_choice

    route = meta.get("route") or interview.route_vendor(v_choice)
    path_title = "Workday" if route == "workday" else "Full EPIF"
    header_context = f"📋 *Path:* {path_title} — {vendor_display}"
    if is_edit:
        header_context += "\n_Vendor and route are not editable. To change vendor, Decline and resubmit._"

    room_options = [
        {"text": {"type": "plain_text", "text": r}, "value": r}
        for r in sorted(config.VALID_DELIVERY_ROOMS)
    ]
    project_options = [
        {"text": {"type": "plain_text", "text": p}, "value": p}
        for p in sorted(config.VALID_PROJECT_IDS)
    ]
    fund_options = [
        {"text": {"type": "plain_text", "text": f}, "value": f}
        for f in sorted(config.VALID_FUNDS)
    ]

    category_display_list = getattr(config, "CATEGORY_DISPLAY_ORDER", [])
    if category_display_list:
        category_options = [
            {"text": {"type": "plain_text", "text": disp[:75]}, "value": val}
            for val, disp in category_display_list
        ]
    else:
        category_options = [
            {"text": {"type": "plain_text", "text": c[:75]}, "value": c}
            for c in sorted(set(config.CHECKBOX_TO_CATEGORY.values()))
        ]

    def _text_elem(action_id, placeholder, max_len=None, multiline=False, prefill_key=None):
        """Build a plain_text_input element, optionally pre-filled."""
        elem = {
            "type": "plain_text_input",
            "action_id": action_id,
            "placeholder": {"type": "plain_text", "text": placeholder},
        }
        if multiline:
            elem["multiline"] = True
        if max_len:
            elem["max_length"] = max_len
        if is_edit and prefill_key:
            val = meta.get(prefill_key)
            if val is not None:
                elem["initial_value"] = str(val)
        return elem

    def _select_elem(action_id, placeholder, options, prefill_key=None):
        """Build a static_select element, optionally pre-filled."""
        elem = {
            "type": "static_select",
            "action_id": action_id,
            "placeholder": {"type": "plain_text", "text": placeholder},
            "options": options,
        }
        if is_edit and prefill_key:
            initial = _select_initial_option(meta.get(prefill_key), options)
            if initial:
                elem["initial_option"] = initial
        return elem

    # Date picker initial_date: today for new, stored value for edit
    date_initial = datetime.now().strftime("%Y-%m-%d")
    if is_edit and meta.get("date_of_purchase"):
        raw_date = str(meta["date_of_purchase"])
        # Stored as "YYYY-MM-DD" (isoformat) or a date object str
        if len(raw_date) >= 10 and raw_date[4] == "-":
            date_initial = raw_date[:10]

    blocks = [
        {
            "type": "context",
            "block_id": "block_path_context",
            "elements": [{"type": "mrkdwn", "text": header_context}],
        },
        {
            "type": "input",
            "block_id": "block_item_description",
            "element": _text_elem(
                "item_description",
                "e.g. Box of Nitrile Gloves (Medium)",
                max_len=getattr(config, "MAX_ITEM_DESCRIPTION_LEN", 150),
                prefill_key="item_description",
            ),
            "label": {"type": "plain_text", "text": "Item Description (What is being purchased)"},
        },
        {
            "type": "input",
            "block_id": "block_purpose",
            "element": _text_elem(
                "purpose",
                "Why needed for research, and product URL (https://...)",
                max_len=getattr(config, "MAX_PURPOSE_LEN", 900),
                multiline=True,
                prefill_key="purpose",
            ),
            "label": {"type": "plain_text", "text": "Purpose / Why Necessary & Link"},
        },
        {
            "type": "input",
            "block_id": "block_link",
            "optional": True,
            "element": _text_elem(
                "link",
                "https://... (vendor product page or quote link)",
                prefill_key="link",
            ),
            "label": {"type": "plain_text", "text": "Product Page / Quote Link"},
        },
        {
            "type": "input",
            "block_id": "block_total_price",
            "element": _text_elem(
                "total_price",
                "e.g. 145.50 or $145.50",
                prefill_key="total_price",
            ),
            "label": {"type": "plain_text", "text": "Total Price ($ Amount)"},
        },
        {
            "type": "input",
            "block_id": "block_line_items",
            "optional": True,
            "element": {
                "type": "plain_text_input",
                "action_id": "line_items",
                "multiline": True,
                "max_length": getattr(config, "MAX_LINE_ITEMS_LEN", 1500),
                "placeholder": {
                    "type": "plain_text",
                    "text": "qty | name | part # | unit price | link | description\nshipping | 24.50",
                },
                **({"initial_value": meta["line_items"]} if meta.get("line_items") else {}),
            },
            "label": {"type": "plain_text", "text": "Line items (optional)"},
            "hint": {
                "type": "plain_text",
                "text": (
                    "One item per line (pipe or tab separated): "
                    "qty | name | part # | unit price | link | description. "
                    "Optional line: shipping | <amount>"
                ),
            },
        },
        {
            "type": "input",
            "block_id": "block_vendor_contact_name",
            "element": _text_elem(
                "vendor_contact_name",
                "Vendor contact name or rep",
                prefill_key="vendor_contact_name",
            ),
            "label": {"type": "plain_text", "text": "Vendor Contact Name"},
        },
        {
            "type": "input",
            "block_id": "block_vendor_contact_email",
            "element": _text_elem(
                "vendor_contact_email",
                "e.g. rep@vendor.com or info@vendor.com",
                prefill_key="vendor_contact_email",
            ),
            "label": {"type": "plain_text", "text": "Vendor Contact Email"},
        },
        {
            "type": "input",
            "block_id": "block_date_of_purchase",
            "element": {
                "type": "datepicker",
                "action_id": "date_of_purchase",
                "initial_date": date_initial,
                "placeholder": {"type": "plain_text", "text": "Select date"},
            },
            "label": {"type": "plain_text", "text": "Date of Request / Purchase"},
        },
        {
            "type": "input",
            "block_id": "block_delivery_room",
            "element": _select_elem(
                "delivery_room",
                "Select delivery room",
                room_options,
                prefill_key="delivery_room",
            ),
            "label": {"type": "plain_text", "text": "Delivery Room (Campus Address)"},
        },
        {
            "type": "input",
            "block_id": "block_project_id",
            "element": _select_elem(
                "project_id",
                "Select Project ID",
                project_options,
                prefill_key="project_id",
            ),
            "label": {"type": "plain_text", "text": "Project ID Number"},
        },
        {
            "type": "input",
            "block_id": "block_fund",
            "element": _select_elem(
                "fund",
                "Select Fund",
                fund_options,
                prefill_key="fund",
            ),
            "label": {"type": "plain_text", "text": "Fund Number"},
        },
        {
            "type": "input",
            "block_id": "block_category",
            "element": _select_elem(
                "category",
                "Select Category",
                category_options,
                prefill_key="category",
            ),
            "label": {"type": "plain_text", "text": "Accounting Category"},
        },
    ]

    if route == "epif":
        pm_options = [
            {"text": {"type": "plain_text", "text": "P-card"}, "value": "P-card"},
            {"text": {"type": "plain_text", "text": "Req/PO"}, "value": "Req/PO"},
        ]
        blocks.append({
            "type": "input",
            "block_id": "block_payment_method",
            "element": _select_elem(
                "payment_method",
                "Select payment method",
                pm_options,
                prefill_key="payment_method",
            ),
            "label": {"type": "plain_text", "text": "Payment Method"},
        })

    # Edit mode: always include asset fields (required at submit when category needs them)
    if is_edit:
        blocks.append({
            "type": "input",
            "block_id": "block_asset_id",
            "optional": True,
            "element": _text_elem(
                "asset_id",
                "e.g. TAG-12345 or Fab #4670",
                prefill_key="asset_id",
            ),
            "label": {"type": "plain_text", "text": "Asset ID / Fabrication # (required for Fabrication category)"},
        })
        blocks.append({
            "type": "input",
            "block_id": "block_name_of_system",
            "optional": True,
            "element": _text_elem(
                "name_of_system",
                "e.g. Target Chamber, Laser System",
                prefill_key="name_of_system",
            ),
            "label": {"type": "plain_text", "text": "Name of System (required for Fabrication category)"},
        })

    if is_edit:
        callback_id = config.EDIT_CALLBACK_ID
        title_text = "Edit Request"
        submit_text = "Save changes"
    else:
        callback_id = config.STAGE2_CALLBACK_ID
        title_text = "Purchase Details"
        submit_text = "Continue"

    return {
        "type": "modal",
        "callback_id": callback_id,
        "title": {"type": "plain_text", "text": title_text},
        "submit": {"type": "plain_text", "text": submit_text},
        "close": {"type": "plain_text", "text": "Cancel"},
        "private_metadata": json.dumps(meta),
        "blocks": blocks,
    }


def build_stage3_view(meta: dict) -> dict:
    """Generate Screen 3 (Fabrication details) Block Kit modal for category 4670."""
    return {
        "type": "modal",
        "callback_id": config.STAGE3_CALLBACK_ID,
        "title": {"type": "plain_text", "text": "Fabrication Info"},
        "submit": {"type": "plain_text", "text": "Submit Request"},
        "close": {"type": "plain_text", "text": "Cancel"},
        "private_metadata": json.dumps(meta),
        "blocks": [
            {
                "type": "context",
                "block_id": "block_fab_context",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": "🔬 *Fabrication Component:* This is the asset/fabrication number of the system the part belongs to — ask Charlie or check the fabrication paperwork.",
                    }
                ],
            },
            {
                "type": "input",
                "block_id": "block_asset_id",
                "element": {
                    "type": "plain_text_input",
                    "action_id": "asset_id",
                    "placeholder": {"type": "plain_text", "text": "e.g. TAG-12345 or Fab #4670"},
                },
                "label": {"type": "plain_text", "text": "Asset ID / Fabrication #"},
            },
            {
                "type": "input",
                "block_id": "block_name_of_system",
                "element": {
                    "type": "plain_text_input",
                    "action_id": "name_of_system",
                    "placeholder": {"type": "plain_text", "text": "e.g. Target Chamber, Laser System"},
                },
                "label": {"type": "plain_text", "text": "Name of System"},
            },
        ],
    }


def build_roster_set_name_view(
    user_id: str,
    current_name: str | None = None,
    channel_id: str | None = None,
) -> dict:
    """Build the /roster-set-name Block Kit modal view.

    WHY THIS EXISTS:
    ----------------
    Ticket 19: Pure Block Kit builder for the roster-set-name modal.
    Shows the submitter's current registered name (or that they are not registered yet),
    without printing the hardcoded lab roster list which was invalidated when
    get_valid_requesters() was changed to read the roster directly.
    """
    if current_name:
        status_text = f"You are currently registered in the roster as *{current_name}*."
    else:
        status_text = "You are not yet registered in the lab roster."

    meta = {"user_id": user_id}
    if channel_id:
        meta["channel_id"] = channel_id

    return {
        "type": "modal",
        "callback_id": config.ROSTER_SET_NAME_CALLBACK_ID,
        "title": {"type": "plain_text", "text": "Set Roster Name"},
        "submit": {"type": "plain_text", "text": "Submit"},
        "close": {"type": "plain_text", "text": "Cancel"},
        "private_metadata": json.dumps(meta),
        "blocks": [
            {
                "type": "context",
                "block_id": "block_roster_status",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": f"💡 {status_text}",
                    }
                ],
            },
            {
                "type": "input",
                "block_id": "block_proposed_name",
                "element": {
                    "type": "plain_text_input",
                    "action_id": "proposed_name",
                    "placeholder": {"type": "plain_text", "text": "e.g. First Last"},
                },
                "label": {"type": "plain_text", "text": "Your Name in Lab Requester List"},
            },

        ],
    }



def build_workday_details_view(channel: str, thread_ts: str, card_ts: str, vendors: list[str]) -> dict:
    """Generate Block Kit modal for filling Workday details from a bare-thread approval."""
    vendor_options = [{"text": {"type": "plain_text", "text": v}, "value": v} for v in vendors]

    blocks = [
        {
            "type": "input",
            "block_id": "block_vendor",
            "label": {"type": "plain_text", "text": "Vendor"},
            "element": {
                "type": "static_select",
                "action_id": "vendor",
                "placeholder": {"type": "plain_text", "text": "Select a vendor"},
                "options": vendor_options,
            },
        },
        {
            "type": "input",
            "block_id": "block_item_description",
            "label": {"type": "plain_text", "text": "What is being purchased?"},
            "element": {"type": "plain_text_input", "action_id": "item_description"},
        },
        {
            "type": "input",
            "block_id": "block_purpose",
            "label": {"type": "plain_text", "text": "Why is this being purchased?"},
            "element": {"type": "plain_text_input", "action_id": "purpose", "multiline": True},
        },
        {
            "type": "input",
            "block_id": "block_link",
            "label": {"type": "plain_text", "text": "Link to item (optional)"},
            "optional": True,
            "element": {"type": "plain_text_input", "action_id": "link"},
        },
        {
            "type": "input",
            "block_id": "block_total_price",
            "label": {"type": "plain_text", "text": "Total price including shipping ($)"},
            "element": {"type": "plain_text_input", "action_id": "total_price"},
        },
        {
            "type": "input",
            "block_id": "block_date_of_purchase",
            "label": {"type": "plain_text", "text": "Date of Purchase"},
            "element": {"type": "datepicker", "action_id": "date_of_purchase", "initial_date": datetime.now().strftime("%Y-%m-%d")},
        },
        {
            "type": "input",
            "block_id": "block_delivery_room",
            "label": {"type": "plain_text", "text": "Delivery Room"},
            "element": {"type": "plain_text_input", "action_id": "delivery_room"},
        },
        {
            "type": "input",
            "block_id": "block_project_id",
            "label": {"type": "plain_text", "text": "Project ID"},
            "element": {"type": "plain_text_input", "action_id": "project_id"},
        },
        {
            "type": "input",
            "block_id": "block_fund",
            "label": {"type": "plain_text", "text": "Fund"},
            "element": {"type": "plain_text_input", "action_id": "fund"},
        },
        {
            "type": "input",
            "block_id": "block_category",
            "label": {"type": "plain_text", "text": "Category"},
            "element": {
                "type": "static_select",
                "action_id": "category",
                "options": [
                    {"text": {"type": "plain_text", "text": "Lab Consumable"}, "value": "Lab Consumable"},
                    {"text": {"type": "plain_text", "text": "Equipment / Software"}, "value": "Equipment / Software"},
                    {"text": {"type": "plain_text", "text": "Office Supply"}, "value": "Office Supply"},
                    {"text": {"type": "plain_text", "text": "Service"}, "value": "Service"},
                    {"text": {"type": "plain_text", "text": "Fabrication Component"}, "value": "Fabrication Component"},
                ],
                "initial_option": {"text": {"type": "plain_text", "text": "Lab Consumable"}, "value": "Lab Consumable"},
            },
        },
        {
            "type": "input",
            "block_id": "block_line_items",
            "optional": True,
            "label": {"type": "plain_text", "text": "Line items (optional)"},
            "hint": {"type": "plain_text", "text": "Add line items with qty, unit, name, part, price, link. Last line must be shipping if not $0."},
            "element": {
                "type": "plain_text_input",
                "action_id": "line_items",
                "multiline": True,
                "placeholder": {"type": "plain_text", "text": "2 EA | Flask | FL-1 | 10.00\nShipping | 5.00"},
            },
        },
    ]

    return {
        "type": "modal",
        "callback_id": "modal_workday_details",
        "title": {"type": "plain_text", "text": "Workday Order Details"},
        "submit": {"type": "plain_text", "text": "Submit"},
        "close": {"type": "plain_text", "text": "Cancel"},
        "private_metadata": json.dumps({"channel_id": channel, "thread_ts": thread_ts, "card_ts": card_ts}),
        "blocks": blocks,
    }
