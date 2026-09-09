"""Admin, Diagnostic, and Lifecycle Management Suite for P-Bot.

Provides:
- In-Slack System Health & Diagnostics (@p-bot health / status)
- Excel Lock Queue Status (@p-bot queue)
- Remote Log Viewer (@p-bot logs [n])
- Remote Git Update (@p-bot update)
- Remote Bot Restart (@p-bot restart)
"""
from datetime import datetime
import logging
import os
import platform
import re
import shutil
import subprocess
import sys
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

try:
    from . import config
    from . import queue_worker
except ImportError:
    import config
    import queue_worker

log = logging.getLogger("p-bot.admin")

# Process startup timestamp for uptime calculation
START_TIME = datetime.now()


def is_admin_user(user_id: Optional[str]) -> bool:
    """Check if the given Slack user ID is authorized as an administrator."""
    if not user_id:
        return False
    return user_id in config.ADMIN_SLACK_USER_IDS


def format_uptime(start: datetime) -> str:
    """Calculate and format human-readable uptime string."""
    delta = datetime.now() - start
    days = delta.days
    hours, remainder = divmod(delta.seconds, 3600)
    minutes, seconds = divmod(remainder, 60)

    parts = []
    if days > 0:
        parts.append(f"{days} day{'s' if days != 1 else ''}")
    if hours > 0:
        parts.append(f"{hours} hour{'s' if hours != 1 else ''}")
    parts.append(f"{minutes} minute{'s' if minutes != 1 else ''}")
    return ", ".join(parts)


def get_process_memory_mb() -> float:
    """Get current process memory usage in Megabytes."""
    try:
        import psutil
        process = psutil.Process(os.getpid())
        return process.memory_info().rss / (1024 * 1024)
    except Exception:
        pass

    # Windows ctypes fallback for GetProcessMemoryInfo
    if sys.platform == "win32":
        try:
            import ctypes
            from ctypes import wintypes

            class PROCESS_MEMORY_COUNTERS(ctypes.Structure):
                _fields_ = [
                    ("cb", wintypes.DWORD),
                    ("PageFaultCount", wintypes.DWORD),
                    ("PeakWorkingSetSize", ctypes.c_size_t),
                    ("WorkingSetSize", ctypes.c_size_t),
                    ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                    ("PagefileUsage", ctypes.c_size_t),
                    ("PeakPagefileUsage", ctypes.c_size_t),
                ]

            counters = PROCESS_MEMORY_COUNTERS()
            counters.cb = ctypes.sizeof(PROCESS_MEMORY_COUNTERS)
            handle = ctypes.windll.kernel32.GetCurrentProcess()
            if ctypes.windll.psapi.GetProcessMemoryInfo(handle, ctypes.byref(counters), counters.cb):
                return counters.WorkingSetSize / (1024 * 1024)
        except Exception:
            pass

    return 0.0


def check_path_health(path: str, is_file: bool = False) -> Dict[str, Any]:
    """Check existence, writability, and lock status for a file or directory."""
    result = {
        "path": path,
        "exists": False,
        "writable": False,
        "locked": False,
        "error": None,
    }
    if not path:
        result["error"] = "Path not set"
        return result

    try:
        if is_file:
            result["exists"] = os.path.isfile(path)
            if result["exists"]:
                lock_file = os.path.join(os.path.dirname(path), "~$" + os.path.basename(path))
                result["locked"] = os.path.exists(lock_file)
                # Check writable
                result["writable"] = os.access(path, os.W_OK) and not result["locked"]
            else:
                parent = os.path.dirname(path)
                result["writable"] = os.path.isdir(parent) and os.access(parent, os.W_OK)
        else:
            result["exists"] = os.path.isdir(path)
            if result["exists"]:
                result["writable"] = os.access(path, os.W_OK)
            else:
                parent = os.path.dirname(path)
                result["writable"] = os.path.isdir(parent) and os.access(parent, os.W_OK)
    except Exception as e:
        result["error"] = str(e)

    return result


