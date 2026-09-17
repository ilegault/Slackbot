"""Block Kit builders and view definitions for Slack UI.

WHY THIS EXISTS:
----------------
Constructs Slack Block Kit dictionaries and view payloads for App Home, modals,
and message cards. Pure presentation layer that takes dictionaries/metadata
and returns list/dict Block Kit structures.
ADR 0005: The posted card carries a buyer picker (users_select) in the same
actions block as Approve and Decline, allowing approvers to pick a buyer directly
without typing a mention.

Imports:
    - config, interview, roster, text_rules
May NOT import:
    - Slack SDK / Bolt (holds no client, makes no API calls)
    - storage writers (log_writer, queue_worker)
    - lifecycle/ops handlers
"""
import json
from datetime import datetime

try:
    from . import config, interview, roster
except ImportError:
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
    "• Click the action buttons on the request message: *Approve* or *Decline* (approvers), "
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
    "• `@Purchasing logs [n]` — _(Admin Only)_ View recent bot log entries.\n"
    "• `@Purchasing update` — _(Admin Only)_ Pull latest git code and restart bot.\n"
    "• `@Purchasing restart` — _(Admin Only)_ Gracefully restart the bot process.\n"
    "• `@Purchasing promote-admin @user` — _(Admin Only)_ Propose promoting a user to bot administrator.\n"
    "• `@Purchasing add-approver @user` — _(Admin Only)_ Add a user to the approver list.\n"
    "• `@Purchasing remove-approver @user` — _(Admin Only)_ Remove a user from the approver list.\n"
    "• `@Purchasing add-buyer @user` — _(Admin Only)_ Add a user to the buyers list.\n"
    "• `@Purchasing remove-buyer @user` — _(Admin Only)_ Remove a user from the buyers list.\n"
    "• `@Purchasing remove vendor <name>` — _(Admin Only)_ Remove a vendor from the Workday catalog list."
)

_SLASH_COMMANDS = (
    "• `/new-purchase` — Open the guided purchasing modal to submit an order request.\n"
    "• `/purchasing-help` — Display this help and command reference.\n"
    "• `/blank-template` — Download the blank EPIF PDF template and instructions.\n"
    "• `/roster-list` — List registered lab members and Workday catalog vendors.\n"
    "• `/roster-set-name` — Link your Slack user account to your lab name in the roster."
)

# --- App Home Block Kit View --------------------------------------------------


def build_app_home_view() -> dict:
    """Build the App Home Block Kit view dict.

    WHY A FUNCTION NOT A CONSTANT: The shared text constants (_BUTTON_LIST,
    _STAGE_DEFINITIONS, etc.) must be interpolated into the mrkdwn blocks at
    build time.  A static dict cannot hold a reference to a module-level string
    that hasn't been assigned yet, and string concatenation in a dict literal
    is fragile to maintain.  The one caller (handle_app_home_opened) calls this
    once per event, so there is no performance concern.
    """
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


