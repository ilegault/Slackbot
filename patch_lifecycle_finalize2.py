import re

with open("src/lifecycle.py", "r") as f:
    content = f.read()

old_block = """        else:
            say(
                text=(
                    f"Logged to row {row}: {parsed['item_description']} — "
                    f"${parsed['total_price']:,.2f} from {parsed['vendor']} "
                    f"({parsed['category']}).\\n"
                    f"{saved_str}"
                    f"📢 {ping_user}'s request is approved!\\n"
                    f"⚠️ *Needs a Grad Student Buyer to process in Workday / ShopUW.*\\n"
                    f"Please assign a buyer: `@Purchasing assign @buyer`"
                ),
                thread_ts=thread_ts,
            )"""

new_block = """        else:
            route = interview.get_request_route(parsed, bool(pdf_bytes))
            action_text = "to place in Workday." if route == "workday" else "to email to purchasing."
            say(
                text=(
                    f"Logged to row {row}: {parsed['item_description']} — "
                    f"${parsed['total_price']:,.2f} from {parsed['vendor']} "
                    f"({parsed['category']}).\\n"
                    f"{saved_str}"
                    f"📢 {ping_user}'s request is approved!\\n"
                    f"⚠️ *Needs a buyer {action_text}*\\n"
                    f"Please assign a buyer: `@Purchasing assign @buyer`"
                ),
                thread_ts=thread_ts,
            )"""

content = content.replace(old_block, new_block)

with open("src/lifecycle.py", "w") as f:
    f.write(content)
