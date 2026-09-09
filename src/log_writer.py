"""Write one row into Purchasing-Log.xlsx without wrecking the workbook.

Why this file is not just pandas.ExcelWriter or openpyxl:

    The workbook uses an x14 (extension-namespace) conditional formatting block -
    that's the pink/yellow/green row colouring driven by the Status column, plus
    the grey-out of Name of System / Asset ID. openpyxl cannot represent x14 CF,
    so ANY load-and-save through openpyxl or pandas silently deletes it, along
    with xl/metadata.xml and the web-extension parts. The lab opens the file and
    the colours are gone, with nothing in the logs to explain it.

    So instead of rewriting the workbook, we copy the .xlsx (which is just a zip)
    part-for-part, and surgically edit only the <c> elements of the one row we
    are filling in. Everything we don't touch is byte-identical afterwards.

This is safe because rows 12-1999 already exist in the sheet with their styles
and their A/Z array formulas. We are filling blanks, not appending structure.
"""
import os
import re
import shutil
import tempfile
import zipfile
from datetime import date, datetime
from xml.sax.saxutils import escape

try:
    from . import config
except ImportError:
    import config


class WorkbookLockedError(Exception):
    """Someone has the workbook open in Excel."""


class LogFullError(Exception):
    """No empty rows left inside the OrderLog table range."""


EXCEL_EPOCH = date(1899, 12, 30)  # Excel's day 0, accounting for the 1900 leap bug


def _to_serial(value) -> int:
    if isinstance(value, datetime):
        value = value.date()
    return (value - EXCEL_EPOCH).days


def _cell_pattern(ref: str):
    """Matches either <c r="B17" s="46"/> or <c r="B17" ...>...</c>."""
    return re.compile(
        r'<c r="%s"(?P<attrs>[^>/]*)(?:/>|>(?P<body>.*?)</c>)' % ref, re.S
    )


def _render_cell(ref: str, style_attrs: str, value) -> str:
    """Build the replacement <c> element, keeping the original style index."""
    # Drop any t="..." from the original attrs; we set our own.
    attrs = re.sub(r'\st="[^"]*"', "", style_attrs).rstrip()
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return f'<c r="{ref}"{attrs}><v>{value}</v></c>'
    if isinstance(value, (date, datetime)):
        return f'<c r="{ref}"{attrs}><v>{_to_serial(value)}</v></c>'
    text = escape(str(value))
    return f'<c r="{ref}"{attrs} t="inlineStr"><is><t xml:space="preserve">{text}</t></is></c>'


def get_cell_value(sheet_xml: str, ref: str) -> str | None:
    """Extract raw text or numeric value from a specific cell reference in sheet_xml."""
    match = _cell_pattern(ref).search(sheet_xml)
    if match is None:
        return None
    body = match.group("body")
    if not body:
        return None
    t_match = re.search(r"<t[^>]*>(.*?)</t>", body, re.S)
    if t_match:
        return t_match.group(1).strip()
    v_match = re.search(r"<v[^>]*>(.*?)</v>", body, re.S)
    if v_match:
        return v_match.group(1).strip()
    return None


def find_first_empty_row(sheet_xml: str) -> int:
    """First row in the table whose Requester Name (column B) is empty."""
    for row in range(config.FIRST_DATA_ROW, config.LAST_DATA_ROW + 1):
        match = _cell_pattern(f"B{row}").search(sheet_xml)
        if match is None:
            return row  # row element has no B cell at all -> definitely empty
        body = match.group("body")
        if body is None or "<v" not in body and "<is>" not in body:
            return row
    raise LogFullError(
        f"Rows {config.FIRST_DATA_ROW}-{config.LAST_DATA_ROW} of the OrderLog "
        "table are all used. Extend the table before logging more orders."
    )


def apply_row(sheet_xml: str, row: int, values: dict) -> str:
    """Return sheet_xml with `values` ({'B': 'Isaac', ...}) written into `row`."""
    for column, value in values.items():
        if value in (None, ""):
            continue
        if column in config.READ_ONLY_COLUMNS:
            raise ValueError(
                f"Column {column} holds a formula and must not be written."
            )
        ref = f"{column}{row}"
        pattern = _cell_pattern(ref)
        match = pattern.search(sheet_xml)
        if match is None:
            raise ValueError(f"Cell {ref} is not present in the sheet XML.")
        replacement = _render_cell(ref, match.group("attrs"), value)
        sheet_xml = sheet_xml[:match.start()] + replacement + sheet_xml[match.end():]
    return sheet_xml