def build_request_blocks(state: str, request: dict, history: list | None = None) -> list:
    """Generate Block Kit blocks for a purchase request at a given lifecycle state.

    States: posted -> approved -> processed -> confirmed -> delivered
    Terminal states with no buttons: declined, cancelled, delivered.
    """
    parsed = request.get("parsed", request)
    requester = request.get("requester")
    user_id = request.get("user_id")
    is_pending_name = request.get("is_pending_name", False)

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
        btn_value = json.dumps(
            {
                "state": state,
                "requester": requester,
                "thread_ts": request.get("thread_ts"),
                "request": request,
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


def build_stage2_view(meta: dict) -> dict:
    """Generate Screen 2 (Details) Block Kit modal shaped by Screen 1 route."""
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

    blocks = [
        {
            "type": "context",
            "block_id": "block_path_context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": header_context,
                }
            ],
        },
        {
            "type": "input",
            "block_id": "block_item_description",
            "element": {
                "type": "plain_text_input",
                "action_id": "item_description",
                "max_length": getattr(config, "MAX_ITEM_DESCRIPTION_LEN", 150),
                "placeholder": {"type": "plain_text", "text": "e.g. Box of Nitrile Gloves (Medium)"},
            },
            "label": {"type": "plain_text", "text": "Item Description (What is being purchased)"},
        },
        {
            "type": "input",
            "block_id": "block_purpose",
            "element": {
                "type": "plain_text_input",
                "multiline": True,
                "action_id": "purpose",
                "max_length": getattr(config, "MAX_PURPOSE_LEN", 900),
                "placeholder": {"type": "plain_text", "text": "Why needed for research, and product URL (https://...)"},
            },
            "label": {"type": "plain_text", "text": "Purpose / Why Necessary & Link"},
        },
        {
            "type": "input",
            "block_id": "block_link",
            "optional": True,
            "element": {
                "type": "plain_text_input",
                "action_id": "link",
                "placeholder": {"type": "plain_text", "text": "https://... (vendor product page or quote link)"},
            },
            "label": {"type": "plain_text", "text": "Product Page / Quote Link"},
        },
        {
            "type": "input",
            "block_id": "block_total_price",
            "element": {
                "type": "plain_text_input",
                "action_id": "total_price",
                "placeholder": {"type": "plain_text", "text": "e.g. 145.50 or $145.50"},
            },
            "label": {"type": "plain_text", "text": "Total Price ($ Amount)"},
        },
        {
            "type": "input",
            "block_id": "block_vendor_contact_name",
            "element": {
                "type": "plain_text_input",
                "action_id": "vendor_contact_name",
                "placeholder": {"type": "plain_text", "text": "Vendor contact name or rep"},
            },
            "label": {"type": "plain_text", "text": "Vendor Contact Name"},
        },
        {
            "type": "input",
            "block_id": "block_vendor_contact_email",
            "element": {
                "type": "plain_text_input",
                "action_id": "vendor_contact_email",
                "placeholder": {"type": "plain_text", "text": "e.g. rep@vendor.com or info@vendor.com"},
            },
            "label": {"type": "plain_text", "text": "Vendor Contact Email"},
        },
        {
            "type": "input",
            "block_id": "block_date_of_purchase",
            "element": {
                "type": "datepicker",
                "action_id": "date_of_purchase",
                "initial_date": datetime.now().strftime("%Y-%m-%d"),
                "placeholder": {"type": "plain_text", "text": "Select date"},
            },
            "label": {"type": "plain_text", "text": "Date of Request / Purchase"},
        },
        {
            "type": "input",
            "block_id": "block_delivery_room",
            "element": {
                "type": "static_select",
                "action_id": "delivery_room",
                "placeholder": {"type": "plain_text", "text": "Select delivery room"},
                "options": room_options,
            },
            "label": {"type": "plain_text", "text": "Delivery Room (Campus Address)"},
        },
        {
            "type": "input",
            "block_id": "block_project_id",
            "element": {
                "type": "static_select",
                "action_id": "project_id",
                "placeholder": {"type": "plain_text", "text": "Select Project ID"},
                "options": project_options,
            },
            "label": {"type": "plain_text", "text": "Project ID Number"},
        },
        {
            "type": "input",
            "block_id": "block_fund",
            "element": {
                "type": "static_select",
                "action_id": "fund",
                "placeholder": {"type": "plain_text", "text": "Select Fund"},
                "options": fund_options,
            },
            "label": {"type": "plain_text", "text": "Fund Number"},
        },
        {
            "type": "input",
            "block_id": "block_category",
            "element": {
                "type": "static_select",
                "action_id": "category",
                "placeholder": {"type": "plain_text", "text": "Select Category"},
                "options": category_options,
            },
            "label": {"type": "plain_text", "text": "Accounting Category"},
        },
    ]

    if route == "epif":
        blocks.append({
            "type": "input",
            "block_id": "block_payment_method",
            "element": {
                "type": "static_select",
                "action_id": "payment_method",
                "placeholder": {"type": "plain_text", "text": "Select payment method"},
                "options": [
                    {"text": {"type": "plain_text", "text": "P-card"}, "value": "P-card"},
                    {"text": {"type": "plain_text", "text": "Req/PO"}, "value": "Req/PO"},
                ],
            },
            "label": {"type": "plain_text", "text": "Payment Method"},
        })

    return {
        "type": "modal",
        "callback_id": config.STAGE2_CALLBACK_ID,
        "title": {"type": "plain_text", "text": "Purchase Details"},
        "submit": {"type": "plain_text", "text": "Continue"},
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
