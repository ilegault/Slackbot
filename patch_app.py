with open('src/app.py', 'r') as f:
    content = f.read()

handler_code = """
@app.action("req_switch_epif")
def handle_req_switch_epif(ack, body, respond, client):
    \"\"\"Handle clicking 'Switch to EPIF' on an approved Workday request.\"\"\"
    ack()
    user_id = body.get("user", {}).get("id")
    channel_id = body.get("channel", {}).get("id")
    msg_ts = body.get("message", {}).get("ts")
    thread_ts = body.get("container", {}).get("thread_ts") or msg_ts

    action = body.get("actions", [{}])[0]
    val_data = json.loads(action.get("value") or "{}")
    req_data = val_data.get("request", {})
    parsed_request = req_data.get("parsed", req_data)

    # Permission check: requester, assignee, unassigned buyer, or admin
    requester_name = val_data.get("requester")
    is_requester = (requester_name and requester_name == slack_io.resolve_requester(client, user_id)) or (user_id == req_data.get("user_id"))
    is_assignee = user_id == req_data.get("assignee_id")
    is_unassigned_buyer = (not req_data.get("assignee_id")) and roster.is_buyer(user_id)
    is_admin = admin.is_admin_user(user_id)

    if not (is_requester or is_assignee or is_unassigned_buyer or is_admin):
        log.warning("Unauthorized user %s attempted to switch to EPIF", user_id)
        slack_io.deny(respond, "🔒 Only the requester, assignee, or admin can switch this to EPIF.")
        return

    # Check date processed in row
    row_num = req_data.get("row")
    if row_num:
        try:
            row_info = log_writer.get_row_info(row_num)
            if row_info.get("date_processed"):
                slack_io.deny(respond, "This request has already been processed and cannot be switched to EPIF.")
                return
        except Exception as e:
            log.error("Could not fetch row info for switch epif check: %s", e)

    vendor = parsed_request.get("vendor", "")

    meta = {
        "channel_id": channel_id,
        "thread_ts": thread_ts,
        "card_ts": msg_ts,
        "is_edit": True,
        "is_switch_epif": True,
        "vendor_choice": vendor,
        "route": "epif",
        "parsed": parsed_request,
        "user_id": user_id,
        "items": req_data.get("items", []),
        "shipping": req_data.get("shipping", 0.0)
    }

    view = blocks.build_stage2_view(meta)
    client.views_open(trigger_id=body["trigger_id"], view=view)
"""

search_str = """@app.action("req_cancel")
def handle_req_cancel_action(ack, body, respond, client):"""

content = content.replace(search_str, handler_code + "\n" + search_str)

with open('src/app.py', 'w') as f:
    f.write(content)
