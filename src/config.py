"""All the lab-specific constants live here, nothing else.

Everything in this file was read off the real EPIF_TEMPLATE_blank.pdf and the real
Purchasing-Log.xlsx, so if either of those changes, this is the only file to edit.
"""
import os
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

BOT_VERSION = "1.2.0"

# --- Admin & Notification Settings --------------------------------------------
# Comma-separated list of Slack User IDs allowed to run admin commands
ADMIN_SLACK_USER_IDS = [
    uid.strip()
    for uid in os.environ.get("ADMIN_SLACK_USER_IDS", "").split(",")
    if uid.strip()
]

# Channel ID or Admin User ID where startup, crash, and system health alerts should be sent
ADMIN_ALERT_CHANNEL = os.environ.get("ADMIN_ALERT_CHANNEL", "").strip()

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
WORKBOOK_PATH = os.environ.get(
    "PURCHASING_LOG_PATH",
    os.path.expanduser(r"C:\Users\IGLeg\OneDrive - UW-Madison\Shortcuts\Charles Hirst's files - Hirst-Lab\Purchasing\Purchasing-Log.xlsx"),
)

# Point this at the OneDrive-synced EPIFs directory.
EPIFS_DIR = os.environ.get(
    "EPIFS_DIR",
    os.path.expanduser(r"C:\Users\IGLeg\OneDrive - UW-Madison\Shortcuts\Charles Hirst's files - Hirst-Lab\Purchasing\EPIFs"),
)

# Point this at the OneDrive-synced Order-Confirmations directory.
CONFIRMATIONS_DIR = os.environ.get(
    "CONFIRMATIONS_DIR",
    os.path.expanduser(r"C:\Users\IGLeg\OneDrive - UW-Madison\Shortcuts\Charles Hirst's files - Hirst-Lab\Purchasing\Order-Confirmations"),
)

# Point this at the OneDrive-synced Quotes directory.
QUOTES_DIR = os.environ.get(
    "QUOTES_DIR",
    os.path.expanduser(r"C:\Users\IGLeg\OneDrive - UW-Madison\Shortcuts\Charles Hirst's files - Hirst-Lab\Purchasing\Quotes"),
)

SHEET_XML = "xl/worksheets/sheet1.xml"  # 'Order Log' is the first sheet
HEADER_ROW = 11                          # OrderLog table header
FIRST_DATA_ROW = 12
LAST_DATA_ROW = 1999                     # table ref is A11:Z1999

# Columns A (Order ID) and Z (Status) hold array formulas already filled down to
# row 1999. The bot must never write to them.
READ_ONLY_COLUMNS = ("A", "Z")

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
COLUMN_HOW_BUYING = "L"     # P-card / Req is NOT the same as Workday / Out-of-Network
COLUMN_DATE_OF_REQUEST = "M"# Date of Purchase / Request
COLUMN_URGENCY = "N"        # not on the EPIF
COLUMN_CATEGORY = "O"
COLUMN_DATE_PROCESSED = "U" # Date submitted to Workday/Tina/Lisa
COLUMN_DATE_CONFIRMED = "V" # Date order/package confirmed
COLUMN_DATE_DELIVERY = "W"  # Date package delivered to lab
COLUMN_RECEIVED_BY = "X"    # Lab member who received package
COLUMN_NOTES = "Y"          # Notes

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

PAYMENT_CHECKBOXES = ("PCard", "Req")

# --- Allowed values, mirrored from the 'Roles & Lists' sheet -------------------
# These are the dropdown sources. Writing a value that is not in these lists
# produces a cell Excel flags as invalid, so validate before writing.
VALID_PROJECT_IDS = {"PG000025831"}
VALID_FUNDS = {"133", "135", "150", "144", "233"}
VALID_DELIVERY_ROOMS = {"ERB 212", "ERB 839"}
VALID_REQUESTERS = {
    "Isaac", "Smeet", "Dylan", "Charlie H.", "Alex", "Casey", "Prof. Hirst",
    "Copeland", "Erich", "Finn", "Eddie", "Katarina", "Keyvan",
}

# Grad students who have Workday / purchasing admin permissions
GRAD_STUDENT_BUYERS = {"Isaac", "Dylan", "Smeet", "Finn"}

# Slack user id -> the exact name in the Requester Name dropdown.
# Fill these in with real IDs (find them in Slack: profile -> More -> Copy member ID).
SLACK_USER_TO_REQUESTER = {
    # "U01ABCDEF": "Isaac",
}

TRIGGER_KEYWORD = "approved"
CLAIM_KEYWORDS = ("claim", "i will order", "i'll order", "take", "claiming")
SUBMIT_KEYWORDS = ("submitted", "submit", "processed", "processing", "ordered")
CONFIRM_KEYWORDS = ("confirmed", "confirm", "package confirmed", "order confirmed")
DELIVERED_KEYWORDS = ("delivered", "received", "package delivered", "package received")
QUOTE_KEYWORDS = ("quote", "save quote", "quotes")
HELP_KEYWORDS = ("help", "commands", "cmd", "usage")
STATUS_KEYWORDS = ("status", "health", "system", "uptime")
QUEUE_KEYWORDS = ("queue", "lock queue", "writes")
LOGS_KEYWORDS = ("logs", "log")
UPDATE_KEYWORDS = ("update", "git pull")
RESTART_KEYWORDS = ("restart", "reboot")

