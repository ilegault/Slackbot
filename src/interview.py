"""Purchasing interview routing, modal data conversion, and FAQ engine.

Pure Python logic separated from Slack API plumbing for testability.
"""
import difflib
import re
from typing import Any, Dict, Optional

try:
    from . import config, epif_parser
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


def needs_asset_details(category: Optional[str]) -> bool:
    """Return True if category requires Asset ID and Name of System (Screen 3)."""
    if not category:
        return False
    required_cats = getattr(config, "ASSET_REQUIRED_CATEGORIES", {"Fabrication Component (4670) > $200"})
    return category in required_cats


def _normalize_vendor(name: str) -> str:
    # Lowercase, remove punctuation
    name = name.lower()
    name = re.sub(r'[^\w\s]', '', name)

    # Remove multiple spaces to ensure single spaces between words
    name = re.sub(r'\s+', ' ', name).strip()

    # Drop trailing suffixes
    suffixes = r'\s+(inc|llc|ltd|co|corp|corporation|company)$'
    name = re.sub(suffixes, '', name)

    # Remove all remaining spaces for final comparison
    name = re.sub(r'\s+', '', name)
    return name

def check_near_miss_vendor(typed_name: str, listed_vendors: set[str]) -> str | None:
    """Check if the typed vendor name is a near miss for any listed vendor.

    WHY THIS EXISTS: If a user types a vendor name on the EPIF path that is already
    in Workday, we want to warn them so they switch to the Workday path. We do this
    by dropping common suffixes (Inc, LLC, etc.) and checking for >0.85 SequenceMatcher
    similarity (see ADR 0007).

    Returns the listed vendor name if a near miss is found, otherwise None.
    """
    if not typed_name:
        return None

    norm_typed = _normalize_vendor(typed_name)
    if not norm_typed:
        return None

    best_match = None
    best_ratio = 0.0

    for vendor in listed_vendors:
        norm_vendor = _normalize_vendor(vendor)
        if norm_typed == norm_vendor:
            return vendor

        ratio = difflib.SequenceMatcher(None, norm_typed, norm_vendor).ratio()
        threshold = getattr(config, "NEAR_MISS_VENDOR_RATIO", 0.85)
        if ratio >= threshold and ratio > best_ratio:
            best_match = vendor
            best_ratio = ratio

    return best_match

def validate_stage1(vendor_choice: str, vendor_custom: str) -> Dict[str, str]:
    """Validate Stage 1 inputs. Returns {block_id: error_message} dict (empty if valid)."""
    errors: Dict[str, str] = {}
    suggest_opt = getattr(config, "VENDOR_SUGGEST_OPTION", "Suggest a new vendor that was added to workday")
    other_opt = getattr(config, "VENDOR_OTHER_OPTION", "Not listed / other")
    if vendor_choice in (suggest_opt, other_opt) and not str(vendor_custom or "").strip():
        errors["block_vendor_custom"] = "Please enter the vendor name."
    return errors


def build_parsed_from_stages(
    stage1: Dict[str, Any],
    stage2: Dict[str, Any],
    stage3: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Convert accumulated stage answers into a dict matching epif_parser.parse_epif().

    Returns exactly 19 keys matching the AcroForm parser.
    """
    purpose = str(stage2.get("purpose") or "").strip()
    raw_link = stage2.get("link")
    link = str(raw_link).strip() if (raw_link and str(raw_link).strip()) else epif_parser.first_url(purpose)

    raw_price = stage2.get("total_price")
    if raw_price is None:
        price_num = None
        price_raw = ""
    elif isinstance(raw_price, (int, float)):
        price_num = float(raw_price)
        price_raw = str(raw_price)
    else:
        price_raw = str(raw_price).strip()
        price_num = epif_parser.parse_money(price_raw)

    raw_date = stage2.get("date_of_purchase")
    if isinstance(raw_date, str):
        parsed_date = epif_parser.parse_date(raw_date)
    else:
        parsed_date = raw_date

    # Determine final vendor name
    vendor_choice = str(stage1.get("vendor_choice") or "").strip()
    suggest_opt = getattr(config, "VENDOR_SUGGEST_OPTION", "Suggest a new vendor that was added to workday")
    other_opt = getattr(config, "VENDOR_OTHER_OPTION", "Not listed / other")
    if vendor_choice in (suggest_opt, other_opt):
        custom_v = str(stage1.get("vendor_custom") or "").strip()
        final_vendor = custom_v if custom_v else vendor_choice
    else:
        final_vendor = vendor_choice

    # Determine payment method based on routing
    routing = stage1.get("route") or route_vendor(vendor_choice)
    if routing == "workday":
        payment_method = getattr(config, "WORKDAY_PAYMENT_METHOD", "Workday")
    else:
        payment_method = stage2.get("payment_method") or None

    category = stage2.get("category")
    category_error = None if category else "no EPIF category box is ticked"

    asset_id = str(stage3.get("asset_id") or "").strip() if stage3 else ""
    name_of_system = str(stage3.get("name_of_system") or "").strip() if stage3 else ""

    return {
        "raw_fields": {},
        "item_description": str(stage2.get("item_description") or "").strip(),
        "purpose": purpose,
        "link": link,
        "total_price": price_num,
        "total_price_raw": price_raw,
        "vendor": final_vendor,
        "vendor_contact_name": str(stage2.get("vendor_contact_name") or "").strip(),
        "vendor_contact_email": str(stage2.get("vendor_contact_email") or "").strip(),
        "date_of_purchase": parsed_date,
        "name_of_system": name_of_system,
        "delivery_room": str(stage2.get("delivery_room") or "").strip(),
        "project_id": str(stage2.get("project_id") or "").strip(),
        "fund": str(stage2.get("fund") or "").strip(),
        "asset_id": asset_id,
        "pi_of_funding": "",
        "end_user": "",
        "category": category,
        "category_error": category_error,
        "payment_method": payment_method,
    }

FAQ_ANSWERS: Dict[str, str] = {
    "workday": (
        "Workday punch-out vendors (like Fisher Scientific, Dell, Apple) are pre-approved campus suppliers "
        "where orders skip manual EPIF paperwork. Non-catalog vendors require a standard EPIF form and "
        "P-card or Purchase Order (Req/PO)."
    ),
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
    "slash": (
        "If the action needs a target (like approving or updating a specific request), use the buttons on that message. "
        "If it doesn't (like starting a purchase or viewing help), use a slash command (`/`); `@p-bot` mentions are reserved for admin operations."
    ),
    "@p-bot": (
        "If the action needs a target (like approving or updating a specific request), use the buttons on that message. "
        "If it doesn't (like starting a purchase or viewing help), use a slash command (`/`); `@p-bot` mentions are reserved for admin operations."
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

