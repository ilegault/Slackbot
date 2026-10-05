"""Line items parsing, formatting, validation, and BOM workbook generation.

WHY THIS EXISTS:
----------------
EPIFs have exactly one 'What is being purchased' description and one 'Amount of Purchase'.
When a lab member orders multiple parts from one vendor (e.g. five shaft couplings from
Ruland), sending purchasing five bare links in an email forces the buyer and Tina to
reconstruct quantities, unit costs, and part numbers by hand.

This module provides the pure domain logic for multi-item orders:
1. Parsing pasted line items (pipe-separated or tab-separated straight from Excel/Sheets)
   with precise per-line error reporting.
2. Formatting line items back to standard text for pre-filling edit modals.
3. Checking line item totals against request total ($0.01 tolerance).
4. Building an in-memory openpyxl workbook (BOM) in the lab's hand-made layout (ADR 0008).
   Totals are live formulas to match that sheet so purchasing can adjust a quantity; the
   accepted cost is that Slack's preview shows the formula cells blank, because openpyxl
   stores no cached results. The sheet has no shipping row, so its Total can be below the
   EPIF amount by the shipping entered, and that is intended.
5. Hyperlinking the Item cell to the item's URL so Tina can click straight through to parts.
6. Generating standardized file names (NNNN_<Vendor>_BOM.xlsx) with safe slugging.
7. Computing concise change descriptions for card edit threads.

All functions in this module are strictly pure (no Slack API, no filesystem I/O)
to guarantee isolation and fast, deterministic testability.
"""
import io
import re
from typing import Any, Dict, List, Optional, Tuple

import openpyxl
from openpyxl.styles import Alignment, Font, PatternFill

try:
    from . import epif_parser
except ImportError:
    import epif_parser


def parse_line_items(text: str) -> Tuple[List[Dict[str, Any]], float, List[str]]:
    """Parse pasted line items text into a list of item dicts, shipping amount, and errors.

    Input format: one item per line, separated by '|' or tab '\\t':
      qty | name | part_number | unit_price | link | description
    Optional shipping line:
      shipping | <amount>

    Returns:
      (items, shipping, errors)
    """
    items: List[Dict[str, Any]] = []
    shipping = 0.0
    shipping_seen = False
    errors: List[str] = []

    if not text:
        return items, shipping, errors

    lines = text.splitlines()
    for idx, raw_line in enumerate(lines):
        line_no = idx + 1
        line = raw_line.strip()
        if not line:
            continue

        if "|" in line:
            fields = [f.strip() for f in line.split("|")]
        else:
            fields = [f.strip() for f in line.split("\t")]

        # Check for shipping line
        if fields and fields[0].lower() == "shipping":
            if shipping_seen:
                errors.append(f"line {line_no}: second shipping line is not allowed")
            elif len(fields) < 2:
                errors.append(f"line {line_no}: shipping line must include an amount")
            elif len(fields) > 2:
                errors.append(f"line {line_no}: shipping line has too many fields")
            else:
                amt_str = fields[1]
                p = epif_parser.parse_money(amt_str)
                if p is None:
                    errors.append(f'line {line_no}: shipping amount "{amt_str}" is not a valid number')
                elif p < 0:
                    errors.append(f'line {line_no}: shipping amount "{amt_str}" must be ≥ 0')
                else:
                    shipping = p
                    shipping_seen = True
            continue

        # Item line: 4 to 6 fields
        if len(fields) < 4:
            errors.append(
                f"line {line_no}: expected at least 4 fields (qty | name | part # | unit price), got {len(fields)}"
            )
            continue
        if len(fields) > 6:
            errors.append(
                f"line {line_no}: too many fields (expected up to 6, got {len(fields)})"
            )
            continue

        qty_str = fields[0]
        name = fields[1]
        part_number = fields[2]
        price_str = fields[3]
        link = fields[4] if len(fields) > 4 else ""
        description = fields[5] if len(fields) > 5 else ""

        line_valid = True

        # Validate qty (positive whole number)
        try:
            qty_val = int(qty_str)
            if qty_val <= 0:
                errors.append(f'line {line_no}: quantity "{qty_str}" must be a positive whole number')
                line_valid = False
        except (ValueError, TypeError):
            errors.append(f'line {line_no}: quantity "{qty_str}" must be a positive whole number')
            line_valid = False
            qty_val = 0

        # Validate name (non-empty)
        if not name:
            errors.append(f"line {line_no}: item name cannot be empty")
            line_valid = False

        # Validate unit_price (number >= 0)
        p = epif_parser.parse_money(price_str)
        if p is None:
            errors.append(f'line {line_no}: unit price "{price_str}" is not a number')
            line_valid = False
            price_val = 0.0
        elif p < 0:
            errors.append(f'line {line_no}: unit price "{price_str}" must be ≥ 0')
            line_valid = False
            price_val = 0.0
        else:
            price_val = p

        if line_valid:
            items.append({
                "qty": qty_val,
                "name": name,
                "part_number": part_number,
                "unit_price": price_val,
                "link": link,
                "description": description,
            })

    if len(items) > 25:
        errors.append(f"too many item lines ({len(items)} items, maximum is 25)")

    return items, shipping, errors


