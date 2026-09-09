# P-Bot (Hirst Lab Purchasing Bot) 

An automated Slack purchasing bot and Excel integration system for the Hirst Lab.
- It listens for EPIF (Equipment & Purchasing Information Form) purchase requests
- validates form data against lab rules
- safely updates `Purchasing-Log.xlsx`
- archives PDFs and confirmation documents
- guides lab members through order processing.

---

## Slack Bot Commands

- `@p-bot approved` — Charlie/Admin approves an EPIF PDF in a thread. The bot parses, validates, logs it to `Purchasing-Log.xlsx`, saves the PDF to `EPIFs/`, and generates email templates or claims.
- `@p-bot claim` — (Grad Students) Claim an approved undergrad purchase to submit via Workday/ShopUW.
- `@p-bot submitted [$price]` — Marks an order as submitted in Workday (`Date Processed`, Col U) and updates total price if adjusted.
- `@p-bot confirmed` — Marks an order as confirmed (`Date Confirmed`, Col V) and saves attached confirmation files to `Order-Confirmations/`.
- `@p-bot delivered` — Marks an order as delivered (`Date of Delivery`, Col W & `Received By`, Col X).
- `@p-bot quote` — Saves an attached quote PDF/file directly to `Purchasing/Quotes/`.
- `@p-bot health` / `@p-bot status` — Displays host uptime, disk space, storage connectivity, and Excel lock status.
- `@p-bot queue` — Displays pending write tasks in the automatic Excel lock retry queue.
- `@p-bot logs [n]` — _(Admin Only)_ Displays the last `n` lines of application logs directly in Slack.
- `@p-bot update` — _(Admin Only)_ Pulls latest git updates, updates dependencies, and restarts the bot.
- `@p-bot restart` — _(Admin Only)_ Gracefully restarts the bot process.
- `@p-bot help` — Displays the command reference.