def _assert_not_locked(path: str):
    lock = os.path.join(os.path.dirname(path), "~$" + os.path.basename(path))
    if os.path.exists(lock):
        raise WorkbookLockedError(
            "Purchasing-Log.xlsx is open in Excel by someone in the lab. "
            "I'll need them to close it before I can log this."
        )


def append_row(values: dict, workbook_path: str = None) -> int:
    """Write one order into the log. Returns the row number used."""
    path = workbook_path or config.WORKBOOK_PATH
    _assert_not_locked(path)

    with zipfile.ZipFile(path) as archive:
        parts = {name: archive.read(name) for name in archive.namelist()}
        order = archive.namelist()

    sheet_xml = parts[config.SHEET_XML].decode("utf-8")
    row = find_first_empty_row(sheet_xml)
    parts[config.SHEET_XML] = apply_row(sheet_xml, row, values).encode("utf-8")

    # Write to a temp file in the same directory, then atomically swap it in, so
    # OneDrive never sees a half-written workbook.
    directory = os.path.dirname(os.path.abspath(path))
    handle, temp_path = tempfile.mkstemp(suffix=".xlsx", dir=directory)
    os.close(handle)
    try:
        with zipfile.ZipFile(temp_path, "w", zipfile.ZIP_DEFLATED) as out:
            for name in order:
                out.writestr(name, parts[name])
        shutil.copystat(path, temp_path)
        os.replace(temp_path, path)
    except Exception:
        if os.path.exists(temp_path):
            os.remove(temp_path)
        raise
    return row


def update_row(row: int, values: dict, workbook_path: str = None) -> int:
    """Update specific columns in an existing row of Purchasing-Log.xlsx atomically."""
    path = workbook_path or config.WORKBOOK_PATH
    _assert_not_locked(path)

    with zipfile.ZipFile(path) as archive:
        parts = {name: archive.read(name) for name in archive.namelist()}
        order = archive.namelist()

    sheet_xml = parts[config.SHEET_XML].decode("utf-8")
    parts[config.SHEET_XML] = apply_row(sheet_xml, row, values).encode("utf-8")

    directory = os.path.dirname(os.path.abspath(path))
    handle, temp_path = tempfile.mkstemp(suffix=".xlsx", dir=directory)
    os.close(handle)
    try:
        with zipfile.ZipFile(temp_path, "w", zipfile.ZIP_DEFLATED) as out:
            for name in order:
                out.writestr(name, parts[name])
        shutil.copystat(path, temp_path)
        os.replace(temp_path, path)
    except Exception:
        if os.path.exists(temp_path):
            os.remove(temp_path)
        raise
    return row


def get_row_info(row: int, workbook_path: str = None) -> dict:
    """Read basic info (Requester, Item, Date of Request, Confirmed date, etc.) for a row."""
    path = workbook_path or config.WORKBOOK_PATH
    with zipfile.ZipFile(path) as archive:
        sheet_xml = archive.read(config.SHEET_XML).decode("utf-8")

    return {
        "row": row,
        "requester": get_cell_value(sheet_xml, f"{config.COLUMN_REQUESTER}{row}"),
        "item_description": get_cell_value(sheet_xml, f"C{row}"),
        "total_price": get_cell_value(sheet_xml, f"{config.COLUMN_TOTAL_PRICE}{row}"),
        "date_requested": get_cell_value(sheet_xml, f"{config.COLUMN_DATE_OF_REQUEST}{row}"),
        "date_processed": get_cell_value(sheet_xml, f"{config.COLUMN_DATE_PROCESSED}{row}"),
        "date_confirmed": get_cell_value(sheet_xml, f"{config.COLUMN_DATE_CONFIRMED}{row}"),
        "date_delivered": get_cell_value(sheet_xml, f"{config.COLUMN_DATE_DELIVERY}{row}"),
    }


