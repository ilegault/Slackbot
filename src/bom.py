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
4. Building the BOM by filling the committed lab template (ADR 0019 decision 6; it replaced
   ADR 0008's hand-built layout). Totals are live formulas, so Slack's preview shows them
   blank because openpyxl stores no cached results. The sheet has no shipping row.
5. Hyperlinking the Item cell to the item's URL so Tina can click straight through to parts.
6. Generating the lab's file names, HIRST_LAB_BOM_<Description>_<MM.DD.YYYY>.xlsx.
7. Computing concise change descriptions for card edit threads.

8. Reading the lab BOM template (ADR 0019): `read_bom_template` parses an uploaded .xlsx
   whose header row exactly matches `config.BOM_TEMPLATE_HEADERS`. It never guesses headers:
   a sheet in any other layout is refused with one sentence pointing at the template, because
   a wrong guess writes a wrong quantity into a purchase. It never reads formula cells (the
   Total Cost column): a file written by openpyxl or any non-Excel tool holds no cached
   formula results, so the reader would see None or the formula text. The total is
   recomputed as quantity x unit cost, and `check_bom_total` compares it with the typed
   Total Price to the cent. There is no shipping anywhere in this check.

All functions in this module are strictly pure (no Slack API, no filesystem I/O)
to guarantee isolation and fast, deterministic testability.
"""
import copy
import datetime
import io
import re
from typing import Any, Dict, List, Optional, Tuple

import openpyxl
from openpyxl.styles import Font

try:
    from . import config, epif_parser
except ImportError:
    import config  # type: ignore[no-redef]  # same fallback idiom as the other modules
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


_FILENAME_BAD = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_FILENAME_MAX = 60


def bom_filename(
    description: str,
    approval_date: Optional[datetime.date] = None,
    draft: bool = False,
    ext: str = "xlsx",
) -> str:
    """Generate the lab's BOM file name (ADR 0019 decision 6).

    `HIRST_LAB_BOM_<Description>_<MM.DD.YYYY>.xlsx`. Each whitespace-separated word of the
    description keeps only characters a Windows file name can hold; the words are joined by
    `-` and the result is cut to 60 characters. A draft is `DRAFT_` + the same name dated
    today (it has no approval date yet). `ext` exists only so an attached BOM posted before
    ADR 0019 shipped is filed under the new name with its own extension.
    """
    words = [_FILENAME_BAD.sub("", w) for w in (description or "").split()]
    part = "-".join(w for w in words if w)[:_FILENAME_MAX].rstrip("-") or "Order"
    day = datetime.date.today() if draft or approval_date is None else approval_date
    ext = re.sub(r"[^a-z0-9]", "", (ext or "xlsx").lower().lstrip(".")) or "xlsx"
    name = f"HIRST_LAB_BOM_{part}_{day.strftime('%m.%d.%Y')}.{ext}"
    return f"DRAFT_{name}" if draft else name


def quote_filename(row: int, vendor: str, k: int) -> str:
    """Archived quote name NNNN_{slug}_Quote_{k}.pdf, k counted from 1 in attachment order.

    After approval the card carries only a quote_count (button values are size-capped), so
    every later reader derives the names from row + vendor + k with this function.
    """
    return f"{int(row):04d}_{_vendor_slug(vendor)}_Quote_{int(k)}.pdf"


def build_bom_workbook(request: Dict[str, Any], items: List[Dict[str, Any]]) -> bytes:
    """Fill the committed lab BOM template (ADR 0019 decision 6) and return its bytes.

    The template is loaded from `config.BOM_TEMPLATE_PATH`, so the rebuilt file is the lab's
    own sheet with its styles, not a look-alike. B2 is the order description, B3 the
    requester's roster name, items start on row 6, then the Total row and B4 pointing at it.
    The template ships with four item rows; rows below row 5 are rebuilt for any item count,
    each copying the style of the template's first item row, and the Total row copies the
    template's Total row. Totals stay live formulas (Slack's preview shows them blank; the
    reader never trusts them). Shipping, project, fund and log row are not rendered.
    """
    # Read the template as bytes: this is the committed template, not the log workbook, and
    # the only-log_writer-opens-a-workbook guard exempts in-memory loads only.
    with open(config.BOM_TEMPLATE_PATH, "rb") as fh:
        wb = openpyxl.load_workbook(io.BytesIO(fh.read()))
    ws = wb.worksheets[0]
    first_row, ncols = 6, 8

    item_styles = [copy.copy(ws.cell(row=first_row, column=c)._style) for c in range(1, ncols + 1)]
    template_total = next(
        r for r in range(first_row, ws.max_row + 1) if str(ws.cell(row=r, column=6).value or "").strip() == "Total"
    )
    total_styles = [copy.copy(ws.cell(row=template_total, column=c)._style) for c in range(1, ncols + 1)]
    height = ws.row_dimensions[first_row].height
    ws.delete_rows(first_row, ws.max_row)

    default_vendor = str(request.get("vendor") or "").strip() or "Unknown Vendor"
    ws["B2"] = str(request.get("item_description") or "").strip()
    ws["B3"] = str(request.get("requester") or "").strip()

    for i, item in enumerate(items):
        r = first_row + i
        for c in range(1, ncols + 1):
            ws.cell(row=r, column=c)._style = copy.copy(item_styles[c - 1])
        if height:
            ws.row_dimensions[r].height = height
        link = str(item.get("link") or "").strip()
        a = ws.cell(row=r, column=1, value=str(item.get("name", "")).strip())
        if link.startswith(("http://", "https://")):
            a.hyperlink = link
            a.font = Font(name=a.font.name, size=a.font.sz, color="467886", underline="single")
        ws.cell(row=r, column=2, value=str(item.get("description") or "").strip() or None)
        ws.cell(row=r, column=3, value=str(item.get("part_number") or "").strip() or None)
        ws.cell(row=r, column=4, value=str(item.get("vendor") or "").strip() or default_vendor)
        ws.cell(row=r, column=5, value=float(item.get("unit_price", 0.0))).number_format = '"$"#,##0.00'
        ws.cell(row=r, column=6, value=int(item.get("qty", 1)))
        ws.cell(row=r, column=7, value=f"=F{r}*E{r}")
        ws.cell(row=r, column=8, value=str(item.get("notes") or "").strip() or None)

    total_row = first_row + len(items)
    for c in range(1, ncols + 1):
        ws.cell(row=total_row, column=c)._style = copy.copy(total_styles[c - 1])
    if height:
        ws.row_dimensions[total_row].height = height
    ws.cell(row=total_row, column=6, value="Total")
    ws.cell(row=total_row, column=7, value=f"=SUM(G{first_row}:G{total_row - 1})")
    ws["B4"] = f"=G{total_row}"

    bio = io.BytesIO()
    wb.save(bio)
    return bio.getvalue()


# ---------------------------------------------------------------------------
# Lab BOM template reader (ADR 0019)
# ---------------------------------------------------------------------------

_NOT_TEMPLATE = (
    "This isn't the lab BOM template — get it with the “Send me the BOM template” "
    "button. Vendor carts and quotes go in the Quotes field."
)
_HEADER_SCAN_ROWS = 10


def _text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _whole_quantity(value: Any) -> Optional[int]:
    """Return value as an int of 1 or more, or None when it is not a whole number."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        number = float(value)
    else:
        try:
            number = float(_text(value))
        except ValueError:
            return None
    if number != int(number) or number < 1:
        return None
    return int(number)