def get_system_health() -> Dict[str, Any]:
    """Gather comprehensive diagnostics across host, storage, memory, and write queue."""
    # Host & Uptime
    host = platform.node() or "Unknown Host"
    os_desc = f"{platform.system()} {platform.release()}"
    uptime_str = format_uptime(START_TIME)

    # Disk Space
    drive_root = os.path.splitdrive(os.path.abspath(config.BASE_DIR))[0] + "\\"
    if not os.path.exists(drive_root):
        drive_root = config.BASE_DIR
    try:
        total, used, free = shutil.disk_usage(drive_root)
        total_gb = total / (1024 ** 3)
        free_gb = free / (1024 ** 3)
        free_pct = (free / total * 100) if total > 0 else 0
        disk_str = f"{drive_root} - {free_gb:.1f} GB free ({free_pct:.0f}% of {total_gb:.1f} GB)"
    except Exception as e:
        disk_str = f"Unavailable ({e})"

    # Memory
    mem_mb = get_process_memory_mb()
    mem_str = f"{mem_mb:.1f} MB" if mem_mb > 0 else "N/A"

    # Storage & OneDrive Paths
    wb_health = check_path_health(config.WORKBOOK_PATH, is_file=True)
    epifs_health = check_path_health(config.EPIFS_DIR, is_file=False)
    conf_health = check_path_health(config.CONFIRMATIONS_DIR, is_file=False)
    quotes_health = check_path_health(config.QUOTES_DIR, is_file=False)

    # Queue Status
    q_status = queue_worker.get_queue_status()

    return {
        "host": host,
        "os": os_desc,
        "uptime": uptime_str,
        "disk": disk_str,
        "memory": mem_str,
        "workbook": wb_health,
        "epifs": epifs_health,
        "confirmations": conf_health,
        "quotes": quotes_health,
        "queue": q_status,
        "bot_version": config.BOT_VERSION,
    }


def build_health_blocks(health: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    """Generate Slack Block Kit payload for health & diagnostic reports."""
    h = health or get_system_health()

    def format_status(check: Dict[str, Any], is_file: bool = False) -> str:
        if check.get("locked"):
            return "⏳ Locked in Excel (`~$` active)"
        if not check.get("exists"):
            return "❌ Missing"
        if not check.get("writable"):
            return "⚠️ Read-Only"
        return "✅ Ready & Writable"

    wb_status = format_status(h["workbook"], is_file=True)
    epifs_status = format_status(h["epifs"])
    conf_status = format_status(h["confirmations"])
    quotes_status = format_status(h["quotes"])

    pending = h["queue"]["pending_count"]
    queue_str = f"✅ `{pending} pending`" if pending == 0 else f"⏳ `{pending} write(s) queued`"
    if h["queue"].get("is_locked"):
        queue_str += " (Waiting for Excel lock release)"

    blocks = [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": "🩺 P-Bot System Health & Status",
                "emoji": True,
            },
        },
        {
            "type": "section",
            "fields": [
                {
                    "type": "mrkdwn",
                    "text": f"*Host Machine:*\n`{h['host']}` ({h['os']})",
                },
                {
                    "type": "mrkdwn",
                    "text": f"*Bot Uptime:*\n`{h['uptime']}` (v{h['bot_version']})",
                },
                {
                    "type": "mrkdwn",
                    "text": f"*Disk Space:*\n`{h['disk']}`",
                },
                {
                    "type": "mrkdwn",
                    "text": f"*Process Memory:*\n`{h['memory']}`",
                },
            ],
        },
        {
            "type": "divider",
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    "*📁 Storage & OneDrive Directory Health:*\n"
                    f"• `Purchasing-Log.xlsx`: {wb_status}\n"
                    f"• `EPIFs/`: {epifs_status}\n"
                    f"• `Order-Confirmations/`: {conf_status}\n"
                    f"• `Quotes/`: {quotes_status}"
                ),
            },
        },
        {
            "type": "section",
            "fields": [
                {
                    "type": "mrkdwn",
                    "text": f"*Excel Write Queue:*\n{queue_str}",
                },
            ],
        },
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": f"Diagnostics gathered at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} • Hirst Lab",
                },
            ],
        },
    ]
    return blocks