def format_line_items(items: List[Dict[str, Any]], shipping: float = 0.0) -> str:
    """Format line items and shipping back to pipe-separated text for pre-filling modals."""
    lines: List[str] = []
    for item in items:
        qty = item.get("qty", 1)
        name = item.get("name", "")
        part = item.get("part_number", "")
        price = float(item.get("unit_price", 0.0))
        link = item.get("link", "")
        desc = item.get("description", "")

        if desc:
            line = f"{qty} | {name} | {part} | {price:.2f} | {link} | {desc}"
        elif link:
            line = f"{qty} | {name} | {part} | {price:.2f} | {link}"
        else:
            line = f"{qty} | {name} | {part} | {price:.2f}"
        lines.append(line)

    if shipping > 0.0:
        lines.append(f"shipping | {shipping:.2f}")

    return "\n".join(lines)


def check_total(items: List[Dict[str, Any]], shipping: float, total_price: Any) -> Optional[str]:
    """Check if sum(qty * unit_price) + shipping matches total_price within $0.01.

    Returns None if within tolerance, or an error sentence showing both numbers.
    """
    if total_price is None:
        target = 0.0
    elif isinstance(total_price, (int, float)):
        target = float(total_price)
    else:
        parsed = epif_parser.parse_money(str(total_price))
        target = parsed if parsed is not None else 0.0

    calculated = sum(int(item["qty"]) * float(item["unit_price"]) for item in items) + float(shipping or 0.0)
    if abs(calculated - target) <= 0.01 + 1e-9:
        return None
    return (
        f"Line items total (${calculated:.2f}) does not match request total (${target:.2f})."
    )


def attachment_errors(
    bom_files: List[Dict[str, Any]], one_vendor_ticked: bool, line_items_text: str
) -> Dict[str, str]:
    """Validate an attached BOM against the one-vendor and attach-or-paste rules.

    WHY THIS EXISTS:
    ----------------
    Ticket 82 / ADR 0012 Decisions 1-4: an attached BOM is carried, never opened, so the
    bot cannot see whether it holds one vendor or whether its lines add up. It can only
    refuse the two combinations it can detect: a BOM plus pasted items (two sources of
    truth for the order) and a BOM without the requester's one-vendor confirmation (one
    EPIF per vendor). Returns Slack view-error text keyed by block_id, in that priority,
    one error at a time. Pure, so Screen 2 here and Add items / Edit (tickets 85, 86)
    share one rule.
    """
    if not bom_files:
        return {}
    if (line_items_text or "").strip():
        return {"block_bom": "Attach a BOM or paste line items, not both."}
    if not one_vendor_ticked:
        return {"block_bom_one_vendor": "One EPIF per vendor — split this into one request per vendor."}
    return {}


