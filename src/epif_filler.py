"""Fills the blank EPIF template with a parsed request dict.

WHY THIS EXISTS:
Per ADR 0007, an approved EPIF request needs to generate an actual PDF so that it
can be emailed to purchasing, using the same template already manually
used by the lab. This is the pure domain logic that creates the filled PDF. It reads
back to the same dictionary `epif_parser.parse_epif` extracts.

Fields `parse_epif` does not read:
- Telephone # for ?'s
- Signature1
- List of Other
"""
import io

from pypdf import PdfReader, PdfWriter

try:
    from . import config
except ImportError:
    import config


def fill_epif(template_bytes: bytes, parsed: dict) -> bytes:
    """Given a blank template PDF and a parsed request, return the filled PDF bytes."""
    reader = PdfReader(io.BytesIO(template_bytes))
    writer = PdfWriter(clone_from=reader)

    fields = {
        "Purpose": parsed.get("purpose", ""),
        "Amount of Purchase": parsed.get("total_price_raw") or (str(parsed.get("total_price")) if parsed.get("total_price") is not None else ""),
        "Vendor": parsed.get("vendor", ""),
        "Vendor Name": parsed.get("vendor_contact_name", ""),
        "Email add": parsed.get("vendor_contact_email", ""),
        "Date of Purchase": parsed.get("date_of_purchase").strftime("%m/%d/%y") if parsed.get("date_of_purchase") else "",
        "Name of System": parsed.get("name_of_system", ""),
        "room address": parsed.get("delivery_room", ""),
        "Project ID Number": parsed.get("project_id", ""),
        "Fund": parsed.get("fund", ""),
        "Asset ID": parsed.get("asset_id", ""),
        "PI of Funding": config.EPIF_PI_AND_END_USER,
        "Name": config.EPIF_PI_AND_END_USER,
    }

    items = parsed.get("items", [])
    if len(items) >= 2:
        fields["What is being purchased"] = f"See attached BOM — {len(items)} items"
        fields["Amount of Purchase"] = str(parsed.get("total_price")) if parsed.get("total_price") is not None else ""
    else:
        fields["What is being purchased"] = parsed.get("item_description", "")

    category = parsed.get("category")
    if category:
        for checkbox_name, cat_label in config.CHECKBOX_TO_CATEGORY.items():
            if cat_label == category:
                fields[checkbox_name] = "/On"
                break

    payment_method = parsed.get("payment_method")
    if payment_method == "P-card":
        fields["PCard"] = "/On"
    elif payment_method == "Req/PO":
        fields["Req"] = "/On"

    writer.update_page_form_field_values(writer.pages[0], fields)

    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()
