import re

with open("src/lifecycle.py", "r") as f:
    content = f.read()

# Replace signature
old_sig = """def _send_assignee_dm(
    client,
    assignee_id: str,
    assignee_name: str,
    email_draft: str,
    item_desc: str,
    row,
    bom_path: str | None = None,
    bom_fname: str | None = None,
) -> None:"""

new_sig = """def _send_assignee_dm(
    client,
    assignee_id: str,
    assignee_name: str,
    email_draft: str,
    item_desc: str,
    row,
    bom_path: str | None = None,
    bom_fname: str | None = None,
    route: str = "workday",
    parsed: dict | None = None,
) -> None:"""

content = content.replace(old_sig, new_sig)

# Replace DM text creation
old_dm_text_logic = """    row_dm_str = f" in *Row {row}*" if row else ""
    dm_text = (
        f"Hi {assignee_name}! You've been assigned the purchase request for *{item_desc}*{row_dm_str}.\\n\\n"
        f"📋 *Next Steps:*\\n"
        f"1. Submit via Workday or send this email to purchasing (Tina / Ally / Lisa):\\n\\n"
        f"```\\n{email_draft}\\n```\\n\\n"
        f"2. Use the buttons on your purchase request in the purchasing channel to update its status when processed, confirmed, and delivered!"
    )
    if bom_fname:
        dm_text += f"\\n\\n📊 The BOM spreadsheet *{bom_fname}* is attached."
"""

new_dm_text_logic = """    row_dm_str = f" in *Row {row}*" if row else ""
    if route == "workday":
        vendor = (parsed or {}).get("vendor") or "Vendor"
        price = (parsed or {}).get("total_price")
        if isinstance(price, (int, float)):
            price_str = f"${price:,.2f}"
        elif price:
            price_str = str(price)
            if not price_str.startswith("$"):
                price_str = f"${price_str}"
        else:
            price_str = "$0.00"
        link = (parsed or {}).get("link") or "No link"
        dm_text = (
            f"Place this in Workday:\\n"
            f"• *Item:* {item_desc}\\n"
            f"• *Vendor:* {vendor}\\n"
            f"• *Price:* {price_str}\\n"
            f"• *Link:* {link}\\n"
            f"• *Row:* {row or 'None'}\\n\\n"
            f"Use the buttons on your purchase request in the purchasing channel to update its status when processed, confirmed, and delivered!"
        )
    else:
        dm_text = (
            f"Hi {assignee_name}! You've been assigned the purchase request for *{item_desc}*{row_dm_str}.\\n\\n"
            f"📋 *Next Steps:*\\n"
            f"1. Submit via Workday or send this email to purchasing (Tina / Ally / Lisa):\\n\\n"
            f"```\\n{email_draft}\\n```\\n\\n"
            f"2. Use the buttons on your purchase request in the purchasing channel to update its status when processed, confirmed, and delivered!"
        )
        if bom_fname:
            dm_text += f"\\n\\n📊 The BOM spreadsheet *{bom_fname}* is attached."
"""

content = content.replace(old_dm_text_logic, new_dm_text_logic)

# Replace attachment logic
old_attach_logic = """    if bom_path and bom_fname and os.path.exists(bom_path):"""
new_attach_logic = """    if route == "epif" and bom_path and bom_fname and os.path.exists(bom_path):"""

content = content.replace(old_attach_logic, new_attach_logic)

with open("src/lifecycle.py", "w") as f:
    f.write(content)
