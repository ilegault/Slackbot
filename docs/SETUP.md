# P-Bot (Purchasing Bot) - Setup & Deployment Guide

## Quick Start

### 1. Install Dependencies
```bash
pip install -r requirements.txt
```

### 2. Set Environment Variables
Create a `.env` file in the project root with your Slack tokens:
```
SLACK_BOT_TOKEN=xoxb-your-bot-token
SLACK_APP_TOKEN=xapp-your-app-token
```

Optionally, override storage paths (the bot will prompt you if they're not found):
```
PURCHASING_LOG_PATH=C:\Users\USERNAME\OneDrive\Purchasing\Purchasing-Log.xlsx
EPIFS_DIR=C:\Users\USERNAME\OneDrive\Purchasing\EPIFs
CONFIRMATIONS_DIR=C:\Users\USERNAME\OneDrive\Purchasing\Order-Confirmations
```

### 3. First Run - Path Validation
When you run the bot for the first time (or deploy to a new machine), it will validate storage paths:

```bash
python app.py
```

**The bot will:**
- ✅ Check if all required storage paths exist
- 🔍 Auto-search for Purchasing-Log.xlsx on your OneDrive
- 📋 Prompt you to manually enter paths if they're not found
- 💾 Save your configuration to `.env` for future runs

**Example interaction:**
```
======================================================================
🔍 Validating storage paths...
======================================================================

❌ Purchasing-Log.xlsx not found at:
   C:\Users\IGLeg\OneDrive - UW-Madison\Shortcuts\...

======================================================================
⚠️  Some paths are missing. Attempting to auto-locate...
======================================================================

✅ Found Purchasing-Log.xlsx at:
   C:\Users\NEWUSER\OneDrive\Purchasing\Purchasing-Log.xlsx

Enter the path to EPIFs directory (where PDFs are saved)
(or press Enter to skip): C:\Users\NEWUSER\OneDrive\Purchasing\EPIFs

Enter the path to Order-Confirmations directory
(or press Enter to skip): C:\Users\NEWUSER\OneDrive\Purchasing\Order-Confirmations

💾 Saving configuration to .env...
✅ Configuration saved to .env

🤖 Starting P-Bot in Socket Mode...
```

---

## Auto-Start on Boot

To run the bot automatically when the lab computer starts:

### Setup Auto-Start
```bash
python setup_autostart.py
```

This will:
1. Create a `run_bot.bat` batch file launcher
2. Create a Windows Task Scheduler entry to run it at startup
3. Create a backup startup folder shortcut

### What Gets Created
- **run_bot.bat** — Batch file that launches the bot
- **Windows Task Scheduler Task** — "P-Bot" task runs at system startup
- **Startup Shortcut** — Fallback launcher in Windows Startup folder

### Verify Setup
Check that the task was created:
```powershell
Get-ScheduledTask -TaskName "P-Bot" | Select-Object *
```

### Disable Auto-Start (if needed)
```powershell
Unregister-ScheduledTask -TaskName "P-Bot" -Confirm:$false
```

---

## Deploying to a Different Computer

### On the New Lab Computer:

1. **Clone or copy the bot** to the new machine
2. **Set up Python environment** (Python 3.10+)
3. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```
4. **First run** (with path configuration):
   ```bash
   python app.py
   ```
   The bot will guide you through configuring storage paths for the new machine.

5. **Set up auto-start** (optional):
   ```bash
   python setup_autostart.py
   ```

6. **Reboot** to verify auto-start works

---

## Storage Path Configuration

The bot needs access to three OneDrive-synced locations:

| Path | Purpose | Example |
|------|---------|---------|
| **PURCHASING_LOG_PATH** | Excel workbook (Purchasing-Log.xlsx) | `C:\...\OneDrive\Purchasing\Purchasing-Log.xlsx` |
| **EPIFS_DIR** | Where bot saves approved EPIF PDFs | `C:\...\OneDrive\Purchasing\EPIFs` |
| **CONFIRMATIONS_DIR** | Where bot saves confirmation files | `C:\...\OneDrive\Purchasing\Order-Confirmations` |

### How to Find Your Paths

**Purchasing-Log.xlsx:**
- Open OneDrive from File Explorer
- Navigate to: Purchasing → Purchasing-Log.xlsx
- Right-click → Copy full path

**EPIFs directory:**
- Open OneDrive from File Explorer
- Navigate to: Purchasing → EPIFs
- Right-click on folder → Copy full path

**Order-Confirmations directory:**
- Open OneDrive from File Explorer
- Navigate to: Purchasing → Order-Confirmations
- Right-click on folder → Copy full path

---

## Troubleshooting

### Bot won't start after deployment
1. Check that `SLACK_BOT_TOKEN` and `SLACK_APP_TOKEN` environment variables are set
2. Run `python app.py` manually to see error messages
3. Verify that storage paths are accessible (the bot will guide you)

### "Cannot find Purchasing-Log.xlsx"
- Make sure OneDrive is synced on the computer
- Check that the file exists in your OneDrive
- Provide the full path when prompted by the bot

### Task Scheduler task not running
1. Open Task Scheduler (press `Win+R`, type `taskschd.msc`)
2. Find "P-Bot" task in the list
3. Right-click → Properties
4. Verify the "Program/script" path is correct
5. Check under "History" tab for error logs

### Bot runs but doesn't respond to Slack messages
1. Verify bot is invited to the #hirst-lab channel
2. Check that bot has `files:read` scope in API settings
3. Ensure bot tokens are correct in `.env`
4. Check bot logs for connection errors

---

## System Requirements

- **RAM:** 150-300 MB idle, up to 500 MB during PDF processing
- **Disk:** ~200-500 MB (bot + dependencies + cached PDFs)
- **Network:** Minimal (5-20 KB/min idle, brief bursts during operations)
- **CPU:** <1% idle, 5-15% during processing

**Impact on lab computer:** Negligible — similar to a single web browser tab.

---

## Files Overview

- **app.py** — Main Slack bot logic
- **config.py** — Lab-specific constants (field mappings, valid values)
- **log_writer.py** — Safely writes to Excel workbook
- **path_validator.py** — Validates & configures storage paths at startup
- **setup_autostart.py** — Creates Windows Task Scheduler auto-start entry
- **run_bot.bat** — Batch launcher (created during setup)
- **.env** — Environment variables (Slack tokens + storage paths)