def find_latest_unconfirmed_row_for_requester(requester_name: str, workbook_path: str = None) -> int | None:
    """Find the most recent row for a requester where Date Confirmed (Col V) is empty."""
    path = workbook_path or config.WORKBOOK_PATH
    with zipfile.ZipFile(path) as archive:
        sheet_xml = archive.read(config.SHEET_XML).decode("utf-8")

    first_empty = find_first_empty_row(sheet_xml)
    # Search backwards from last filled row
    for row in range(first_empty - 1, config.FIRST_DATA_ROW - 1, -1):
        req = get_cell_value(sheet_xml, f"{config.COLUMN_REQUESTER}{row}")
        if req and req.lower() == requester_name.lower():
            date_confirmed = get_cell_value(sheet_xml, f"{config.COLUMN_DATE_CONFIRMED}{row}")
            if not date_confirmed:
                return row
    return None


def save_epif(pdf_bytes: bytes, filename: str, target_dir: str = None) -> str:
    """Save the EPIF PDF into the lab's EPIFs directory atomically.

    Returns the absolute path to the saved PDF file.
    """
    directory = target_dir or config.EPIFS_DIR
    os.makedirs(directory, exist_ok=True)

    clean_name = os.path.basename(filename).strip() if filename else "EPIF.pdf"
    if not clean_name:
        clean_name = "EPIF.pdf"
    if not clean_name.lower().endswith(".pdf"):
        clean_name += ".pdf"

    dest_path = os.path.join(directory, clean_name)

    handle, temp_path = tempfile.mkstemp(suffix=".pdf", dir=directory)
    try:
        with os.fdopen(handle, "wb") as f:
            f.write(pdf_bytes)
        os.replace(temp_path, dest_path)
    except Exception:
        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except OSError:
                pass
        raise
    return dest_path


def save_confirmation(file_bytes: bytes, filename: str, target_dir: str = None) -> str:
    """Save order confirmation attachment into Order-Confirmations directory atomically.

    Returns the absolute path to the saved confirmation file.
    """
    directory = target_dir or config.CONFIRMATIONS_DIR
    os.makedirs(directory, exist_ok=True)

    clean_name = os.path.basename(filename).strip() if filename else "Order_Confirmation.pdf"
    if not clean_name:
        clean_name = "Order_Confirmation.pdf"

    dest_path = os.path.join(directory, clean_name)

    suffix = os.path.splitext(clean_name)[1] or ".pdf"
    handle, temp_path = tempfile.mkstemp(suffix=suffix, dir=directory)
    try:
        with os.fdopen(handle, "wb") as f:
            f.write(file_bytes)
        os.replace(temp_path, dest_path)
    except Exception:
        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except OSError:
                pass
        raise
    return dest_path


def save_quote(file_bytes: bytes, filename: str, target_dir: str = None) -> str:
    """Save vendor quote document into Quotes directory atomically.

    Returns the absolute path to the saved quote file.
    """
    directory = target_dir or config.QUOTES_DIR
    os.makedirs(directory, exist_ok=True)

    clean_name = os.path.basename(filename).strip() if filename else "Vendor_Quote.pdf"
    if not clean_name:
        clean_name = "Vendor_Quote.pdf"

    dest_path = os.path.join(directory, clean_name)

    suffix = os.path.splitext(clean_name)[1] or ".pdf"
    handle, temp_path = tempfile.mkstemp(suffix=suffix, dir=directory)
    try:
        with os.fdopen(handle, "wb") as f:
            f.write(file_bytes)
        os.replace(temp_path, dest_path)
    except Exception:
        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except OSError:
                pass
        raise
    return dest_path


def build_row(parsed: dict, requester_name: str) -> dict:
    """Parsed EPIF -> {column_letter: value}, ready for append_row."""
    values = {
        config.COLUMN_REQUESTER: requester_name,
        "C": parsed["item_description"],
        "D": parsed["purpose"],
        config.COLUMN_TOTAL_PRICE: parsed["total_price"],
        "I": parsed["vendor"],
        "J": parsed["vendor_contact_name"],
        "K": parsed["vendor_contact_email"],
        config.COLUMN_DATE_OF_REQUEST: parsed["date_of_purchase"],
        "P": parsed["name_of_system"],
        "Q": parsed["delivery_room"],
        "R": parsed["project_id"],
        "T": parsed["asset_id"],
        config.COLUMN_CATEGORY: parsed["category"],
    }
    if parsed["link"]:
        values[config.COLUMN_LINK] = parsed["link"]
    if parsed["fund"]:
        # The Fund dropdown holds numbers, not text.
        values["S"] = int(parsed["fund"])
    return {k: v for k, v in values.items() if v not in (None, "")}
