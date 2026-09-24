import re

with open("src/lifecycle.py", "r") as f:
    content = f.read()

# finalize_purchase_request changes
old_fin_req_str1 = """        if assignee_id and assignee_name:
            say(
                text=(
                    f"Logged to row {row}: {parsed['item_description']} — "
                    f"${parsed['total_price']:,.2f} from {parsed['vendor']} "
                    f"({parsed['category']}).\\n"
                    f"{saved_str}"
                    f"📢 {ping_user}'s request is approved!\\n"
                    f"👤 Assigned to <@{assignee_id}> ({assignee_name}) to process in Workday / ShopUW."
                    + (f" ({input_note})" if input_note else "")
                ),
                thread_ts=thread_ts,
            )"""

new_fin_req_str1 = """        if assignee_id and assignee_name:
            route = interview.get_request_route(parsed, bool(pdf_bytes))
            action_text = "to place in Workday." if route == "workday" else "to email to purchasing."
            say(
                text=(
                    f"Logged to row {row}: {parsed['item_description']} — "
                    f"${parsed['total_price']:,.2f} from {parsed['vendor']} "
                    f"({parsed['category']}).\\n"
                    f"{saved_str}"
                    f"📢 {ping_user}'s request is approved!\\n"
                    f"👤 Assigned to <@{assignee_id}> ({assignee_name}) {action_text}"
                    + (f" ({input_note})" if input_note else "")
                ),
                thread_ts=thread_ts,
            )"""

old_fin_req_str2 = """            _send_assignee_dm(
                client=client,
                assignee_id=assignee_id,
                assignee_name=assignee_name,
                email_draft=email_draft,
                item_desc=item_desc,
                row=row,
                bom_path=saved_bom_path,
                bom_fname=bom_fname,
            )"""

new_fin_req_str2 = """            _send_assignee_dm(
                client=client,
                assignee_id=assignee_id,
                assignee_name=assignee_name,
                email_draft=email_draft,
                item_desc=item_desc,
                row=row,
                bom_path=saved_bom_path,
                bom_fname=bom_fname,
                route=route,
                parsed=parsed,
            )"""

old_fin_req_str3 = """        else:
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

new_fin_req_str3 = """        elif not refusal_msg:
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

content = content.replace(old_fin_req_str1, new_fin_req_str1)
content = content.replace(old_fin_req_str2, new_fin_req_str2)
# Since the 'elif refusal_msg:' is handled implicitly via the old 'else:' handling (wait, the logic is if assignee -> elif refusal_msg -> else).
# So we need to replace the 'else:' block precisely.
# Note: Python's replace might not work if there's any slight difference. We should probably use regex or check if the exact string matches.

import textwrap
content = content.replace(textwrap.dedent("""\
        else:
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
            )"""), textwrap.dedent("""\
        else:
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
            )"""))


# handle_assign changes
old_ha_str1 = """    if current_state == "posted":
        # Selecting a buyer on the posted card records the selection on the card; approval remains a second click.
        return True

    say(text=f"👤 Assigned to <@{target_user_id}> ({target_name}) to process in Workday / ShopUW.", thread_ts=thread_ts)

    # Email draft DM (with optional BOM) to assignee — single implementation via _send_assignee_dm
    row = slack_io.find_row_in_thread(client, channel, thread_ts)
    row_info = log_writer.get_row_info(row) if row else {}
    draft_data = dict(req_data.get("parsed", req_data))
    for k, v in row_info.items():
        if k not in draft_data or not draft_data[k]:
            draft_data[k] = v
    bom_fname = req_data.get("bom_file")
    bom_path = os.path.join(config.BOMS_DIR, bom_fname) if bom_fname else None
    email_draft = text_rules.generate_email_draft(draft_data, target_name, bom_filename=bom_fname)
    item_desc = draft_data.get("item_description") or "supplies"
    _send_assignee_dm(
        client=client,
        assignee_id=target_user_id,
        assignee_name=target_name,
        email_draft=email_draft,
        item_desc=item_desc,
        row=row,
        bom_path=bom_path,
        bom_fname=bom_fname,
    )"""

new_ha_str1 = """    if current_state == "posted":
        # Selecting a buyer on the posted card records the selection on the card; approval remains a second click.
        return True

    draft_data = dict(req_data.get("parsed", req_data))
    route = interview.get_request_route(req_data)
    action_text = "to place in Workday." if route == "workday" else "to email to purchasing."

    say(text=f"👤 Assigned to <@{target_user_id}> ({target_name}) {action_text}", thread_ts=thread_ts)

    # Email draft DM (with optional BOM) to assignee — single implementation via _send_assignee_dm
    row = slack_io.find_row_in_thread(client, channel, thread_ts)
    row_info = log_writer.get_row_info(row) if row else {}
    for k, v in row_info.items():
        if k not in draft_data or not draft_data[k]:
            draft_data[k] = v
    bom_fname = req_data.get("bom_file")
    bom_path = os.path.join(config.BOMS_DIR, bom_fname) if bom_fname else None
    email_draft = text_rules.generate_email_draft(draft_data, target_name, bom_filename=bom_fname)
    item_desc = draft_data.get("item_description") or "supplies"
    _send_assignee_dm(
        client=client,
        assignee_id=target_user_id,
        assignee_name=target_name,
        email_draft=email_draft,
        item_desc=item_desc,
        row=row,
        bom_path=bom_path,
        bom_fname=bom_fname,
        route=route,
        parsed=draft_data,
    )"""

content = content.replace(old_ha_str1, new_ha_str1)

with open("src/lifecycle.py", "w") as f:
    f.write(content)
