# P-Bot: Python Source Deployment & Self-Update Guide 🚀

This guide explains how to set up, run, and maintain **P-Bot (Hirst Lab Purchasing Bot)** directly from Python source. Running from source enables seamless in-Slack remote updates (`@p-bot update`) and process restarts (`@p-bot restart`).

---

## 1. Why Run from Python Source vs. Compiled `.exe`?

| Feature | Python Source (`python app.py`) | Compiled Executable (`p_bot.exe`) |
| :--- | :--- | :--- |
| **In-Slack Self-Updates (`@p-bot update`)** | ✅ **Yes** (Pulls git repo, runs `pip`, restarts immediately) | ❌ **No** (Requires manual PyInstaller recompile) |
| **Remote Restart (`@p-bot restart`)** | ✅ **Yes** | ✅ **Yes** |
| **Setup Simplicity** | Quick (`git clone` & `pip install`) | Requires packaging step |
| **Prerequisites** | Python 3.10+ & Git installed | Standalone (no Python required) |

---

## 2. Prerequisites on the Host / Lab Computer

1. **Python 3.10+**:
   - Download and install Python from [python.org](https://www.python.org/).
   - ⚠️ **Important:** Ensure you check **"Add Python to PATH"** during the Windows installation.

2. **Git for Windows**:
   - Download and install Git from [git-scm.com](https://git-scm.com/).
   - Enables `@p-bot update` to pull latest changes directly from GitHub/GitLab.

---

## 3. Initial Project Setup

### Step 3.1: Clone or Copy the Repository
Place the project in your desired directory (e.g. `C:\Hirst-Lab\Slackbot` or `C:\Users\<User>\PycharmProjects\Slackbot`):
```powershell
git clone https://github.com/your-lab/Slackbot.git
cd Slackbot
```

### Step 3.2: Install Python Dependencies
Open PowerShell or Command Prompt inside the `Slackbot` folder:
```powershell
pip install -r requirements.txt
```

### Step 3.3: Configure Environment Variables (`.env`)
Create a `.env` file in the root `Slackbot/` directory (you can copy `.env.example` as a template):
```env
# --- Slack Authentication ---
SLACK_BOT_TOKEN=xoxb-your-bot-token
SLACK_APP_TOKEN=xapp-your-app-token

# --- OneDrive & File System Paths ---
PURCHASING_LOG_PATH=C:\Users\<User>\OneDrive - UW-Madison\Shortcuts\Charles Hirst's files - Hirst-Lab\Purchasing\Purchasing-Log.xlsx
EPIFS_DIR=C:\Users\<User>\OneDrive - UW-Madison\Shortcuts\Charles Hirst's files - Hirst-Lab\Purchasing\EPIFs
CONFIRMATIONS_DIR=C:\Users\<User>\OneDrive - UW-Madison\Shortcuts\Charles Hirst's files - Hirst-Lab\Purchasing\Order-Confirmations
QUOTES_DIR=C:\Users\<User>\OneDrive - UW-Madison\Shortcuts\Charles Hirst's files - Hirst-Lab\Purchasing\Quotes

# --- Admin & Notification Settings ---
# Comma-separated list of Slack User IDs allowed to run admin commands (e.g. @p-bot update, @p-bot restart, @p-bot logs)
ADMIN_SLACK_USER_IDS=U0123456789

# Channel ID or Admin User ID where startup, crash, and system health alerts should be sent
ADMIN_ALERT_CHANNEL=C0123456789

# --- External Heartbeat (Optional Dead-Man's Switch) ---
# Healthchecks.io / BetterStack ping URL for remote uptime monitoring
HEALTHCHECK_URL=https://hc-ping.com/your-uuid-here
HEALTHCHECK_INTERVAL_SECONDS=300

# --- Lock Queue Settings ---
EXCEL_QUEUE_POLL_INTERVAL=5
EXCEL_LOCK_ALERT_TIMEOUT_SECONDS=600
```

### Step 3.4: Verify the Configuration
Run the setup verification script:
```powershell
python verify_setup.py
```
This tests your Slack tokens, folder connectivity, dependencies, and configuration.

---

## 4. Running the Bot

### Option A: Run Interactively in Terminal
To start the bot in the current console window:
```powershell
python app.py
```
Output will log to both the terminal and `p_bot.log`.

### Option B: Automatic Startup on Windows Boot (Task Scheduler)
To ensure P-Bot starts automatically in the background whenever the computer boots:
```powershell
python setup_autostart.py
```
This registers a Windows Task Scheduler task named **`P-Bot`** that:
- Runs automatically when Windows starts up.
- Restarts cleanly when restarted via Slack.

---

## 5. Remote In-Slack Management

Once running, administrators (defined in `ADMIN_SLACK_USER_IDS`) can manage the bot directly from Slack:

### 1. Remote Git Self-Update
```
@p-bot update
```
- Detects the current branch and performs a `git pull origin <branch>`.
- If `requirements.txt` was modified, automatically runs `pip install -r requirements.txt`.
- Automatically reboots the bot process with the latest code applied.

### 2. Remote Bot Restart
```
@p-bot restart
```
- Checks that the Excel write queue is idle, flushes logs, and cleanly respawns the bot process.

### 3. Remote Log Viewer
```
@p-bot logs 50
```
- Displays the last 50 lines of `p_bot.log` inside Slack with sensitive tokens masked.

### 4. Health & Lock Queue Diagnostics (Accessible to all lab members)
```
@p-bot health
@p-bot queue
```
- Displays bot uptime, host computer stats, free disk space, Excel lock status, and pending write queue tasks.

---

## 6. Managing & Troubleshooting

### Check Task Scheduler Status (PowerShell)
```powershell
Get-ScheduledTask -TaskName "P-Bot"
```

### Stop Running Bot Manually
```powershell
Stop-Process -Name python -Force
```

### Remove Windows Autostart Task
```powershell
Unregister-ScheduledTask -TaskName "P-Bot" -Confirm:$false
```

### View Application Logs
Log files are saved in the project root:
- `p_bot.log`: General application logs and operation history.
- `rejections.log`: Form validation errors and rejected EPIF submissions.
