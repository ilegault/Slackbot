with open('src/app.py', 'r') as f:
    content = f.read()

handler_code = """
@app.view(config.SWITCH_EPIF_CALLBACK_ID)
def handle_switch_epif_submit(ack, body, client, view):
    \"\"\"Handle submission of the Switch to EPIF modal.\"\"\"
    meta = json.loads(view["private_metadata"])
    channel = meta["channel_id"]
    thread_ts = meta["thread_ts"]
    card_ts = meta["card_ts"]
    user_id = body.get("user", {}).get("id")
    _ = user_id

    # Re-check card state
    card_payload = slack_io.get_card_payload(client, channel, thread_ts, card_ts)
    if not card_payload or card_payload.get("state") != "approved":
        ack(response_action="errors", errors={"block_item_description": "This request is no longer approved."})
        return

    req_data = card_payload.get("request", {})
    row_num = req_data.get("row")
    if not row_num:
        ack(response_action="errors", errors={"block_item_description": "This request has no row number."})
        return

    state_vals = view["state"]["values"]

    # Extract values
    item = state_vals.get("block_item_description", {}).get("item_description", {}).get("value")
    purpose = state_vals.get("block_purpose", {}).get("purpose", {}).get("value")
    link = state_vals.get("block_link", {}).get("link", {}).get("value", "")
    total_price = state_vals.get("block_total_price", {}).get("total_price", {}).get("value")
    if total_price:
        try:
            total_price = float(str(total_price).replace('$', '').replace(',', '').strip())
        except ValueError:
            pass
    date_str = state_vals.get("block_date_of_purchase", {}).get("date_of_purchase", {}).get("selected_date")
    room = state_vals.get("block_delivery_room", {}).get("delivery_room", {}).get("value")
    project = state_vals.get("block_project_id", {}).get("project_id", {}).get("value")
    fund = state_vals.get("block_fund", {}).get("fund", {}).get("value")
    category = state_vals.get("block_category", {}).get("category", {}).get("selected_option", {}).get("value")
    line_items_str = state_vals.get("block_line_items", {}).get("line_items", {}).get("value", "")

    # Optional fields
    asset_id = ""
    if "block_asset_id" in state_vals:
        asset_id = state_vals["block_asset_id"].get("asset_id", {}).get("value", "")
    name_of_system = ""
    if "block_name_of_system" in state_vals:
        name_of_system = state_vals["block_name_of_system"].get("name_of_system", {}).get("value", "")

    parsed_items = []
    shipping = 0.0
    if line_items_str:
        parsed_items, shipping, err = bom.parse_line_items(line_items_str)
        if err:
            ack(response_action="errors", errors={"block_line_items": err})
            return

    # Check total
    if parsed_items:
        total_err = bom.check_total(parsed_items, shipping, total_price)
        if total_err:
            ack(response_action="errors", errors={"block_line_items": total_err})
            return

    if category == "Fabrication" and not asset_id:
        ack(response_action="errors", errors={"block_asset_id": "Required for Fabrication"})
        return
    if category == "Fabrication" and not name_of_system:
        ack(response_action="errors", errors={"block_name_of_system": "Required for Fabrication"})
        return

    ack()

    vendor = meta.get("vendor_choice", "Vendor")

    parsed = {
        "vendor": vendor,
        "payment_method": "EPIF",
        "item_description": item,
        "purpose": purpose,
        "link": link,
        "total_price": total_price,
        "date_of_purchase": date_str,
        "delivery_room": room,
        "project_id": project,
        "fund": fund,
        "category": category,
        "asset_id": asset_id,
        "name_of_system": name_of_system,
    }
    from . import epif_parser
    parsed["date_of_purchase"] = epif_parser.parse_date(date_str) if date_str else None

    # Apply changes to card's existing request
    updated_req = dict(req_data)
    updated_req["parsed"] = parsed
    updated_req["route"] = "epif"
    updated_req["source"] = "epif"
    if parsed_items:
        updated_req["items"] = parsed_items
        updated_req["shipping"] = shipping
    elif "items" in updated_req:
        del updated_req["items"]
    if "shipping" in updated_req and not parsed_items:
        del updated_req["shipping"]

    updated_columns = log_writer.request_to_row_values(
        requester=card_payload.get("requester", ""),
        parsed=parsed,
    )

    # We don't overwrite requester, date of request, or stage dates
    # log_writer.update_row only writes values that are given.
    # However, request_to_row_values provides them all, including Date of Request based on when it runs!
    # So we should be careful to only update the modified columns.

    # Let's extract exactly the columns that should change
    col_updates = {
        "B": vendor,
        "C": item,
        "D": purpose,
        config.COLUMN_HOW_BUYING: "EPIF",
        config.COLUMN_LINK: link,
        config.COLUMN_TOTAL_PRICE: total_price,
        config.COLUMN_CATEGORY: category,
        config.COLUMN_PROJECT_ID: project,
        config.COLUMN_FUND: fund,
        config.COLUMN_DELIVERY_ROOM: room,
        config.COLUMN_ASSET_ID: asset_id,
        config.COLUMN_NAME_OF_SYSTEM: name_of_system
    }

    user_name = slack_io.resolve_requester(client, user_id) or f"<@{user_id}>"
    assignee_id = req_data.get("assignee_id")

    def write_action():
        row_info = log_writer.get_row_info(row_num)
        if row_info.get("date_processed"):
            raise RuntimeError("Request has already been processed.")

        log_writer.update_row(row_num, col_updates)

        # Archive EPIF
        from . import epif_filler
        with open(config.EPIF_TEMPLATE_PATH, "rb") as template_file:
            template_bytes = template_file.read()

        filled_bytes = epif_filler.fill_epif(template_bytes, parsed)

        existing = os.listdir(config.EPIFS_DIR) if os.path.exists(config.EPIFS_DIR) else []
        archive_name = log_writer.epif_archive_name(
            vendor=vendor,
            total_price=total_price,
            project_id=project,
            existing=existing,
        )
        saved_epif_path = log_writer.save_epif(filled_bytes, archive_name)

        saved_bom_path = None
        bom_fname = None
        if parsed_items and bom.needs_bom(parsed_items):
            bom_fname = bom.bom_filename(row_num, vendor)
            workbook_bytes = bom.build_bom_workbook(
                vendor=vendor,
                row_num=row_num,
                items=parsed_items,
                shipping=shipping,
                total_price=total_price,
            )
            saved_bom_path = log_writer.save_bom(workbook_bytes, bom_fname)

            # Update notes column with BOM link
            log_writer.update_row(row_num, {config.COLUMN_NOTES: f"BOM: {bom_fname}"})

        return row_num, saved_epif_path, archive_name, bom_fname, saved_bom_path

    def on_success(res):
        row_num, saved_epif_path, archive_name, bom_fname, saved_bom_path = res

        updated_req["epif_file"] = archive_name
        if bom_fname:
            updated_req["bom_file"] = bom_fname

        # Update card
        new_blocks = blocks.build_request_blocks(
            state="approved",
            request=updated_req,
            history=card_payload.get("history", []),
            requester=card_payload.get("requester"),
            items=parsed_items,
        )
        client.chat_update(
            channel=channel,
            ts=card_ts,
            text="Purchase Request",
            blocks=new_blocks
        )

        # Thread reply
        slack_io.tell(client, user_id, f"🔁 Switched to EPIF by {user_name}.", thread_ts=thread_ts)

        # DM Assignee
        if assignee_id:
            try:
                lifecycle._send_assignee_dm(
                    client=client,
                    assignee_id=assignee_id,
                    req_data=updated_req,
                    channel=channel,
                    thread_ts=thread_ts,
                    epif_path=saved_epif_path,
                    epif_fname=archive_name,
                    bom_path=saved_bom_path,
                    bom_fname=bom_fname,
                    epif_path_route=True,
                )
            except Exception as e:
                log.error("Failed to send switch EPIF DM to assignee %s: %s", assignee_id, e)

    def on_failure(error):
        log.error("Failed to switch request to EPIF: %s", error)
        msg = str(error) if "already been processed" in str(error) else "Internal error during switch to EPIF."
        slack_io.tell(client, user_id, f"❌ Failed to switch to EPIF: {msg}", thread_ts=thread_ts)

    queue_worker.submit_write_task(
        action_fn=write_action,
        channel=channel,
        thread_ts=thread_ts,
        user_id=user_id,
        task_type="update",
        description=f"Switch to EPIF for row {row_num} by {user_name}",
        success_callback=on_success,
        failure_callback=on_failure,
        client=client,
    )
"""

search_str = """@app.view(config.STAGE3_CALLBACK_ID)
def handle_stage3_submit(ack, body, client, view):"""

content = content.replace(search_str, handler_code + "\n" + search_str)

with open('src/app.py', 'w') as f:
    f.write(content)
