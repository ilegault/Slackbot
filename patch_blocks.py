import re

with open('src/blocks.py', 'r') as f:
    content = f.read()

# First, import interview
if 'import interview' not in content:
    content = content.replace('from . import admin, bom, config, epif_parser, roster, slack_io', 'from . import admin, bom, config, epif_parser, interview, roster, slack_io')

# Next, add the button logic in build_request_blocks
# Find the end of `if state in primary_buttons:` section (where picker_elem is appended)

search_str = """
            if assignee_id:
                picker_elem["initial_user"] = assignee_id
            elements.append(picker_elem)"""
replace_str = search_str + """
        if state == "approved" and not request.get("date_processed") and interview.get_request_route(request) == "workday":
            elements.append({
                "type": "button",
                "text": {"type": "plain_text", "text": "Switch to EPIF", "emoji": True},
                "action_id": "req_switch_epif",
                "value": btn_value,
            })"""

if search_str in content:
    content = content.replace(search_str, replace_str)
else:
    print("Failed to find insertion point for req_switch_epif button")


with open('src/blocks.py', 'w') as f:
    f.write(content)
