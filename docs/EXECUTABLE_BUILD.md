# P-Bot (Purchasing Bot) - PyInstaller Executable Build Guide

This guide explains how to build P-Bot as a standalone `.exe` executable that can run on any Windows computer **without requiring Python to be installed**.

---

## Why Build an Executable?

| Aspect | Python Source | .exe Executable |
|--------|---------------|-----------------|
| **Requires Python** | ✅ Yes (3.10+) | ❌ No |
| **Installation** | `pip install -r requirements.txt` | Just copy .exe |
| **Size** | Smaller (~few MB) | Larger (~120-150 MB) |
| **Deployment** | Requires dev setup | Anyone can run it |
| **Updates** | Easy (edit .py files) | Rebuild .exe |

**Best for lab computer:** The .exe is ideal since you just copy it once and it runs on any machine.

---

## Prerequisites

### On Your Development Machine (where you build the .exe)

1. **Python 3.10 or higher**
   ```bash
   python --version
   ```

2. **Install PyInstaller**
   ```bash
   pip install pyinstaller
   ```

3. **Install all bot dependencies**
   ```bash
   pip install -r requirements.txt
   ```

---

## Building the Executable

### Step 1: Prepare Your Code
Make sure your bot code is ready:
- All edits/fixes are done
- `.env` file has your Slack tokens (optional, can be added later)
- Dependencies are all installed

### Step 2: Build with PyInstaller
From the project directory, run:
```bash
python build_exe.py
```

This will:
1. ✅ Verify PyInstaller is installed
2. 🔨 Compile the bot into a standalone executable
3. 📦 Create a deployment package with everything needed
4. 📋 Show you the output location

**Build output:**
```
✅ Build Complete!

📍 Executable location:
   C:\Users\IGLeg\PycharmProjects\Slackbot\dist\p_bot\p_bot.exe

📦 Deployment package:
   C:\Users\IGLeg\PycharmProjects\Slackbot\p_bot_deployment

🚀 Next Steps:
   1. Test locally
   2. Setup auto-start (optional)
   3. Deploy to lab computer
```

### Build Time
- First build: 2-3 minutes (longer, needs to compile everything)
- Subsequent builds: ~1 minute (incremental)

### Build Size
The `dist/p_bot/` folder will be ~120-150 MB (contains Python + all dependencies bundled in)

---

## Testing the Executable Locally

### Option 1: Run Directly
```bash
cd dist\p_bot
p_bot.exe
```

**What happens:**
- On first run, bot validates storage paths
- Bot prompts you to configure paths if missing
- Bot connects to Slack and starts listening
- No console window (runs in background)

### Option 2: Run with Console (for debugging)
Edit `p_bot.spec` and change:
```python
console=False,  # Change to True for console window
```
Then rebuild:
```bash
python build_exe.py
```

---

## Deploying to Lab Computer

### Quick Deployment (No Auto-Start)

**On the lab computer:**

1. Copy the `p_bot_deployment` folder to the lab computer (any location)
   ```
   Example: C:\P-Bot\
   ```

2. Create a `.env` file in that folder with your Slack tokens:
   ```
   SLACK_BOT_TOKEN=xoxb-...
   SLACK_APP_TOKEN=xapp-...
   ```

3. Double-click `p_bot\p_bot.exe` to run
   - First run: configure storage paths when prompted
   - Future runs: bot starts automatically

4. To stop: Open Task Manager → End Process `p_bot.exe`

### Full Deployment (With Auto-Start)

**On the lab computer:**

1. Copy `p_bot_deployment` folder (same as above)

2. Create `.env` file with Slack tokens

3. Open PowerShell in the deployment folder and run:
   ```bash
   python setup_autostart.py
   ```

   This creates:
   - Windows Task Scheduler task "P-Bot" (primary)
   - Startup folder shortcut (fallback)

4. Reboot computer to verify auto-start works

5. Bot will now:
   - 🟢 Start automatically on boot
   - 🔄 Restart if it crashes
   - 📝 Log errors to `p_bot.log`

---

## Deployment Folder Structure

After building, you'll have:

