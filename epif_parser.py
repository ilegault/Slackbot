"""Turn an EPIF PDF into a plain dict.

The EPIF is a real AcroForm: 28 named fields. That means we never have to look at
coordinates or scrape text - pypdf hands us {field_name: value} directly.
"""
import io
import re
from datetime import datetime

from pypdf import PdfReader

import config


class FlattenedPdfError(Exception):
    """Raised when the PDF has no form fields left (someone printed it to PDF)."""


_URL_RE = re.compile(r"https?://\S+")
_MONEY_RE = re.compile(r"-?[\d,]+(?:\.\d+)?")


def read_fields(pdf_bytes: bytes) -> dict:
    """Raw {field_name: value} straight out of the PDF."""
    reader = PdfReader(io.BytesIO(pdf_bytes))
    fields = reader.get_fields()
    if not fields:
        raise FlattenedPdfError(
            "This PDF has no fillable form fields. It was probably flattened or "
            "printed to PDF. Please re-upload the version you filled in Acrobat."
        )
    out = {}
    for name, obj in fields.items():
        value = obj.get("/V")
        out[name] = "" if value is None else str(value)
    return out


def parse_money(raw: str):
    """'$2799' -> 2799.0 ; '' -> None"""
    if not raw:
        return None
    match = _MONEY_RE.search(raw.replace(",", ""))
    return float(match.group(0)) if match else None


def parse_date(raw: str):
    """'09/03/26' -> date. Returns None if it doesn't look like a date."""
    if not raw:
        return None
    for fmt in ("%m/%d/%y", "%m/%d/%Y", "%Y-%m-%d", "%m-%d-%y", "%m-%d-%Y"):
        try:
            return datetime.strptime(raw.strip(), fmt).date()
        except ValueError:
            continue
    return None


def first_url(text: str):
    match = _URL_RE.search(text or "")
    return match.group(0) if match else None


def selected_category(fields: dict):
    """Which of the nine category checkboxes is ticked.

    Returns (dropdown_string, error_or_None). Exactly one must be ticked - the
    EPIF itself says 'Mark only 1 box'.
    """
    ticked = [
        label for name, label in config.CHECKBOX_TO_CATEGORY.items()
        if fields.get(name, "/Off") != "/Off"
    ]
    if len(ticked) == 1:
        return ticked[0], None
    if not ticked:
        return None, "no EPIF category box is ticked"
    return None, f"{len(ticked)} category boxes are ticked, only 1 is allowed"


def payment_method(fields: dict):
    """'P-card', 'Req/PO', or None if neither/both are ticked."""
    picked = [n for n in config.PAYMENT_CHECKBOXES if fields.get(n, "/Off") != "/Off"]
    if picked == ["PCard"]:
        return "P-card"
    if picked == ["Req"]:
        return "Req/PO"
    return None


def parse_epif(pdf_bytes: bytes) -> dict:
    """The one function the bot calls. Everything downstream reads this dict."""
    fields = read_fields(pdf_bytes)
    category, category_error = selected_category(fields)
    purpose = fields.get("Purpose", "")

    return {
        "raw_fields": fields,
        "item_description": fields.get("What is being purchased", "").strip(),
        "purpose": purpose.strip(),
        "link": first_url(purpose),
        "total_price": parse_money(fields.get("Amount of Purchase", "")),
        "total_price_raw": fields.get("Amount of Purchase", "").strip(),
        "vendor": fields.get("Vendor", "").strip(),
        "vendor_contact_name": fields.get("Vendor Name", "").strip(),
        "vendor_contact_email": fields.get("Email add", "").strip(),
        "date_of_purchase": parse_date(fields.get("Date of Purchase", "")),
        "name_of_system": fields.get("Name of System", "").strip(),
        "delivery_room": fields.get("room address", "").strip(),
        "project_id": fields.get("Project ID Number", "").strip(),
        "fund": fields.get("Fund", "").strip(),
        "asset_id": fields.get("Asset ID", "").strip(),
        "pi_of_funding": fields.get("PI of Funding", "").strip(),
        "end_user": fields.get("Name", "").strip(),
        "category": category,
        "category_error": category_error,
        "payment_method": payment_method(fields),
    }
