#!/usr/bin/env python3
"""
Verify that P-Bot is properly configured and ready to run.

This script checks:
  - Environment variables (Slack tokens)
  - Storage paths (Purchasing-Log.xlsx, EPIFs, Order-Confirmations)
  - Dependencies (pypdf, openpyxl, slack-bolt, etc.)
  - Auto-start configuration (if installed)
"""
import os
import sys
import subprocess

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# Ensure project root and src/ are in sys.path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC_DIR = os.path.join(PROJECT_ROOT, "src")
for p in (PROJECT_ROOT, SRC_DIR):
    if p not in sys.path:
        sys.path.insert(0, p)

try:
    from src import config, path_validator
except ImportError:
    import config
    import path_validator


def check_slack_tokens():
    """Verify Slack tokens are set."""
    print("\n📋 Checking Slack Tokens...")
    print("-" * 70)

    bot_token = os.environ.get("SLACK_BOT_TOKEN")
    app_token = os.environ.get("SLACK_APP_TOKEN")

    if bot_token and bot_token.startswith("xoxb-"):
        print("✅ SLACK_BOT_TOKEN is set")
    else:
        print("❌ SLACK_BOT_TOKEN is missing or invalid (should start with xoxb-)")
        return False

    if app_token and app_token.startswith("xapp-"):
        print("✅ SLACK_APP_TOKEN is set")
    else:
        print("❌ SLACK_APP_TOKEN is missing or invalid (should start with xapp-)")
        return False

    return True


def check_storage_paths():
    """Verify storage paths exist."""
    print("\n📁 Checking Storage Paths...")
    print("-" * 70)

    all_valid = True

    if path_validator.path_exists(config.WORKBOOK_PATH):
        print(f"✅ Purchasing-Log.xlsx:")
        print(f"   {config.WORKBOOK_PATH}")
    else:
        print(f"❌ Purchasing-Log.xlsx not found:")
        print(f"   {config.WORKBOOK_PATH}")
        all_valid = False

    if path_validator.path_exists(config.EPIFS_DIR):
        print(f"✅ EPIFs directory:")
        print(f"   {config.EPIFS_DIR}")
    else:
        print(f"❌ EPIFs directory not found:")
        print(f"   {config.EPIFS_DIR}")
        all_valid = False

    if path_validator.path_exists(config.CONFIRMATIONS_DIR):
        print(f"✅ Order-Confirmations directory:")
        print(f"   {config.CONFIRMATIONS_DIR}")
    else:
        print(f"❌ Order-Confirmations directory not found:")
        print(f"   {config.CONFIRMATIONS_DIR}")
        all_valid = False

    return all_valid


def check_dependencies():
    """Verify Python dependencies are installed."""
    print("\n📦 Checking Dependencies...")
    print("-" * 70)

    required = {
        "slack_bolt": "slack-bolt",
        "requests": "requests",
        "pypdf": "pypdf",
        "openpyxl": "openpyxl",
    }

    all_valid = True
    for module, package in required.items():
        try:
            __import__(module)
            print(f"✅ {package} is installed")
        except ImportError:
            print(f"❌ {package} is NOT installed")
            print(f"   Run: pip install {package}")
            all_valid = False

    return all_valid


def check_autostart():
    """Check if auto-start task is configured."""
    print("\n⏰ Checking Auto-Start Configuration...")
    print("-" * 70)

    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             'Get-ScheduledTask -TaskName "P-Bot", "EPIF-Bot" -ErrorAction SilentlyContinue'],
            capture_output=True,
            text=True,
            timeout=5,
        )

        if result.returncode == 0 and ("P-Bot" in result.stdout or "EPIF-Bot" in result.stdout):
            print("✅ Auto-start task 'P-Bot' is configured")
            print("   → Bot will start automatically on system boot")
            return True
        else:
            print("⚠️  Auto-start task 'P-Bot' is NOT configured")
            print("   → Run: python scripts/setup_autostart.py (or python setup_autostart.py)")
            return False

    except Exception as e:
        print(f"⚠️  Could not check auto-start status: {e}")
        return False


def check_monitoring_config():
    """Display admin, queue, and heartbeat configurations."""
    print("\n⚙️  Checking Monitoring & Admin Configuration...")
    print("-" * 70)
    if config.ADMIN_SLACK_USER_IDS:
        print(f"✅ Admin Users: {', '.join(config.ADMIN_SLACK_USER_IDS)}")
    else:
        print("⚠️  No ADMIN_SLACK_USER_IDS configured (Admin commands like logs/update/restart will be restricted)")

    if config.ADMIN_ALERT_CHANNEL:
        print(f"✅ Admin Alert Channel: {config.ADMIN_ALERT_CHANNEL}")
    else:
        print("ℹ️  ADMIN_ALERT_CHANNEL not set (startup and crash alerts disabled)")

    if config.HEALTHCHECK_URL:
        print(f"✅ External Heartbeat: {config.HEALTHCHECK_URL} (Interval: {config.HEALTHCHECK_INTERVAL_SECONDS}s)")
    else:
        print("ℹ️  HEALTHCHECK_URL not set (External dead-man's switch disabled)")

    print(f"✅ Excel Queue Poll Interval: {config.EXCEL_QUEUE_POLL_INTERVAL}s (Lock Alert Timeout: {config.EXCEL_LOCK_ALERT_TIMEOUT_SECONDS}s)")
    return True



def main():
    """Run all checks."""
    print("\n" + "=" * 70)
    print("🔍 P-Bot - Setup Verification")
    print("=" * 70)

    results = {
        "Slack Tokens": check_slack_tokens(),
        "Storage Paths": check_storage_paths(),
        "Dependencies": check_dependencies(),
        "Auto-Start": check_autostart(),
        "Monitoring Config": check_monitoring_config(),
    }

    print("\n" + "=" * 70)
    print("📊 Summary")
    print("=" * 70)

    all_passed = True
    for check, passed in results.items():
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"{status}: {check}")
        if not passed:
            all_passed = False

    print("=" * 70)

    if all_passed:
        print("\n✅ All checks passed! Bot is ready to run.")
        print("\n   To start the bot manually:")
        print("   $ python app.py")
        print("\n   To start the bot with auto-restart on reboot:")
        print("   $ python scripts/setup_autostart.py")
    else:
        print("\n❌ Some checks failed. Please fix the issues above.")
        print("\n   For help, see: docs/SETUP.md")

    print()
    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(main())