```
p_bot_deployment/
├── p_bot/
│   ├── p_bot.exe          ← The executable (run this!)
│   ├── _internal/             ← Dependencies (don't touch)
│   └── ...
├── setup_autostart.py         ← Auto-start setup script
├── SETUP.md                   ← Setup guide
├── DEPLOYMENT.md              ← Deployment instructions
├── .env                       ← Slack tokens (CREATE THIS)
└── .env.example               ← Example .env file
```

---

## Updating the Executable

When you make changes to the bot:

1. **Edit bot code** (app.py, etc.)
2. **Test locally** with Python
3. **Rebuild the .exe:**
   ```bash
   python build_exe.py
   ```
4. **Deploy new version:**
   - Copy new `p_bot_deployment` folder to lab computer
   - Copy `.env` file from old version to new version
   - Stop old bot (Task Manager)
   - Start new bot

---

## Advanced Options

### Reduce Executable Size
The .exe is currently ~120-150 MB. To reduce it, install UPX:
```bash
pip install pyinstaller[upx]
```

Then in `p_bot.spec`, the upx setting is already enabled:
```python
upx=True,
```

### Add a Console Window for Debugging
In `p_bot.spec`, change:
```python
console=False,  # Change to True
```

Then rebuild:
```bash
python build_exe.py
```

### Create a Shortcut on Desktop
On the lab computer, create a Windows shortcut to:
```
C:\P-Bot\p_bot\p_bot.exe
```

Then save it to the Desktop for easy access.

---

## Troubleshooting Build Issues

### "PyInstaller not found"
```bash
pip install pyinstaller
```

### "Module not found" errors
Some modules are hidden from PyInstaller. They're already included in `p_bot.spec`:
```python
hiddenimports=[
    'slack_bolt',
    'slack_bolt.adapter',
    'slack_bolt.adapter.socket_mode',
    'pypdf',
    'openpyxl',
    'openpyxl.styles',
    'openpyxl.utils',
    'requests',
],
```

If you add new imports, add them here before rebuilding.

### Build fails with dependency errors
Update all dependencies:
```bash
pip install --upgrade -r requirements.txt
```

### Executable crashes on startup
1. Edit `p_bot.spec` to enable console:
   ```python
   console=True,
   ```
2. Rebuild and run to see error messages
3. Fix the issue and rebuild with `console=False`

---

## File Sizes Reference

- **p_bot.exe:** ~8 MB (the executable)
- **p_bot/_internal/:** ~110-140 MB (Python + dependencies)
- **Total deployment:** ~150 MB

This is normal for PyInstaller bundles - they're self-contained with all dependencies included.

---

## Verifying Deployment

After deploying to the lab computer, verify everything works:

```bash
python verify_setup.py
```

This checks:
- ✅ Slack tokens configured
- ✅ Storage paths accessible
- ✅ Dependencies available
- ✅ Auto-start task registered (if installed)

---

## Complete Deployment Checklist

### Before Building
- [ ] All bot code is finalized and tested
- [ ] Slack tokens are correct
- [ ] Python 3.10+ installed
- [ ] PyInstaller installed (`pip install pyinstaller`)

### Building
- [ ] Run `python build_exe.py`
- [ ] Verify `dist/p_bot/p_bot.exe` exists
- [ ] Verify `p_bot_deployment/` folder created
- [ ] Test locally: double-click the .exe

### Deploying to Lab Computer
- [ ] Copy `p_bot_deployment/` folder
- [ ] Create `.env` with Slack tokens
- [ ] Run `p_bot.exe` and verify paths
- [ ] (Optional) Run `setup_autostart.py`
- [ ] (Optional) Reboot to test auto-start
- [ ] Run `verify_setup.py` to confirm

---

## Support & Further Help

- **Slack token issues?** → See [Slack App Setup](https://api.slack.com/apps)
- **Storage paths?** → See SETUP.md
- **Auto-start not working?** → Open Task Scheduler and check "P-Bot" task
- **Build errors?** → Check Python version (needs 3.10+)

For detailed deployment guide, see `DEPLOYMENT.md` (created in the deployment package).
