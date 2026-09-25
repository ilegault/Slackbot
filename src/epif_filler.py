"""Fills an EPIF template with values from a parsed request.

WHY THIS EXISTS: When a request takes the EPIF path, the bot generates the filled EPIF
instead of having the requester fill it manually (ADR 0007). This ensures data in Slack
exactly matches the PDF the buyer sends.

NOTE: Three fields in the EPIF template are not read or written by this module:
- `Signature1`: A `/Sig` digital-signature field. A person signs it outside the bot.
- `Telephone # for ?'s`: Pre-filled in the university template; kept as-is.
- `List of Other`: Left empty.
"""
import datetime
import io

from pypdf import PdfReader, PdfWriter
from pypdf.generic import BooleanObject, NameObject

try:
    from . import config
except ImportError:
    import config

def fill_epif(template_bytes: bytes, parsed: dict) -> bytes:
    """
    Given the committed blank EPIF template bytes and a parsed request dictionary,
    return the filled PDF bytes that `epif_parser.parse_epif` can read back to the same values.
    """
    reader = PdfReader(io.BytesIO(template_bytes))

    # The template carries XMP metadata, which breaks clone_from=reader.
    # We must delete it first.
    root = reader.trailer["/Root"]
    if "/Metadata" in root:
        del root["/Metadata"]

    writer = PdfWriter(clone_from=reader)

    values = {}

    # 1. Constant PI and End User
    values[config.EPIF_PI_FIELD] = config.EPIF_PI_AND_END_USER
    values[config.EPIF_END_USER_FIELD] = config.EPIF_PI_AND_END_USER

    # 2. Text fields mappings
    # Find the reverse mapping from `parsed` keys back to `config.FIELD_TO_COLUMN` keys
    # epif_parser.py parses these as:
    # "What is being purchased" -> "item_description"
    # "Purpose" -> "purpose"
    # "Amount of Purchase" -> "total_price"
    # "Vendor" -> "vendor"
    # "Vendor Name" -> "vendor_contact_name"
    # "Email add" -> "vendor_contact_email"
    # "Date of Purchase" -> "date_of_purchase"
    # "Name of System" -> "name_of_system"
    # "room address" -> "delivery_room"
    # "Project ID Number" -> "project_id"
    # "Fund" -> "fund"
    # "Asset ID" -> "asset_id"

    mapping = {
        "item_description": "What is being purchased",
        "purpose": "Purpose",
        "total_price": "Amount of Purchase",
        "vendor": "Vendor",
        "vendor_contact_name": "Vendor Name",
        "vendor_contact_email": "Email add",
        "date_of_purchase": "Date of Purchase",
        "name_of_system": "Name of System",
        "delivery_room": "room address",
        "project_id": "Project ID Number",
        "fund": "Fund",
        "asset_id": "Asset ID",
    }

    for parsed_key, pdf_key in mapping.items():
        if pdf_key not in config.FIELD_TO_COLUMN:
            continue

        val = parsed.get(parsed_key)

        # Format dates and prices
        if parsed_key == "date_of_purchase" and isinstance(val, datetime.date):
            val = val.strftime("%m/%d/%Y")
        elif parsed_key == "total_price" and val is not None:
            val = f"${val:.2f}"

        # BOM check
        if parsed_key == "item_description":
            items = parsed.get("items")
            if items and len(items) >= 2:
                val = f"See attached BOM — {len(items)} items"

        if val is not None:
            values[pdf_key] = val

    # 3. Checkboxes (Categories)
    target_category = parsed.get("category")
    for box, cat_name in config.CHECKBOX_TO_CATEGORY.items():
        if cat_name == target_category:
            values[box] = "/On"
        else:
            values[box] = "/Off"

    # 4. Checkboxes (Payment Method)
    target_payment = parsed.get("payment_method")
    payment_map = {"P-card": "PCard", "Req/PO": "Req"}
    mapped_payment = payment_map.get(target_payment)

    for box in config.PAYMENT_CHECKBOXES:
        if box == mapped_payment:
            values[box] = "/On"
        else:
            values[box] = "/Off"

    # Remove fields we are not allowed to update
    for ignored_field in ["Signature1", "Telephone # for ?'s", "List of Other"]:
        if ignored_field in values:
            del values[ignored_field]

    # Fill all pages
    for page in writer.pages:
        writer.update_page_form_field_values(page, values, auto_regenerate=False)

    # Set NeedAppearances
    if "/AcroForm" in writer.root_object:
        writer.root_object["/AcroForm"][NameObject("/NeedAppearances")] = BooleanObject(True)

    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()