def get_tail_logs(n: int = 30, log_path: Optional[str] = None) -> str:
    """Read the last n lines from p_bot.log with sensitive tokens masked."""
    target_path = log_path or config.LOG_FILE
    n = max(1, min(100, n))

    if not os.path.exists(target_path):
        return f"Log file not found at `{target_path}`."

    try:
        with open(target_path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
            tail_lines = lines[-n:] if len(lines) >= n else lines
            raw_text = "".join(tail_lines)
    except Exception as e:
        return f"Error reading log file: {e}"

    # Mask sensitive tokens (Slack tokens, webhook URLs, etc.)
    masked_text = re.sub(r"xoxb-[a-zA-Z0-9-]+", "xoxb-***MASKED***", raw_text)
    masked_text = re.sub(r"xapp-[a-zA-Z0-9-]+", "xapp-***MASKED***", masked_text)
    masked_text = re.sub(r"https://hooks\.slack\.com/services/[^\s]+", "https://hooks.slack.com/services/***MASKED***", masked_text)

    return masked_text


def execute_git_update() -> Tuple[bool, str]:
    """Pull latest changes from git repository and optionally update dependencies."""
    try:
        git_res = subprocess.run(
            ["git", "pull", "origin", "main"],
            cwd=config.BASE_DIR,
            capture_output=True,
            text=True,
            timeout=45,
        )
        output = (git_res.stdout + "\n" + git_res.stderr).strip()

        if git_res.returncode != 0:
            # Try generic git pull fallback
            git_fallback = subprocess.run(
                ["git", "pull"],
                cwd=config.BASE_DIR,
                capture_output=True,
                text=True,
                timeout=45,
            )
            output = (git_fallback.stdout + "\n" + git_fallback.stderr).strip()
            if git_fallback.returncode != 0:
                return False, f"Git pull failed with return code {git_fallback.returncode}:\n```\n{output}\n```"

        pip_output = ""
        if "requirements.txt" in output:
            log.info("requirements.txt changed during git pull; running pip install...")
            pip_res = subprocess.run(
                [sys.executable, "-m", "pip", "install", "-r", "requirements.txt"],
                cwd=config.BASE_DIR,
                capture_output=True,
                text=True,
                timeout=120,
            )
            pip_output = f"\n\n*Dependencies updated:*\n```{pip_res.stdout[-500:]}```"

        return True, f"✅ *Git update successful!*\n```\n{output}\n```{pip_output}"
    except Exception as e:
        return False, f"Exception during git update: {e}"


def execute_restart(delay: float = 1.0) -> None:
    """Cleanly spawn a new instance of the bot process and terminate the current process."""
    log.info("Executing remote restart in %s seconds...", delay)

    def _do_restart():
        time.sleep(delay)
        # Flush standard log handlers
        for handler in logging.root.handlers:
            try:
                handler.flush()
            except Exception:
                pass

        # Determine entry point
        entrypoint = "app.py"
        entry_path = os.path.join(config.BASE_DIR, entrypoint)
        if not os.path.isfile(entry_path):
            entry_path = sys.argv[0]

        if sys.platform == "win32":
            # On Windows, spawn detached process group so it survives parent exit
            creationflags = subprocess.CREATE_NEW_PROCESS_GROUP
            subprocess.Popen(
                [sys.executable, entry_path],
                cwd=config.BASE_DIR,
                creationflags=creationflags,
            )
        else:
            subprocess.Popen([sys.executable, entry_path], cwd=config.BASE_DIR)

        # Exit current process cleanly
        os._exit(0)

    t = threading.Thread(target=_do_restart, daemon=True)
    t.start()
