"""Decide whether a parsed EPIF is good enough to log.

Every rule returns a sentence a grad student can act on. If the list comes back
empty, the row is safe to write.
"""
try:
    from . import config
except ImportError:
    import config


def validate(parsed: dict, requester_name=None) -> list:
    problems = []

    if not parsed["item_description"]:
        problems.append("Section 1 (What) is blank - describe the item being purchased.")

    if not parsed["purpose"]:
        problems.append("Section 2 (Why Necessary/Purpose) is blank.")

    if parsed["total_price"] is None:
        problems.append("Amt of Purchase is blank or not a number.")

    if not parsed["vendor"]:
        problems.append("Vendor is blank.")

    if not parsed["vendor_contact_email"]:
        problems.append("Vendor contact Email is blank.")
    elif "@" not in parsed["vendor_contact_email"]:
        problems.append(
            f"Vendor contact Email '{parsed['vendor_contact_email']}' is not an "
            "email address."
        )

    if parsed["date_of_purchase"] is None:
        problems.append("Today's Date is blank or unreadable (use MM/DD/YY).")

    # --- dropdown-constrained fields ------------------------------------------
    # These have to match the Roles & Lists sheet exactly or Excel flags the cell.
    project_id = parsed["project_id"]
    if not project_id:
        problems.append("Project ID is blank.")
    elif project_id not in config.VALID_PROJECT_IDS:
        problems.append(
            f"Project ID '{project_id}' is not in the Project ID list "
            f"({', '.join(sorted(config.VALID_PROJECT_IDS))})."
        )

    fund = parsed["fund"]
    if not fund:
        problems.append("Fund is blank.")
    elif fund not in config.VALID_FUNDS:
        problems.append(
            f"Fund '{fund}' is not one of {', '.join(sorted(config.VALID_FUNDS))}."
        )

    room = parsed["delivery_room"]
    if not room:
        problems.append("Campus Address for Delivery (Bldg and Room) is blank.")
    elif room not in config.VALID_DELIVERY_ROOMS:
        problems.append(
            f"Delivery room '{room}' is not in the Delivery Room list "
            f"({', '.join(sorted(config.VALID_DELIVERY_ROOMS))})."
        )

    if parsed["category_error"]:
        problems.append(
            f"Section 2 category: {parsed['category_error']} - tick exactly one box."
        )

    if parsed["payment_method"] is None:
        problems.append("Tick either the P-card box or the Req/PO box (exactly one).")

    # --- the Slack side --------------------------------------------------------
    if requester_name is None:
        problems.append(
            "I don't know which lab member you are - your Slack ID isn't in the "
            "requester map yet. Ask Isaac to add it."
        )
    elif requester_name not in config.VALID_REQUESTERS:
        problems.append(
            f"'{requester_name}' is not in the Requester Name dropdown list."
        )

    return problems
