# P-Bot (Hirst Lab Purchasing Bot) 🤖

An automated Slack purchasing bot and Excel integration system for the Hirst Lab. It listens for EPIF (Equipment & Purchasing Information Form) purchase requests, validates form data against lab rules, safely updates `Purchasing-Log.xlsx`, archives PDFs and confirmation documents, and guides lab members through order processing.

---

## 📁 Project Directory Layout

```
Slackbot/
├── docs/                     # Guides and setup documentation
│   ├── BUILD_GUIDE.md        # PyInstaller build and packaging guide
│   ├── EXECUTABLE_BUILD.md   # Deployment and executable instructions
│   ├── MONITORING_AND_QUEUE_SPEC.md # Lock queue & monitoring specification
│   ├── PYTHON_SOURCE_DEPLOYMENT.md  # Python source deployment & self-update guide
│   └── SETUP.md              # Complete setup and Slack configuration guide
│
├── samples/                  # Reference templates and testing fixtures
│   ├── EPIF_TEMPLATE_blank.pdf
│   ├── Prusa_EPIF__2799_PG000025831.pdf
│   └── Purchasing-Log.xlsx
│
├── scripts/                  # Administrative and utility scripts
│   ├── build_exe.py          # Builds standalone Windows .exe package
│   ├── setup_autostart.py    # Registers Windows Task Scheduler autostart
│   ├── test_cli.py           # CLI tool to test EPIF parsing & dry runs
│   └── verify_setup.py       # Validates tokens, dependencies, and paths
│
├── src/                      # Application source code
│   ├── app.py                # Slack Bolt event handlers & workflows
│   ├── config.py             # Lab configuration, mappings, & environment
│   ├── epif_parser.py        # AcroForm PDF parser
│   ├── log_writer.py         # Safe, atomic Excel XML updater & file saver
│   ├── path_validator.py     # OneDrive & local path validator
│   └── validators.py         # Business logic and form validation rules
│
├── tests/                    # Pytest automated test suite
│   └── test_pipeline.py      # Full pipeline tests (parsing, writing, Slack)
│
├── .env                      # Local environment variables (Slack tokens & paths)
├── app.py                    # Root entrypoint launcher
├── build_exe.py              # Root convenience forwarder -> scripts/build_exe.py
├── p_bot.spec                # PyInstaller packaging configuration
├── pytest.ini                # Pytest configuration
├── requirements.txt          # Python package dependencies
├── setup_autostart.py        # Root convenience forwarder -> scripts/setup_autostart.py
├── test_cli.py               # Root convenience forwarder -> scripts/test_cli.py
└── verify_setup.py           # Root convenience forwarder -> scripts/verify_setup.py
```

---

## 🚀 Quick Start

### 1. Environment Setup
Create a virtual environment and install dependencies:
```bash
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
```

Ensure your `.env` contains your Slack tokens and OneDrive paths:
```env
SLACK_BOT_TOKEN=xoxb-...
SLACK_APP_TOKEN=xapp-...
PURCHASING_LOG_PATH=C:\Users\USERNAME\OneDrive\Purchasing\Purchasing-Log.xlsx
EPIFS_DIR=C:\Users\USERNAME\OneDrive\Purchasing\EPIFs
CONFIRMATIONS_DIR=C:\Users\USERNAME\OneDrive\Purchasing\Order-Confirmations
QUOTES_DIR=C:\Users\USERNAME\OneDrive\Purchasing\Quotes
```

### 2. Verify Setup
Run the setup verification script:
```bash
python verify_setup.py
# or: python scripts/verify_setup.py
```

### 3. Run the Bot
Start the bot directly in Socket Mode:
```bash
python app.py
```

---

## 🧪 Testing

Run the test suite using pytest:
```bash
pytest
```

Test a sample EPIF PDF locally using the CLI tool (dry run):
```bash
python test_cli.py samples/Prusa_EPIF__2799_PG000025831.pdf
```

Test marking a row as confirmed or delivered:
```bash
python test_cli.py --confirm-row 17
python test_cli.py --deliver-row 17 --requester Isaac
```

---

## 🔨 Standalone Executable & Autostart

### Build Executable (`dist/p_bot/p_bot.exe`)
To package the bot into a standalone Windows executable:
```bash
python build_exe.py
# or: python scripts/build_exe.py
```

### Configure Windows Autostart on Boot
To register P-Bot with Windows Task Scheduler so it runs automatically in the background:
```bash
python setup_autostart.py
# or: python scripts/setup_autostart.py
```

---

## 💬 Slack Bot Commands

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

