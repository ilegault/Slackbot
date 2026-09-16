"""Block Kit builders and view definitions for Slack UI.

WHY THIS EXISTS:
----------------
Constructs Slack Block Kit dictionaries and view payloads for App Home, modals,
and message cards. Pure presentation layer that takes dictionaries/metadata
and returns list/dict Block Kit structures.

Imports:
    - config, interview, roster, text_rules
May NOT import:
    - Slack SDK / Bolt (holds no client, makes no API calls)
    - storage writers (log_writer, queue_worker)
    - lifecycle/ops handlers
"""
from datetime import datetime
import json

try:
    from . import config
    from . import interview
    from . import roster
except ImportError:
    import config
    import interview
    import roster

# --- App Home Block Kit View --------------------------------------------------
APP_HOME_VIEW = {
    "type": "home",
    "blocks": [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": "Purchasing Bot: P-Bot",
                "emoji": True,
            },
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    "Welcome! *P-Bot* (`@p-bot`) automates logging, tracking, and archiving lab purchase requests directly to `Purchasing-Log.xlsx` and OneDrive.\n\n"
                    "> *Rule:* If the action needs a target, it's a button on that target. If it doesn't, it's a slash command."
                ),
            },
        },
        {
            "type": "divider",
        },
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": "🛒 Start Something",
                "emoji": True,
            },
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    "• `/new-purchase` — Open the guided purchasing modal to submit an order request.\n"
                    "• `/purchasing-help` — Display this help and command reference.\n"
                    "• `/blank-template` — Download the blank EPIF PDF template and instructions.\n"
                    "• `/roster-list` — List registered lab members and Workday catalog vendors.\n"
                    "• `/roster-set-name` — Link your Slack user account to your lab name in the roster."
                ),
            },
            "accessory": {
                "type": "button",
                "text": {
                    "type": "plain_text",
                    "text": "New Purchase Request",
                    "emoji": True,
                },
                "style": "primary",
                "action_id": "start_purchase_interview",
            },
        },
        {
            "type": "divider",
        },
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": "🔄 Move a Request Along",
                "emoji": True,
            },
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    "• Click the action buttons on the request message: *Approve* (approvers), *Claim* (grad buyers), *Mark Submitted*, *Mark Confirmed*, and *Mark Delivered*.\n"
                    "• Drop quote files or confirmation receipts directly into the thread to attach them."
                ),
            },
        },
        {
            "type": "divider",
        },
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": "⚙️ Admin Operations",
                "emoji": True,
            },
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    "• `@p-bot health` / `@p-bot status` — View system health, host uptime, and storage status.\n"
                    "• `@p-bot queue` — View Excel lock write queue status.\n"
                    "• `@p-bot logs [n]` — _(Admin Only)_ View recent bot log entries.\n"
                    "• `@p-bot update` — _(Admin Only)_ Pull latest git code and restart bot.\n"
                    "• `@p-bot restart` — _(Admin Only)_ Gracefully restart the bot process.\n"
                    "• `@p-bot promote-admin @user` — _(Admin Only)_ Propose promoting a user to bot administrator.\n"
                    "• `@p-bot add-approver @user` — _(Admin Only)_ Add a user to the approver list.\n"
                    "• `@p-bot remove-approver @user` — _(Admin Only)_ Remove a user from the approver list.\n"
                    "• `@p-bot remove vendor <name>` — _(Admin Only)_ Remove a vendor from the Workday catalog list."
                ),
            },
        },
        {
            "type": "divider",
        },
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": "⚠️ Common Issues & Troubleshooting",
                "emoji": True,
            },
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    "• *Excel Locked:* If `Purchasing-Log.xlsx` is open in Excel, P-Bot automatically queues your update and writes it immediately once closed.\n"
                    "• *Validation Rejections:* Make sure all required fields in the EPIF form are filled.\n"
                    "• *Price Mismatch:* If the final invoice or checkout total differs from the initial estimate, contact your purchase approver or lab buyer.\n"
                    "• *File Attachments:* For confirmations and quotes, ensure you attach the file in the request thread."
                ),
            },
        },
        {
            "type": "divider",
        },
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": "💬 Questions, Feedback & Complaints",
                "emoji": True,
            },
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
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": "Hirst Lab Automation • Report issues to Isaac Legault",
                },
            ],
        },
    ],
}


def get_help_message() -> str:
    """Command guide for the bot description and help command."""
    return (
        "🤖 *Hirst Lab Purchasing Bot (P-Bot)*\n\n"
        "> *Rule:* If the action needs a target, it's a button on that target. If it doesn't, it's a slash command.\n\n"
        "*🛒 Start something (Slash Commands):*\n"
        "• `/new-purchase` — Open the guided purchasing modal to submit an order request.\n"
        "• `/purchasing-help` — Display this help and command reference.\n"
        "• `/blank-template` — Download the blank EPIF PDF template and instructions.\n"
        "• `/roster-list` — List registered lab members and Workday catalog vendors.\n"
        "• `/roster-set-name` — Link your Slack user account to your lab name in the roster.\n\n"
        "*🔄 Move a request along (Buttons on the message):*\n"
        "• Click the action buttons on the request message: *Approve* (approvers), *Claim* (grad buyers), *Mark Submitted*, *Mark Confirmed*, and *Mark Delivered*.\n"
        "• Drop quote files or confirmation receipts directly into the thread to attach them.\n\n"
        "*⚙️ Admins (`@p-bot <command>`):*\n"
        "• `@p-bot health` / `@p-bot status` — View system health, host uptime, and storage status.\n"
        "• `@p-bot queue` — View Excel lock write queue status.\n"
        "• `@p-bot logs [n]` — View recent bot logs.\n"
        "• `@p-bot update` — Pull git updates and restart bot.\n"
        "• `@p-bot restart` — Restart the bot process.\n"
        "• `@p-bot promote-admin @user` — Propose promoting a user to bot administrator.\n"
        "• `@p-bot add-approver @user` — Add a user to the approver list.\n"
        "• `@p-bot remove-approver @user` — Remove a user from the approver list.\n"
        "• `@p-bot remove vendor <name>` — Remove a vendor from the Workday catalog list."
    )


def build_request_blocks(state: str, request: dict, history: list | None = None) -> list:
    """Generate Block Kit blocks for a purchase request at a given lifecycle state.

    States: posted -> approved -> claimed -> submitted -> confirmed -> delivered
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

    button_mapping = {
        "posted": ("Approve", "req_approve"),
        "approved": ("Claim", "req_claim"),
        "claimed": ("Mark Submitted", "req_submitted"),
        "submitted": ("Mark Confirmed", "req_confirmed"),
        "confirmed": ("Mark Delivered", "req_delivered"),
    }

    if state in button_mapping:
        btn_label, btn_action_id = button_mapping[state]
        btn_value = json.dumps({
            "state": state,
            "requester": requester,
            "thread_ts": request.get("thread_ts"),
            "request": request,
            "history": history or [],
        })
        blocks.append({
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": btn_label, "emoji": True},
                    "style": "primary",
                    "action_id": btn_action_id,
                    "value": btn_value,
                }
            ],
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
    suggest_opt = getattr(config, "VENDOR_SUGGEST_OPTION", "Suggest a new vendor")
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
                "placeholder": {"type": "plain_text", "text": "e.g. sales@vendor.com or info@vendor.com"},
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
