"""Decide whether a parsed EPIF is good enough to log.

Every rule returns a sentence a grad student can act on. If the list comes back
empty, the row is safe to write.
"""
try:
    from . import config, roster
except ImportError:
    import config
    import roster


def pcard_problem(payment_method, total_price):
    """Return the P-card limit message, or None (ADR 0017).

    WHY: a P-card is only for orders under config.PCARD_LIMIT; at that amount or
    more the lab must use a Req/PO. One pure rule so approval, Edit, dropped EPIFs
    and the Screen 2 submit all refuse the same way.
    """
    if (
        isinstance(payment_method, str)
        and payment_method.strip().lower() == "p-card"
        and isinstance(total_price, (int, float))
        and not isinstance(total_price, bool)
        and total_price >= config.PCARD_LIMIT
    ):
        return config.PCARD_LIMIT_MESSAGE
    return None


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

    if parsed.get("category_error"):
        problems.append(
            f"Section 2 category: {parsed['category_error']} - tick exactly one box."
        )

    if parsed["payment_method"] is None:
        problems.append("Tick either the P-card box or the Req/PO box (exactly one).")

    pcard = pcard_problem(parsed["payment_method"], parsed["total_price"])
    if pcard is not None:
        problems.append(pcard)

    # --- the Slack side --------------------------------------------------------
    valid_requesters = roster.get_valid_requesters() if hasattr(roster, "get_valid_requesters") else set()
    if requester_name is None:
        problems.append(
            "I don't know which lab member you are - your Slack ID isn't in the "
            "requester map yet. Ask Isaac to add it."
        )
    elif requester_name not in valid_requesters:
        problems.append(
            f"'{requester_name}' is not in the Requester Name dropdown list."
        )

    return problems
