# Purchasing bot (Hirst Lab)

An automated Slack purchasing bot and Excel integration system for the Hirst Lab.
- Listens for purchase requests via `/new-purchase` or EPIF PDF uploads in threads
- Validates form data against lab rules
- Safely updates `Purchasing-Log.xlsx` via a retry lock queue
- Archives PDFs, BOM spreadsheets, and confirmation documents
- Guides lab members through order processing across the four stages: approved, processed, confirmed, delivered.

---

## Slack Bot Commands

- `@Purchasing approved` — Charlie/Approver approves a request in a thread (optionally naming a buyer: `@Dylan @Purchasing approved`). The bot logs it to `Purchasing-Log.xlsx`, archives files, and posts or advances the request card.
- `@Purchasing assign [@buyer]` — Assign a buyer to handle an approved purchase (or assign yourself).
- `@Purchasing processed [$price]` — Mark an order as processed in Workday/ShopUW (`Date Processed`, Col U) and update total price if adjusted.
- `@Purchasing confirmed` — Mark an order as confirmed (`Date Confirmed`, Col V) and save attached confirmation files to `Order-Confirmations/`.
- `@Purchasing delivered` — Mark an order as delivered (`Date of Delivery`, Col W & `Received By`, Col X).
- `@Purchasing quote` — Save an attached quote PDF/file directly to `Quotes/`.
- `@Purchasing decline` — Approver declines a posted request before approval.
- `@Purchasing help` — Display the command reference.
- `@Purchasing health` / `@Purchasing status` — Display system health, host uptime, and storage location status.
- `@Purchasing queue` — Display pending write tasks in the automatic Excel lock retry queue.
- `@Purchasing logs [n|all|rejections]` — _(Admin Only, alert channel)_ View the last `n` lines of `p_bot.log` (default 30), full current `p_bot.log`, or `rejections.log`.
- `@Purchasing update` — _(Admin Only)_ Pull latest git updates, update dependencies, and restart the bot.
- `@Purchasing restart` — _(Admin Only)_ Gracefully restart the bot process.
- `@Purchasing promote-admin @user` — _(Admin Only)_ Propose promoting a user to bot administrator.
- `@Purchasing add-approver @user` — _(Admin Only)_ Add a user to the approvers list.
- `@Purchasing remove-approver @user` — _(Admin Only)_ Remove a user from the approvers list.
- `@Purchasing add-buyer @user` — _(Admin Only)_ Add a user to the buyers list.
- `@Purchasing remove-buyer @user` — _(Admin Only)_ Remove a user from the buyers list.
- `@Purchasing remove-member @user` — _(Admin Only)_ Remove a user from the lab roster and all roles.
- `@Purchasing add-vendor <name>` — _(Admin Only)_ Add a vendor to the Workday catalog list.
- `@Purchasing remove-vendor <name>` — _(Admin Only)_ Remove a vendor from the Workday catalog list.

Two-word commands work with a hyphen or a space: `remove-vendor` = `remove vendor`.

---

## Slash Commands

- `/new-purchase` — Open the guided purchasing modal to submit an order request.
- `/purchasing-help` — Display help and command reference.
- `/blank-template` — Download the blank EPIF PDF template and instructions.
- `/roster-list` — List registered lab members and Workday catalog vendors.
- `/roster-set-name` — Register in the lab roster, correct your name, or request a rename.

---

## Storage Settings

Configured via `.env` (no hardcoded defaults):
- `PURCHASING_LOG_PATH` — Path to the `Purchasing-Log.xlsx` workbook on OneDrive.
- `EPIFS_DIR` — Directory where approved and generated EPIF PDFs are archived.
- `CONFIRMATIONS_DIR` — Directory for vendor order confirmations.
- `QUOTES_DIR` — Directory for vendor quote documents.
- `BOMS_DIR` — Directory for Bill of Materials (BOM) Excel spreadsheets.
- `EPIF_TEMPLATE_PATH` — Path to the blank EPIF template PDF.