def _unit_cost(value: Any) -> Optional[float]:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    cleaned = _text(value).replace("$", "").replace(",", "")
    try:
        return float(cleaned)
    except ValueError:
        return None


def read_bom_template(xlsx_bytes: bytes) -> Tuple[List[Dict[str, Any]], List[str]]:
    """Read the lab BOM template from .xlsx bytes. Returns (items, problems).

    Each item carries the existing line-item keys (`qty`, `name`, `part_number`,
    `unit_price`, `link`, `description`) so the card, the BOM builder and the summary
    lines keep working, plus `quantity`, `item_name`, `vendor` and `notes`.
    """
    not_template: Tuple[List[Dict[str, Any]], List[str]] = ([], [_NOT_TEMPLATE])
    try:
        wb = openpyxl.load_workbook(io.BytesIO(xlsx_bytes), data_only=False)
        ws = wb.worksheets[0]
    except Exception:
        return not_template

    headers = [h.lower() for h in config.BOM_TEMPLATE_HEADERS]
    width = len(headers)
    header_row = None
    for row_no in range(1, _HEADER_SCAN_ROWS + 1):
        cells = [_text(ws.cell(row=row_no, column=c).value).lower() for c in range(1, width + 1)]
        if cells == headers:
            header_row = row_no
            break
    if header_row is None:
        return not_template

    items: List[Dict[str, Any]] = []
    problems: List[str] = []
    rows_seen = 0
    for row_no in range(header_row + 1, ws.max_row + 1):
        cell = {name: ws.cell(row=row_no, column=i + 1) for i, name in enumerate(headers)}
        if _text(cell["quantity"].value).lower() == "total":
            break
        cost_raw, qty_raw = cell["unit cost"].value, cell["quantity"].value
        if _text(cost_raw) == "" and _text(qty_raw) == "":
            continue
        rows_seen += 1

        name = _text(cell["item"].value)
        qty = _whole_quantity(qty_raw)
        price = _unit_cost(cost_raw)
        row_ok = True
        if not name:
            problems.append(f"Row {row_no}: Item is blank.")
            row_ok = False
        if qty is None:
            problems.append(f"Row {row_no}: Quantity '{_text(qty_raw)}' isn't a whole number of 1 or more.")
            row_ok = False
        if price is None:
            problems.append(f"Row {row_no}: Unit Cost '{_text(cost_raw)}' isn't a number.")
            row_ok = False
        if not row_ok:
            continue

        link = cell["item"].hyperlink.target if cell["item"].hyperlink else None
        items.append({
            "item_name": name,
            "name": name,
            "description": _text(cell["description"].value),
            "part_number": _text(cell["product #"].value),
            "vendor": _text(cell["vendor"].value),
            "unit_price": price,
            "quantity": qty,
            "qty": qty,
            "notes": _text(cell["notes"].value),
            "link": link or "",
        })

    if rows_seen > config.BOM_MAX_ROWS:
        problems.append(f"This BOM has {rows_seen} rows — the most is {config.BOM_MAX_ROWS}.")
    return items, problems


def bom_total(items: List[Dict[str, Any]]) -> float:
    """Sum of quantity x unit price over the items, rounded to cents."""
    return round(sum(int(i["quantity"]) * float(i["unit_price"]) for i in items), 2)


def check_bom_total(items: List[Dict[str, Any]], total_price: Any) -> Optional[str]:
    """None when the BOM total equals the typed Total Price to the cent, else a sentence."""
    if isinstance(total_price, (int, float)):
        typed = float(total_price)
    else:
        parsed = epif_parser.parse_money(str(total_price)) if total_price is not None else None
        typed = parsed if parsed is not None else 0.0
    total = bom_total(items)
    if round(typed * 100) == round(total * 100):
        return None
    return f"The BOM totals ${total:,.2f} but you typed ${typed:,.2f} — they must match."
