with open('src/blocks.py', 'r') as f:
    content = f.read()

search_str = """
    if is_edit:
        callback_id = config.EDIT_CALLBACK_ID
        title_text = "Edit Request"
        submit_text = "Save changes"
    else:
        callback_id = config.STAGE2_CALLBACK_ID
        title_text = "Purchase Details"
        submit_text = "Continue"
"""

replace_str = """
    if is_switch_epif:
        callback_id = config.SWITCH_EPIF_CALLBACK_ID
        title_text = "Switch to EPIF"
        submit_text = "Switch to EPIF"
    elif is_edit:
        callback_id = config.EDIT_CALLBACK_ID
        title_text = "Edit Request"
        submit_text = "Save changes"
    else:
        callback_id = config.STAGE2_CALLBACK_ID
        title_text = "Purchase Details"
        submit_text = "Continue"
"""
if search_str in content:
    content = content.replace(search_str, replace_str)
else:
    print("Could not find search_str")

with open('src/blocks.py', 'w') as f:
    f.write(content)