def merge_attachments(
    current: List[Dict[str, Any]],
    kept_quote_ids: List[str],
    new_bom: List[Dict[str, Any]],
    new_quotes: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Return the attachment list a posted card holds after an edit.

    WHY THIS EXISTS:
    ----------------
    Ticket 86 / ADR 0012 Decision 6: Slack cannot pre-fill a file field, so an empty BOM
    field means "keep the current BOM" and the current quotes come back as ticked
    checkboxes. The BOM is the new one if given, else the current one; the quotes are the
    current ones still ticked (original order) followed by the new ones. Pure, so Edit and
    Edit items share one rule and the final state can be validated before anything is written.
    """
    merged: List[Dict[str, Any]] = []
    if new_bom:
        merged.append(dict(new_bom[0]))
    else:
        old_bom = next((a for a in current if a.get("role") == "bom"), None)
        if old_bom:
            merged.append(dict(old_bom))
    kept = set(kept_quote_ids)
    merged.extend(dict(a) for a in current if a.get("role") == "quote" and a.get("id") in kept)
    merged.extend(dict(a) for a in new_quotes)
    return merged


def describe_attachment_changes(old: List[Dict[str, Any]], new: List[Dict[str, Any]]) -> List[str]:
    """Return thread-line fragments naming attachment changes between two lists.

    Ticket 86 / ADR 0012 Decision 6: ``removed quote <name>``, ``added quote <name>``,
    ``replaced BOM with <name>`` or ``attached BOM <name>``. Files are matched by Slack id,
    so an unchanged list gives [].
    """
    fragments: List[str] = []
    old_ids = {a.get("id") for a in old}
    new_ids = {a.get("id") for a in new}
    for a in old:
        if a.get("role") == "quote" and a.get("id") not in new_ids:
            fragments.append(f"removed quote {a.get('name') or 'quote'}")
    for a in new:
        if a.get("role") == "quote" and a.get("id") not in old_ids:
            fragments.append(f"added quote {a.get('name') or 'quote'}")
    old_bom = next((a for a in old if a.get("role") == "bom"), None)
    new_bom = next((a for a in new if a.get("role") == "bom"), None)
    if new_bom and (not old_bom or old_bom.get("id") != new_bom.get("id")):
        verb = "replaced BOM with" if old_bom else "attached BOM"
        fragments.append(f"{verb} {new_bom.get('name') or 'BOM'}")
    return fragments


def needs_bom(items: List[Dict[str, Any]]) -> bool:
    """Return True if request has two or more line items."""
    return len(items) >= 2


def describe_changes(old_request: Dict[str, Any], new_request: Dict[str, Any]) -> List[str]:
    """Return concise change fragments between old_request and new_request."""
    fragments: List[str] = []

    # 1. Total price
    def _parse_p(val: Any) -> Optional[float]:
        if val is None:
            return None
        if isinstance(val, (int, float)):
            return float(val)
        return epif_parser.parse_money(str(val))

    old_p = _parse_p(old_request.get("total_price", old_request.get("Amount of Purchase")))
    new_p = _parse_p(new_request.get("total_price", new_request.get("Amount of Purchase")))
    if old_p is not None and new_p is not None and abs(old_p - new_p) > 0.005:
        fragments.append(f"Total ${old_p:.2f} → ${new_p:.2f}")
    elif old_p is not None and new_p is None:
        fragments.append(f"Total ${old_p:.2f} removed")
    elif old_p is None and new_p is not None:
        fragments.append(f"Total set to ${new_p:.2f}")

    # 2. Line items & shipping
    old_items = old_request.get("items") or []
    new_items = new_request.get("items") or []
    old_ship = float(old_request.get("shipping") or 0.0)
    new_ship = float(new_request.get("shipping") or 0.0)

    if len(old_items) != len(new_items):
        fragments.append(f"items {len(old_items)} → {len(new_items)}")
    elif old_items != new_items or abs(old_ship - new_ship) > 0.005:
        fragments.append("items changed")

    # 3. Scalar text fields
    scalar_fields = [
        (["item_description", "What is being purchased"], "item description"),
        (["purpose", "Purpose"], "purpose"),
        (["link", "Link"], "link"),
        (["project_id", "Project ID Number"], "project ID"),
        (["fund", "Fund"], "fund"),
        (["category"], "category"),
        (["delivery_room", "room_address", "room address"], "delivery room"),
        (["vendor_contact_name", "Vendor Name"], "vendor contact name"),
        (["vendor_contact_email", "Email add"], "vendor contact email"),
        (["payment_method", "how_buying", "How Buying"], "payment method"),
        (["asset_id", "Asset ID"], "asset ID"),
        (["name_of_system", "Name of System"], "name of system"),
    ]

    for aliases, label in scalar_fields:
        old_val = ""
        for k in aliases:
            if k in old_request and old_request[k] is not None:
                old_val = str(old_request[k]).strip()
                break

        new_val = ""
        for k in aliases:
            if k in new_request and new_request[k] is not None:
                new_val = str(new_request[k]).strip()
                break

        if old_val != new_val:
            if old_val and new_val:
                fragments.append(f"{label} '{old_val}' → '{new_val}'")
            elif new_val:
                fragments.append(f"{label} set to '{new_val}'")
            else:
                fragments.append(f"{label} cleared")

    return fragments


def _vendor_slug(vendor: str) -> str:
    """Filename-safe vendor slug shared by bom_filename and quote_filename."""
    v_clean = (vendor or "").strip()
    v_slug = re.sub(r"\s+", "-", v_clean)
    v_slug = re.sub(r"[^A-Za-z0-9\-]", "", v_slug)
    v_slug = re.sub(r"-+", "-", v_slug).strip("-")
    v_slug = v_slug[:40].rstrip("-")
    return v_slug or "Vendor"


def bom_filename(row: Optional[int], vendor: str, ext: str = "xlsx") -> str:
    """Generate standardized BOM filename.

    Draft: DRAFT_{slug}_BOM.xlsx
    Approved: NNNN_{slug}_BOM.xlsx (zero-padded to 4 digits)
    ext: the suffix, for an attached BOM filed byte-for-byte under its own extension
    (ADR 0012 decision 5); the made BOM is always xlsx.
    """
    v_slug = _vendor_slug(vendor)
    ext = re.sub(r"[^a-z0-9]", "", (ext or "xlsx").lower().lstrip(".")) or "xlsx"
    if row is None:
        return f"DRAFT_{v_slug}_BOM.{ext}"
    return f"{int(row):04d}_{v_slug}_BOM.{ext}"


def quote_filename(row: int, vendor: str, k: int) -> str:
    """Archived quote name NNNN_{slug}_Quote_{k}.pdf, k counted from 1 in attachment order.

    After approval the card carries only a quote_count (button values are size-capped), so
    every later reader derives the names from row + vendor + k with this function.
    """
    return f"{int(row):04d}_{_vendor_slug(vendor)}_Quote_{int(k)}.pdf"


def build_bom_workbook(request: Dict[str, Any], items: List[Dict[str, Any]]) -> bytes:
    """Build the BOM spreadsheet in the lab's hand-made layout (ADR 0008) and return its bytes.

    Totals are live formulas. Shipping, requester, project, fund, date and log row are
    deliberately not rendered.
    """
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "BOM"

    font_name, font_size = "Aptos Narrow", 12
    money = '"$"#,##0.00'

    def fnt(bold=False, color=None, underline=None):
        return Font(name=font_name, size=font_size, bold=bold, color=color, underline=underline)

    def fill(hex_rgb):
        return PatternFill(start_color=hex_rgb, end_color=hex_rgb, fill_type="solid")

    title_fill, block_fill, head_fill = fill("0B3041"), fill("DCEAF7"), fill("104862")
    vendor = str(request.get("vendor") or "").strip() or "Unknown Vendor"

    first_item_row = 5
    total_row = first_item_row + len(items)

    ws.merge_cells("A1:B1")
    ws["A1"] = "BILL OF MATERIALS"
    ws["A1"].font = fnt(bold=True, color="FFFFFF")
    ws["A1"].fill = title_fill
    ws["B1"].fill = title_fill

    ws["A2"] = "Total Cost"
    ws["A2"].font = fnt(bold=True)
    ws["A2"].fill = block_fill
    ws["B2"] = f"=G{total_row}"
    ws["B2"].font = fnt()
    ws["B2"].fill = block_fill
    ws["B2"].number_format = money
    ws["B2"].alignment = Alignment(horizontal="left")

    headers = ["Item", "Description", "Product #", "Vendor", "Unit Cost",
               "Quantity", "Total Cost", "Notes"]
    for col, name in enumerate(headers, start=1):
        c = ws.cell(row=4, column=col, value=name)
        c.font = fnt(bold=True, color="FFFFFF")
        c.fill = head_fill

    for i, item in enumerate(items):
        r = first_item_row + i
        link = str(item.get("link") or "").strip()
        a = ws.cell(row=r, column=1, value=str(item.get("name", "")).strip())
        if link.startswith(("http://", "https://")):
            a.hyperlink = link
            a.font = fnt(color="467886", underline="single")
        else:
            a.font = fnt()
        ws.cell(row=r, column=2, value=str(item.get("description") or "").strip())
        ws.cell(row=r, column=3, value=str(item.get("part_number") or "").strip())
        ws.cell(row=r, column=4, value=vendor)
        ws.cell(row=r, column=5, value=float(item.get("unit_price", 0.0))).number_format = money
        ws.cell(row=r, column=6, value=int(item.get("qty", 1)))
        ws.cell(row=r, column=7, value=f"=E{r}*F{r}").number_format = money
        ws.cell(row=r, column=8, value=None)
        for col in range(2, 9):
            ws.cell(row=r, column=col).font = fnt()

    for col in range(1, 9):
        ws.cell(row=total_row, column=col).fill = head_fill
    ws.cell(row=total_row, column=6, value="Total").font = fnt(bold=True, color="FFFFFF")
    g = ws.cell(row=total_row, column=7, value=f"=SUM(G{first_item_row}:G{total_row - 1})")
    g.font = fnt(bold=True, color="FFFFFF")
    g.number_format = money

    ws.freeze_panes = "A5"
    for letter, width in {"A": 35, "B": 68, "C": 14, "D": 17, "E": 12, "F": 10, "G": 13, "H": 47}.items():
        ws.column_dimensions[letter].width = width

    bio = io.BytesIO()
    wb.save(bio)
    return bio.getvalue()
