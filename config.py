"""All the lab-specific constants live here, nothing else.

Everything in this file was read off the real EPIF_TEMPLATE_blank.pdf and the real
Purchasing-Log.xlsx, so if either of those changes, this is the only file to edit.
"""
import os

# --- Where things are on disk -------------------------------------------------
# Point this at the OneDrive-synced copy of the workbook.
WORKBOOK_PATH = os.environ.get(
    "PURCHASING_LOG_PATH",
    os.path.expanduser("~/OneDrive/MUFFIN/Purchasing-Log.xlsx"),
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
COLUMN_HOW_BUYING = "L"     # P-card / Req is NOT the same as Workday / Out-of-Network
COLUMN_URGENCY = "N"        # not on the EPIF
COLUMN_CATEGORY = "O"

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

# Slack user id -> the exact name in the Requester Name dropdown.
# Fill these in with real IDs (find them in Slack: profile -> More -> Copy member ID).
SLACK_USER_TO_REQUESTER = {
    # "U01ABCDEF": "Isaac",
}

TRIGGER_KEYWORD = "approved"
