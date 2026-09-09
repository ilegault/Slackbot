#!/usr/bin/env python3
"""
Setup auto-start on boot for P-Bot (Purchasing Bot).

This script creates a Windows Task Scheduler entry that runs the bot at startup.
"""
import os
import sys
import subprocess
import logging

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
log = logging.getLogger(__name__)

TASK_NAME = "P-Bot"
# Resolve project root directory
BOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PYTHON_EXE = sys.executable


def create_batch_launcher():
    """Create a batch file that launches the bot with proper environment."""
    batch_path = os.path.join(BOT_DIR, "run_bot.bat")

    batch_content = f"""@echo off
REM P-Bot Launcher
REM This batch file runs the bot with proper environment setup

cd /d "{BOT_DIR}"
python app.py
pause
"""

    with open(batch_path, "w") as f:
        f.write(batch_content)

    log.info(f"✅ Created launcher batch file: {batch_path}")
    return batch_path


def find_exe_launcher():
    """Find the compiled .exe file if it exists (PyInstaller build)."""
    # Check for compiled .exe in dist folder
    exe_paths = [
        os.path.join(BOT_DIR, "dist", "p_bot", "p_bot.exe"),
        os.path.join(BOT_DIR, "p_bot", "p_bot.exe"),
        os.path.join(BOT_DIR, "dist", "epif_bot", "epif_bot.exe"),
        os.path.join(BOT_DIR, "epif_bot", "epif_bot.exe"),
    ]

    for exe_path in exe_paths:
        if os.path.isfile(exe_path):
            log.info(f"✅ Found compiled executable: {exe_path}")
            return exe_path

    return None


def create_scheduled_task(launcher_path: str, is_exe: bool = False) -> bool:
    """Create a Windows Task Scheduler task to run at startup.

    Args:
        launcher_path: Path to executable or batch file
        is_exe: True if this is an .exe file (use directly), False if batch file
    """
    log.info("📋 Creating Windows Task Scheduler entry...")

    # PowerShell script to create the task
    ps_script = f"""
$taskName = "{TASK_NAME}"
$taskPath = "\\{TASK_NAME}"
$action = New-ScheduledTaskAction -Execute '"{launcher_path}"'
$trigger = New-ScheduledTaskTrigger -AtStartup
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERNAME" -LogonType Interactive
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable

# Remove existing task if it exists (check both P-Bot and legacy EPIF-Bot)
try {{
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue
    Unregister-ScheduledTask -TaskName "EPIF-Bot" -Confirm:$false -ErrorAction SilentlyContinue
}} catch {{
    # Task doesn't exist, that's fine
}}

# Create new task
Register-ScheduledTask `
    -TaskName $taskName `
    -Action $action `
    -Trigger $trigger `
    -Principal $principal `
    -Settings $settings `
    -Description "Auto-start P-Bot (Purchasing Bot) at system startup"

Write-Host "✅ Task '$taskName' created successfully!"
"""

    try:
        # Run PowerShell script with admin privileges
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps_script],
            capture_output=True,
            text=True,
            check=False,
        )

        if result.returncode == 0:
            launcher_type = "executable" if is_exe else "batch file"
            log.info(f"✅ Windows Task Scheduler task created ({launcher_type})")
            return True
        else:
            log.warning("⚠️  Task creation may have failed. PowerShell output:")
            print(result.stdout)
            if result.stderr:
                print("Errors:", result.stderr)
            return False

    except Exception as e:
        log.error(f"❌ Failed to create scheduled task: {e}")
        return False


def create_startup_shortcut() -> bool:
    """Create a shortcut in Windows Startup folder (alternative method)."""
    try:
        startup_dir = os.path.expandvars(r"%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup")
        if not os.path.isdir(startup_dir):
            log.warning(f"Startup directory not found: {startup_dir}")
            return False

        batch_path = os.path.join(BOT_DIR, "run_bot.bat")
        shortcut_path = os.path.join(startup_dir, "P-Bot.lnk")

        # Clean up old shortcut if present
        old_shortcut = os.path.join(startup_dir, "EPIF-Bot.lnk")
        if os.path.exists(old_shortcut):
            try:
                os.remove(old_shortcut)
            except Exception:
                pass

        # Use PowerShell to create the shortcut
        ps_script = f"""
$WshShell = New-Object -ComObject WScript.Shell
$Shortcut = $WshShell.CreateShortcut("{shortcut_path}")
$Shortcut.TargetPath = "{batch_path}"
$Shortcut.WorkingDirectory = "{BOT_DIR}"
$Shortcut.Description = "P-Bot (Purchasing Bot)"
$Shortcut.Save()
Write-Host "Shortcut created: {shortcut_path}"
"""

        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps_script],
            capture_output=True,
            text=True,
            check=False,
        )

        if result.returncode == 0:
            log.info(f"✅ Created startup shortcut at: {shortcut_path}")
            return True
        else:
            log.warning("⚠️  Could not create startup shortcut")
            return False

    except Exception as e:
        log.error(f"❌ Failed to create startup shortcut: {e}")
        return False


def main():
    """Main setup routine."""
    print("\n" + "="*70)
    print("🤖 P-Bot - Auto-start Setup")
    print("="*70)

    # Check for compiled .exe first
    exe_path = find_exe_launcher()
    launcher_path = None
    is_exe = False

    if exe_path:
        launcher_path = exe_path
        is_exe = True
        log.info(f"Using compiled executable for auto-start")
    else:
        # Fall back to batch file
        try:
            launcher_path = create_batch_launcher()
            is_exe = False
        except Exception as e:
            log.error(f"❌ Failed to create batch launcher: {e}")
            sys.exit(1)

    # Try to create scheduled task (preferred method - runs without window)
    log.info("\n📋 Attempting to create scheduled task...")
    task_created = create_scheduled_task(launcher_path, is_exe=is_exe)

    # Also create startup shortcut as fallback
    log.info("\n📁 Creating startup folder shortcut (backup method)...")
    shortcut_created = create_startup_shortcut()

    print("\n" + "="*70)
    if task_created or shortcut_created:
        print("✅ Auto-start setup complete!")
        launcher_type = "executable" if is_exe else "batch file"
        if task_created:
            print(f"   → Bot will start automatically via Task Scheduler ({launcher_type})")
        if shortcut_created:
            print(f"   → Bot will also start via Startup folder")
    else:
        print("⚠️  Auto-start setup had issues. You may need to run manually.")
        print("   Or manually create a Windows Task Scheduler task:")
        print(f"   → Program: {launcher_path}")
        print(f"   → Trigger: At Startup")

    print("\n📋 To check the task status, run:")
    print(f'   Get-ScheduledTask -TaskName "{TASK_NAME}" | Select-Object *')
    print("\n💡 To remove auto-start, run:")
    print(f'   Unregister-ScheduledTask -TaskName "{TASK_NAME}" -Confirm:$false')
    print("="*70 + "\n")


if __name__ == "__main__":
    main()
