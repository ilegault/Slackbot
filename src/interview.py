"""Purchasing interview routing, modal data conversion, and FAQ engine.

Pure Python logic separated from Slack API plumbing for testability.
"""
from typing import Any, Dict, Optional

try:
    from . import config
    from . import epif_parser
except ImportError:
    import config
    import epif_parser

try:
    from . import roster
except ImportError:
    try:
        import roster
    except ImportError:
        roster = None


def get_available_vendors() -> set[str]:
    """Get the set of active pre-approved Workday punchout/catalog vendors."""
    if roster is not None and hasattr(roster, "get_vendors"):
        return set(roster.get_vendors())
    return set(getattr(config, "WORKDAY_VENDORS", set()))


def route_vendor(vendor_choice: str) -> str:
    """Route a vendor selection to either 'workday' or 'epif'.

    Returns 'workday' if vendor_choice is in the Workday punchout list,
    otherwise 'epif' (including for 'Suggest a new vendor', 'Not listed / other', or custom vendors).
    """
    if vendor_choice in get_available_vendors():
        return "workday"
    return "epif"


def build_parsed_from_modal(values: Dict[str, Any], vendor_choice: str) -> Dict[str, Any]:
    """Convert extracted modal state values into a dict matching epif_parser.parse_epif().

    Expects values dict with keys:
    - item_description (str)
    - purpose (str)
    - link (optional str, or extracted from purpose)
    - total_price (str or float/int)
    - vendor_contact_name (optional str)
    - vendor_contact_email (str)
    - date_of_purchase (str YYYY-MM-DD, MM/DD/YY or date object)
    - name_of_system (optional str)
    - delivery_room (str)
    - project_id (str)
    - fund (str)
    - asset_id (optional str)
    - category (str)
    - payment_method (optional str, required if non-workday)
    - suggested_vendor / other_vendor (optional str if vendor_choice was suggest/other)
    """
    purpose = str(values.get("purpose") or "").strip()
    link = values.get("link") or epif_parser.first_url(purpose)

    raw_price = values.get("total_price")
    if raw_price is None:
        price_num = None
        price_raw = ""
    elif isinstance(raw_price, (int, float)):
        price_num = float(raw_price)
        price_raw = str(raw_price)
    else:
        price_raw = str(raw_price).strip()
        price_num = epif_parser.parse_money(price_raw)

    raw_date = values.get("date_of_purchase")
    if isinstance(raw_date, str):
        parsed_date = epif_parser.parse_date(raw_date)
    else:
        parsed_date = raw_date

    # Determine final vendor string
    suggest_opt = getattr(config, "VENDOR_SUGGEST_OPTION", "Suggest a new vendor")
    other_opt = getattr(config, "VENDOR_OTHER_OPTION", "Not listed / other")
    if vendor_choice == suggest_opt:
        custom_v = str(values.get("suggested_vendor") or values.get("custom_vendor") or "").strip()
        final_vendor = custom_v if custom_v else suggest_opt
    elif vendor_choice == other_opt:
        custom_v = str(values.get("other_vendor") or values.get("custom_vendor") or "").strip()
        final_vendor = custom_v if custom_v else other_opt
    else:
        final_vendor = vendor_choice.strip()

    # Determine payment method based on routing
    routing = route_vendor(vendor_choice)
    if routing == "workday":
        payment_method = getattr(config, "WORKDAY_PAYMENT_METHOD", "Workday")
    else:
        payment_method = values.get("payment_method") or None

    category = values.get("category")
    category_error = None if category else "no EPIF category box is ticked"

    return {
        "raw_fields": values.get("raw_fields", {}),
        "item_description": str(values.get("item_description") or "").strip(),
        "purpose": purpose,
        "link": link,
        "total_price": price_num,
        "total_price_raw": price_raw,
        "vendor": final_vendor,
        "vendor_contact_name": str(values.get("vendor_contact_name") or "").strip(),
        "vendor_contact_email": str(values.get("vendor_contact_email") or "").strip(),
        "date_of_purchase": parsed_date,
        "name_of_system": str(values.get("name_of_system") or "").strip(),
        "delivery_room": str(values.get("delivery_room") or "").strip(),
        "project_id": str(values.get("project_id") or "").strip(),
        "fund": str(values.get("fund") or "").strip(),
        "asset_id": str(values.get("asset_id") or "").strip(),
        "pi_of_funding": str(values.get("pi_of_funding") or "").strip(),
        "end_user": str(values.get("end_user") or "").strip(),
        "category": category,
        "category_error": category_error,
        "payment_method": payment_method,
    }


FAQ_ANSWERS: Dict[str, str] = {
    "project id": (
        "A Project ID (like `PG000025831`) specifies the UW-Madison accounting project that funds "
        "your purchase. Check with your lab mentor or Charlie if you are unsure which one to select."
    ),
    "fund": (
        "The Fund number (e.g. `133`, `150`, `233`) identifies the specific grant type or funding "
        "source. Most lab purchases use Fund `133` or `150`."
    ),
    "category": (
        "The Category classifies what kind of item you are buying for university accounting "
        "(e.g. `Research/Lab Supplies (3105)`, `Software`, `Standalone Equipment >$5k (4602)`)."
    ),
    "delivery room": (
        "This is the physical lab room where the package should be delivered on campus "
        "(e.g. `ERB 212` or `ERB 839`)."
    ),
    "p-card": (
        "A P-card (Purchasing Card) is a university credit card used for direct purchases. "
        "Non-catalog and out-of-network vendor orders typically use a P-card."
    ),
    "req/po": (
        "A Req/PO (Purchase Order) is used when a vendor requires an official university requisition "
        "or purchase order before invoicing."
    ),
    "req po": (
        "A Req/PO (Purchase Order) is used when a vendor requires an official university requisition "
        "or purchase order before invoicing."
    ),
    "asset id": (
        "An Asset ID is an optional university inventory tag number. You only need this if you are "
        "purchasing an upgrade or replacement part for existing tagged lab equipment."
    ),
    "what happens after": (
        "After submitting, your request is posted to the purchasing channel for Charlie's approval. "
        "Once approved, it is logged to `Purchasing-Log.xlsx`, and a grad student buyer (or you) "
        "will place the order in Workday/ShopUW+."
    ),
}

QUESTION_MARKERS = ("?", "what is", "what's", "explain")


def match_faq(text: str) -> Optional[str]:
    """Return matching FAQ answer if text looks like a question and matches a known topic.

    Stateless: returns None if text is not a question or no topic matches.
    """
    if not text:
        return None
    text_lower = text.lower()
    if not any(marker in text_lower for marker in QUESTION_MARKERS):
        return None

    for topic, answer in FAQ_ANSWERS.items():
        if topic in text_lower:
            return answer
    return None
