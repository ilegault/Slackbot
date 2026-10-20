"""All the lab-specific constants live here, nothing else.

Everything in this file was read off the real EPIF_TEMPLATE_blank.pdf and the real
Purchasing-Log.xlsx, so if either of those changes, this is the only file to edit.
"""
import os
import subprocess
import sys


def get_base_dir() -> str:
    """Return project root or executable directory."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    file_dir = os.path.dirname(os.path.abspath(__file__))
    if os.path.basename(file_dir) in ("src", "scripts", "tests"):
        return os.path.dirname(file_dir)
    return file_dir

BASE_DIR = get_base_dir()

# Search candidate locations for .env
_env_candidates = [
    os.path.join(BASE_DIR, ".env"),
    os.path.join(os.path.dirname(BASE_DIR), ".env"),
    os.path.join(os.getcwd(), ".env"),
]
if hasattr(sys, "_MEIPASS"):
    _env_candidates.append(os.path.join(sys._MEIPASS, ".env"))

LOADED_ENV_PATH = None
for _cand in _env_candidates:
    if os.path.isfile(_cand):
        LOADED_ENV_PATH = _cand
        with open(_cand, "r", encoding="utf-8") as _f:
            for _line in _f:
                _line = _line.strip()
                if not _line or _line.startswith("#"):
                    continue
                if "=" in _line:
                    _k, _v = _line.split("=", 1)
                    _k = _k.strip()
                    _v = _v.strip().strip("'\"")
                    if _k and _k not in os.environ:
                        os.environ[_k] = _v
        break
if "_cand" in locals():
    del _cand

def _get_git_hash() -> str:
    """Read the short git commit hash, or return 'unknown' if not in a repo."""
    try:
        res = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=BASE_DIR,
            capture_output=True,
            text=True,
            timeout=5,
        )
        if res.returncode == 0:
            return res.stdout.strip()
    except Exception:
        pass
    return "unknown"

BOT_VERSION = _get_git_hash()

# --- Admin & Notification Settings --------------------------------------------
# Comma-separated list of Slack User IDs allowed to run admin commands
ADMIN_SLACK_USER_IDS = [
    uid.strip()
    for uid in os.environ.get("ADMIN_SLACK_USER_IDS", "").split(",")
    if uid.strip()
]

# Phase 2 (roster.py) replaces this with an admin-manageable list — delete this constant once that ships.
APPROVER_SLACK_USER_IDS = {"U07L2RFEPJ9"}

# Channel ID or Admin User ID where startup, crash, and system health alerts should be sent
ADMIN_ALERT_CHANNEL = os.environ.get("ADMIN_ALERT_CHANNEL", "").strip()

# A file upload to the buyer's DM is tried this many times before the admin is alerted (Ticket 127):
# on 2026-10-13 one "read operation timed out" left a buyer without their EPIF. Seconds waited
# before attempts 2 and 3.
DM_UPLOAD_ATTEMPTS = 3
DM_UPLOAD_WAITS = (2.0, 5.0)

# Channel ID where new purchase requests are posted for lab review (Ticket 15)
PURCHASING_CHANNEL = os.environ.get("PURCHASING_CHANNEL", "").strip()

# --- External Heartbeat (Dead-Man's Switch) -----------------------------------
HEALTHCHECK_URL = os.environ.get("HEALTHCHECK_URL", "").strip()
try:
    HEALTHCHECK_INTERVAL_SECONDS = int(os.environ.get("HEALTHCHECK_INTERVAL_SECONDS", "300"))
except ValueError:
    HEALTHCHECK_INTERVAL_SECONDS = 300

# --- Lock Queue Settings ------------------------------------------------------
try:
    EXCEL_QUEUE_POLL_INTERVAL = float(os.environ.get("EXCEL_QUEUE_POLL_INTERVAL", "5"))
except ValueError:
    EXCEL_QUEUE_POLL_INTERVAL = 5.0

try:
    EXCEL_LOCK_ALERT_TIMEOUT_SECONDS = float(os.environ.get("EXCEL_LOCK_ALERT_TIMEOUT_SECONDS", "600"))
except ValueError:
    EXCEL_LOCK_ALERT_TIMEOUT_SECONDS = 600.0

# --- Log file paths -----------------------------------------------------------
LOG_FILE = os.path.join(BASE_DIR, "p_bot.log")
REJECTIONS_LOG_FILE = os.path.join(BASE_DIR, "rejections.log")

# --- Where things are on disk -------------------------------------------------
# Point this at the OneDrive-synced copy of the workbook.
WORKBOOK_PATH = os.environ.get("PURCHASING_LOG_PATH", "")

# Point this at the OneDrive-synced EPIFs directory.
EPIFS_DIR = os.environ.get("EPIFS_DIR", "")

# Point this at the OneDrive-synced Order-Confirmations directory.
CONFIRMATIONS_DIR = os.environ.get("CONFIRMATIONS_DIR", "")

# Point this at the OneDrive-synced Quotes directory.
QUOTES_DIR = os.environ.get("QUOTES_DIR", "")

# Point this at the OneDrive-synced BOMs directory (Ticket 26).
BOMS_DIR = os.environ.get("BOMS_DIR", "")

EPIF_TEMPLATE_PATH = os.environ.get("EPIF_TEMPLATE_PATH", "")

# The lab BOM template (ADR 0019): the one spreadsheet layout the bot reads. Committed
# in the repo, so it resolves against BASE_DIR like the other repo-relative paths.
BOM_TEMPLATE_PATH = os.path.join(BASE_DIR, "templates", "HIRST_LAB_BOM_TEMPLATE.xlsx")
# Ticket 133: PyInstaller's onedir build unpacks `datas` under sys._MEIPASS (the _internal
# folder), not beside the executable where BASE_DIR points. p_bot.spec carries the template
# in `datas`, so in a frozen build fall back to the bundle when the exe-side copy is absent.
if getattr(sys, "frozen", False) and not os.path.isfile(BOM_TEMPLATE_PATH):
    _bundled = os.path.join(getattr(sys, "_MEIPASS", BASE_DIR), "templates", "HIRST_LAB_BOM_TEMPLATE.xlsx")
    if os.path.isfile(_bundled):
        BOM_TEMPLATE_PATH = _bundled

# Column headers of the template, in order. The reader matches these exactly (case and
# surrounding spaces ignored) and never guesses.
BOM_TEMPLATE_HEADERS = (
    "Item", "Description", "Product #", "Vendor", "Unit Cost", "Quantity", "Total Cost", "Notes",
)

# Most data rows a BOM may hold. The line items ride in the card message's Slack metadata
# (never in a button value). The Slack message-metadata page (https://docs.slack.dev/messaging/message-metadata/)
# could not be read when this was written, so no documented limit is cited: 50 is the
# fallback, and 50 rows of compact item dicts is well inside any size the page has
# described. Revisit if Slack's documented limit is found to be lower.
BOM_MAX_ROWS = 50

# One registry of storage settings: (env setting name, config attribute name, "file" | "folder")
# Order: PURCHASING_LOG_PATH, EPIFS_DIR, CONFIRMATIONS_DIR, QUOTES_DIR, BOMS_DIR, EPIF_TEMPLATE_PATH
STORAGE_SETTINGS: tuple[tuple[str, str, str], ...] = (
    ("PURCHASING_LOG_PATH", "WORKBOOK_PATH", "file"),
    ("EPIFS_DIR", "EPIFS_DIR", "folder"),
    ("CONFIRMATIONS_DIR", "CONFIRMATIONS_DIR", "folder"),
    ("QUOTES_DIR", "QUOTES_DIR", "folder"),
    ("BOMS_DIR", "BOMS_DIR", "folder"),
    ("EPIF_TEMPLATE_PATH", "EPIF_TEMPLATE_PATH", "file"),
)

SHEET_XML = "xl/worksheets/sheet1.xml"  # 'Order Log' is the first sheet
HEADER_ROW = 11                          # OrderLog table header
FIRST_DATA_ROW = 12
LAST_DATA_ROW = 1999                     # table ref is A11:Z1999

# Columns A (Order ID) and Z (Status) hold array formulas already filled down to
# row 1999. The bot must never write to them.
READ_ONLY_COLUMNS = ("A", "Z")

# Roles & Lists sheet and table constants
ROSTER_SHEET_XML = "xl/worksheets/sheet2.xml"
REQUESTERS_TABLE_XML = "xl/tables/table4.xml"
GRAD_STUDENTS_TABLE_XML = "xl/tables/table3.xml"
ROSTER_FIRST_DATA_ROW = 5
ROSTER_LAST_DATA_ROW = 49
ROSTER_COLUMN_REQUESTER = "D"
ROSTER_COLUMN_GRAD = "A"
ROSTER_XLSX_SYNC = os.environ.get("ROSTER_XLSX_SYNC", "true").lower() in ("true", "1", "yes")


# --- EPIF AcroForm field names -> Order Log columns ---------------------------
# Left side = exact /T name in the PDF. Right side = column letter.
FIELD_TO_COLUMN = {
    "What is being purchased": "C",
    "Purpose": "D",
    "Amount of Purchase": "H",
    "Vendor": "I",
    "Vendor Name": "J",
    "Email add": "K",
    "Date of Purchase": "M",
    "Name of System": "P",
    "room address": "Q",
    "Project ID Number": "R",
    "Fund": "S",
    "Asset ID": "T",
}

# Columns the EPIF simply does not carry. Filled from Slack or left blank.
COLUMN_REQUESTER = "B"      # from the Slack user who posted the thread
COLUMN_LINK = "E"           # first URL scraped out of the Purpose text
COLUMN_QTY = "F"            # not on the EPIF
COLUMN_UNIT_PRICE = "G"     # not on the EPIF
COLUMN_TOTAL_PRICE = "H"    # Amount / Total Price
# ADR 0017: a P-card is for orders under this amount; $5,000.00 exactly is refused.
PCARD_LIMIT = 5000.00
PCARD_LIMIT_MESSAGE = "P-card is for orders under $5,000. Pick Req/PO."
# ADR 0017 decision 4: shown under the Payment Method dropdown and returned by the FAQ.
# The bot explains the three-quote rule; it never counts quotes (decision 3).
PAYMENT_METHOD_HINT = (
    "P-card — the lab's university credit card, for orders under $5,000. "
    "Req/PO — a purchase order placed through UW purchasing; required at $5,000 and over "
    "(get 3 quotes), or whenever a vendor only accepts a PO."
)

# Ticket 117: said to the person who submits a Switch to EPIF after the buyer has processed the row.
SWITCH_REFUSED_PROCESSED = "Already processed — the path can't change now."

COLUMN_HOW_BUYING = "L"     # P-card / Req is NOT the same as Workday / Out-of-Network
COLUMN_DATE_OF_REQUEST = "M"# Date of Purchase / Request
COLUMN_URGENCY = "N"        # not on the EPIF
COLUMN_CATEGORY = "O"
COLUMN_DATE_PROCESSED = "U" # Date sent to Workday/Tina/Lisa (Date Processed)
COLUMN_DATE_CONFIRMED = "V" # Date order/package confirmed
COLUMN_DATE_DELIVERY = "W"  # Date package delivered to lab
COLUMN_RECEIVED_BY = "X"    # Lab member who received package
COLUMN_NOTES = "Y"          # Notes

EPIF_PI_AND_END_USER = "Charles Hirst"
EPIF_PI_FIELD = "PI of Funding"
EPIF_END_USER_FIELD = "Name"

# --- Checkbox field name -> the exact string in the EPIF Category dropdown -----
CHECKBOX_TO_CATEGORY = {
    "Researchlab suppliesCode to 3105": "Research/Lab Supplies (3105)",
    "Software": "Software",
    "Services": "Machining / Prof Services",
    "Computer Peripherals": "Computer Peripherals/Cables",
    "Membership": "Membership",
    "Repairs/Maintenance": "Repair & Maintenance",
    "Other": "Other",
    "Standalone equipment for more than 5k that is not part of a planned or "
    "current fabrication nor an": "Standalone Equipment >$5k (4602)",
    "Components for an approved fabrication code 4670 must be at least 200":
        "Fabrication Component (4670) > $200",
}

# Category minimums, read off the form's own wording (ticket 123): category value ->
# (amount, inclusive). Fabrication is "at least $200"; Standalone is "more than 5k".
CATEGORY_MINIMUMS = {
    "Fabrication Component (4670) > $200": (200.00, True),
    "Standalone Equipment >$5k (4602)": (5000.00, False),
}

PAYMENT_CHECKBOXES = ("PCard", "Req")

# --- Allowed values, mirrored from the 'Roles & Lists' sheet -------------------
# These are the dropdown sources. Writing a value that is not in these lists
# produces a cell Excel flags as invalid, so validate before writing.
VALID_PROJECT_IDS = {"PG000025831"}
VALID_FUNDS = {"133", "135", "150", "144", "233"}
VALID_DELIVERY_ROOMS = {"ERB 212", "ERB 839"}

# Slack user id -> the exact name in the Requester Name dropdown.
# Fill these in with real IDs (find them in Slack: profile -> More -> Copy member ID).
SLACK_USER_TO_REQUESTER = {
    # "U01ABCDEF": "Isaac",
}

# Phase 2 (roster.py) replaces this with a self-service list — delete this constant once that ships.
WORKDAY_VENDORS = {
    "Abcam", "Airgas", "Apple", "B&H Photo", "Bio Rad", "CDWG", "Dell",
    "Dot Scientific", "Eppendorf", "Fastenal", "First Supply", "Fisher Scientific",
    "Grainger", "IDT", "Life Technologies", "McKesson", "Medline", "MIDSCI",
    "MSC", "Neta Scientific", "Newark", "New England BioLabs", "Promega",
    "Qiagen", "Rainin", "Santa Cruz", "Sigma Aldrich", "Staples", "USA Scientific",
    "Vanguard", "VWR-AVANTOR", "Anixter", "Kranz", "NASSCO",
}

VENDOR_OTHER_OPTION = "None of these — this will be an EPIF order"
WORKDAY_PAYMENT_METHOD = "Workday"
NEAR_MISS_VENDOR_RATIO = 0.85

TRIGGER_KEYWORD = "approved"
APPROVAL_KEYWORDS = (TRIGGER_KEYWORD,)
ASSIGN_KEYWORDS = ("assign", "assigned")
PROCESSED_KEYWORDS = ("processed", "processing", "ordered", "submitted", "submit")  # "submitted"/"submit" are silent backwards-compat aliases
CONFIRM_KEYWORDS = ("confirmed", "confirm", "package confirmed", "order confirmed")
DELIVERED_KEYWORDS = ("delivered", "received", "package delivered", "package received")
QUOTE_KEYWORDS = ("quote", "save quote", "quotes")
HELP_KEYWORDS = ("help", "commands", "cmd", "usage")
STATUS_KEYWORDS = ("status", "health", "system", "uptime")
QUEUE_KEYWORDS = ("queue", "lock queue", "writes")
LOGS_KEYWORDS = ("logs", "log")
UPDATE_KEYWORDS = ("update", "git pull")
RESTART_KEYWORDS = ("restart", "reboot")
REMOVE_VENDOR_KEYWORDS = ("remove-vendor", "delete-vendor")
ADD_VENDOR_KEYWORDS = ("add-vendor",)
PROMOTE_ADMIN_KEYWORDS = ("promote-admin", "add-admin")
ADD_APPROVER_KEYWORDS = ("add-approver",)
REMOVE_APPROVER_KEYWORDS = ("remove-approver",)
ADD_BUYER_KEYWORDS = ("add-buyer",)
REMOVE_BUYER_KEYWORDS = ("remove-buyer",)
REMOVE_MEMBER_KEYWORDS = ("remove-member",)

ALL_KEYWORD_TUPLES = (
    APPROVAL_KEYWORDS,
    ASSIGN_KEYWORDS,
    PROCESSED_KEYWORDS,
    CONFIRM_KEYWORDS,
    DELIVERED_KEYWORDS,
    QUOTE_KEYWORDS,
    HELP_KEYWORDS,
    STATUS_KEYWORDS,
    QUEUE_KEYWORDS,
    LOGS_KEYWORDS,
    UPDATE_KEYWORDS,
    RESTART_KEYWORDS,
    REMOVE_VENDOR_KEYWORDS,
    ADD_VENDOR_KEYWORDS,
    PROMOTE_ADMIN_KEYWORDS,
    ADD_APPROVER_KEYWORDS,
    REMOVE_APPROVER_KEYWORDS,
    ADD_BUYER_KEYWORDS,
    REMOVE_BUYER_KEYWORDS,
    REMOVE_MEMBER_KEYWORDS,
)

KEYWORD_SUGGESTION_CUTOFF = 0.75

ADMIN_ONLY_KEYWORDS = (
    "promote-admin",
    "add-approver",
    "remove-approver",
    "add-buyer",
    "remove-buyer",
    "remove-member",
    "add-vendor",
    "remove-vendor",
    "update",
    "restart",
    "logs",
)

CANONICAL_KEYWORDS = tuple(kw[0] for kw in ALL_KEYWORD_TUPLES)

# Message subtypes allowed through to command/drop handling (ADR 0010 Decision 6)
HUMAN_MESSAGE_SUBTYPES = (None, "file_share", "thread_broadcast")


# --- Phase 4 Staged Purchasing Interview Constants ----------------------------
# The categories for which Asset ID and Name of System are required (Screen 3)
ASSET_REQUIRED_CATEGORIES = {"Fabrication Component (4670) > $200"}

# Ordered list of (value, display_text) pairs covering every category in CHECKBOX_TO_CATEGORY
# Display text is plain language for first-time users; value must strictly match CHECKBOX_TO_CATEGORY values.
CATEGORY_DISPLAY_ORDER = [
    ("Research/Lab Supplies (3105)", "Research / Lab Supplies (3105) — most consumables and small parts"),
    ("Computer Peripherals/Cables", "Computer Peripherals / Cables — monitors, adapters, cables"),
    ("Software", "Software — licenses, subscriptions, toolboxes"),
    ("Machining / Prof Services", "Machining / Professional Services — custom fab, testing services"),
    ("Repair & Maintenance", "Repair & Maintenance — equipment service, replacement parts"),
    ("Fabrication Component (4670) > $200", "Fabrication Component (4670) > $200 — parts built into an active system"),
    ("Standalone Equipment >$5k (4602)", "Standalone Equipment > $5k (4602) — major standalone capital gear"),
    ("Membership", "Membership — professional societies, journal access"),
    ("Other", "Other — anything not covered above"),
]

# Callback IDs for modals
STAGE1_CALLBACK_ID = "purchase_stage1_submit"
STAGE2_CALLBACK_ID = "purchase_stage2_submit"
STAGE3_CALLBACK_ID = "purchase_stage3_submit"
REPLACE_BOM_CALLBACK_ID = "replace_bom_submit"  # Ticket 137: the Replace BOM upload form
BOM_CHECK_CALLBACK_ID = "bom_check_submit"  # Ticket 134 / ADR 0019 decision 5: the screen after a BOM is submitted
BOM_CHECK_PREVIEW_ROWS = 40  # rows listed on the check view; the rest are counted
ROSTER_SET_NAME_CALLBACK_ID = "roster_set_name_submit"
ITEMS_CALLBACK_ID = "purchase_items_submit"
EDIT_CALLBACK_ID = "purchase_edit_submit"

# Field length limits to keep accumulated private_metadata well under Slack's 3000-char limit
MAX_ITEM_DESCRIPTION_LEN = 150
MAX_PURPOSE_LEN = 900
# Slack rejects a card whose button `value` is over 2,000 characters (invalid_blocks, seen
# 2026-09-29 and 2026-10-13). A card whose full value would not fit carries a slim value
# instead (Ticket 129); these are the keys of the request that stay in it.
BUTTON_VALUE_MAX = 2000
SLIM_VALUE_REQUEST_KEYS = ("thread_ts", "assignee_id", "assignee", "user_id", "source", "epif_file")
MAX_LINE_ITEMS_LEN = 1500  # Ticket 28: keeps carried stage2 state under 3000 chars on Screen 3

# Action IDs for Block Kit elements (Ticket 17, Ticket 22, Ticket 27)
ACTION_REQ_ASSIGN_SELECT = "req_assign_select"
ACTION_OPEN_ROSTER_SET_NAME = "open_roster_set_name"
ACTION_OPEN_NUDGE_SETTINGS = "open_nudge_settings"
NUDGE_SETTINGS_CALLBACK_ID = "nudge_settings_submit"
ACTION_REQ_ITEMS = "req_items"
ACTION_SEND_BOM_TEMPLATE = "send_bom_template"  # Ticket 133 / ADR 0019: DMs the BOM template from Screen 2
ACTION_REQ_EDIT = "req_edit"
ACTION_REQ_SWITCH_EPIF = "req_switch_epif"
ACTION_NUDGE_DELIVERED = "nudge_delivered"  # ADR 0013 decision 4 / Ticket 90: the nudge card's Delivered button
ACTION_NUDGE_NOT_YET = "nudge_not_yet"  # ADR 0013 decision 5 / Ticket 92: "Not yet" on the delivered nudge card
ACTION_SET_EXPECTED_DELIVERY = "set_expected_delivery"  # ADR 0013 decision 5 / Ticket 91
EXPECTED_DELIVERY_CALLBACK_ID = "expected_delivery_submit"
ACTION_REPLACE_BOM = "replace_bom"  # Ticket 137 / ADR 0019 decision 8: upload the lab-template BOM again before Processed
ACTION_RESEND_EPIF = "resend_epif"  # Ticket 128: buyer re-sends the archived EPIF, BOM and quotes to their DM
ACTION_CHANGE_EPIF_DATE = "change_epif_date"  # Ticket 125: buyer re-dates the Filled EPIF before Processed
CHANGE_EPIF_DATE_CALLBACK_ID = "change_epif_date_submit"

# Action IDs for DM card buttons (Ticket 67 / ADR 0010)
ACTION_DM_REQ_PROCESSED = "dm_req_processed"
ACTION_DM_REQ_CONFIRMED = "dm_req_confirmed"
ACTION_DM_REQ_DELIVERED = "dm_req_delivered"
ACTION_DM_REQ_ASSIGN_SELECT = "dm_req_assign_select"



