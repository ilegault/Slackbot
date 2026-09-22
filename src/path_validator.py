"""Validate and configure storage paths and channels at startup.

WHY THIS EXISTS:
----------------
T15: PURCHASING_CHANNEL is a constant with a home in config.py. If unset,
the bot must fail loudly at startup rather than silently falling back to the
admin alert channel or DMing the requester. This module performs the operator-facing
validation check.

T24: The bot previously booted silently with template placeholders like
C:\\Users\\USERNAME\\... in .env until a real purchase failed with FileNotFoundError.
check_storage_paths performs a pure startup check for unset, placeholder,
wrong-kind, or non-existent paths so the startup alert can flag them in orange
before workbook writes or EPIF saves fail.

If storage paths don't exist, prompts the user to either:
  1. Locate them manually (search OneDrive)
  2. Use alternative paths on different drives
  3. Use default test directories
"""
import logging
import os
import re
from typing import NamedTuple

try:
    from . import config
except ImportError:
    import config

log = logging.getLogger("p-bot")


class PathProblem(NamedTuple):
    setting: str
    value: str
    reason: str


def check_storage_paths() -> list[PathProblem]:
    """Pure check of required storage paths.

    Inspects PURCHASING_LOG_PATH, EPIFS_DIR, CONFIRMATIONS_DIR, QUOTES_DIR,
    and BOMS_DIR in order. Returns a list of PathProblem instances, empty if all are valid.

    Reasons are checked in priority order:
      1. not set
      2. still contains a template placeholder
      3. exists but is not a file / exists but is not a folder
      4. does not exist
    """
    checks = [
        ("PURCHASING_LOG_PATH", getattr(config, "WORKBOOK_PATH", ""), "file"),
        ("EPIFS_DIR", getattr(config, "EPIFS_DIR", ""), "folder"),
        ("CONFIRMATIONS_DIR", getattr(config, "CONFIRMATIONS_DIR", ""), "folder"),
        ("QUOTES_DIR", getattr(config, "QUOTES_DIR", ""), "folder"),
        ("BOMS_DIR", getattr(config, "BOMS_DIR", ""), "folder"),
    ]

    problems: list[PathProblem] = []

    for setting, raw_val, kind in checks:
        val_str = "" if raw_val is None else str(raw_val)

        # 1. empty or unset
        if not val_str.strip():
            problems.append(PathProblem(setting, val_str, "not set"))
            continue

        # 2. template placeholder: component exactly USERNAME or contains < or >
        components = re.split(r"[\\/]+", val_str)
        if any(c == "USERNAME" or "<" in c or ">" in c for c in components):
            problems.append(PathProblem(setting, val_str, "still contains a template placeholder"))
            continue

        # 3. exists but wrong kind
        if os.path.exists(val_str):
            if kind == "file" and not os.path.isfile(val_str):
                problems.append(PathProblem(setting, val_str, "exists but is not a file"))
                continue
            if kind == "folder" and not os.path.isdir(val_str):
                problems.append(PathProblem(setting, val_str, "exists but is not a folder"))
                continue
        else:
            # 4. does not exist
            problems.append(PathProblem(setting, val_str, "does not exist"))
            continue

    return problems


def check_purchasing_channel() -> bool:
    """Validate that PURCHASING_CHANNEL is configured.

    Returns True if configured, False otherwise.
    Logs an operator-facing error if unset.
    """
    channel = getattr(config, "PURCHASING_CHANNEL", "").strip()
    if not channel:
        log.error("PURCHASING_CHANNEL is unset; purchase requests cannot be posted.")
        print("❌ PURCHASING_CHANNEL is not set in environment or .env")
        return False
    print(f"✅ PURCHASING_CHANNEL configured: {channel}")
    return True


STORAGE_PATHS = {
    "PURCHASING_LOG_PATH": {
        "env": "PURCHASING_LOG_PATH",
        "config_attr": "WORKBOOK_PATH",
        "description": "Purchasing-Log.xlsx (Excel workbook)",
        "example": r"C:\Users\<your-windows-account>\OneDrive\Purchasing\Purchasing-Log.xlsx",
    },
    "EPIFS_DIR": {
        "env": "EPIFS_DIR",
        "config_attr": "EPIFS_DIR",
        "description": "EPIFs directory (where PDFs are saved)",
        "example": r"C:\Users\<your-windows-account>\OneDrive\Purchasing\EPIFs",
    },
    "CONFIRMATIONS_DIR": {
        "env": "CONFIRMATIONS_DIR",
        "config_attr": "CONFIRMATIONS_DIR",
        "description": "Order-Confirmations directory",
        "example": r"C:\Users\<your-windows-account>\OneDrive\Purchasing\Order-Confirmations",
    },
    "QUOTES_DIR": {
        "env": "QUOTES_DIR",
        "config_attr": "QUOTES_DIR",
        "description": "Quotes directory (vendor quotes)",
        "example": r"C:\Users\<your-windows-account>\OneDrive\Purchasing\Quotes",
    },
    "BOMS_DIR": {
        "env": "BOMS_DIR",
        "config_attr": "BOMS_DIR",
        "description": "BOMs directory (itemised BOM spreadsheets)",
        "example": r"C:\Users\<your-windows-account>\OneDrive\Purchasing\BOMs",
    },
}


def path_exists(path: str) -> bool:
    """Check if a file or directory exists."""
    try:
        return os.path.exists(path)
    except Exception:
        return False


def find_onedrive_root() -> str | None:
    """Try to find the OneDrive sync root directory."""
    username = os.getenv("USERNAME", "")
    candidates = [
        os.path.expanduser("~/OneDrive"),
        os.path.expanduser("~/OneDrive - UW-Madison"),
        f"C:\\Users\\{username}\\OneDrive",
        f"C:\\Users\\{username}\\OneDrive - UW-Madison",
    ]
    for candidate in candidates:
        if os.path.isdir(candidate):
            return candidate
    return None


def search_for_purchasing_log() -> str | None:
    """Search common locations for Purchasing-Log.xlsx."""
    onedrive = find_onedrive_root()
    if not onedrive:
        return None

    search_paths = [
        os.path.join(onedrive, "Purchasing", "Purchasing-Log.xlsx"),
        os.path.join(onedrive, "Shortcuts", "Charles Hirst's files - Hirst-Lab", "Purchasing", "Purchasing-Log.xlsx"),
    ]

    for path in search_paths:
        if os.path.isfile(path):
            return path
    return None


def prompt_for_path(storage_type: str, description: str, example: str) -> str | None:
    """Interactive prompt for user to provide a custom path."""
    print(f"\n{'='*70}")
    print(f"❌ Cannot find: {description}")
    print(f"   Expected type: {storage_type}")
    print(f"\nExample path format:\n   {example}")
    print(f"{'='*70}\n")

    while True:
        user_input = input(f"Enter the path to {description}\n(or press Enter to skip): ").strip()

        if not user_input:
            return None

        # Expand user home directory if needed
        expanded = os.path.expanduser(user_input)

        # Check if it exists
        if storage_type == "file" and os.path.isfile(expanded):
            return expanded
        elif storage_type == "directory" and os.path.isdir(expanded):
            return expanded
        else:
            print("❌ Path not found or not the right type. Please try again.\n")


def validate_and_configure() -> bool:
    """
    Validate all required storage paths at startup.

    Returns True if all paths are valid, False if user cancelled setup.
    Raises ValueError if paths are missing and user can't provide them.
    """
    print("\n" + "="*70)
    print("🔍 Validating storage paths...")
    print("="*70)

    all_valid = True
    missing_paths = {}

    # Check Purchasing-Log.xlsx (file)
    if not path_exists(config.WORKBOOK_PATH):
        all_valid = False
        missing_paths["PURCHASING_LOG_PATH"] = ("file", "Purchasing-Log.xlsx")
        print("❌ Purchasing-Log.xlsx not found at:")
        print(f"   {config.WORKBOOK_PATH}")
    else:
        print("✅ Purchasing-Log.xlsx found")

    # Check EPIFs directory
    if not path_exists(config.EPIFS_DIR):
        all_valid = False
        missing_paths["EPIFS_DIR"] = ("directory", "EPIFs directory")
        print("❌ EPIFs directory not found at:")
        print(f"   {config.EPIFS_DIR}")
    else:
        print("✅ EPIFs directory found")

    # Check Order-Confirmations directory
    if not path_exists(config.CONFIRMATIONS_DIR):
        all_valid = False
        missing_paths["CONFIRMATIONS_DIR"] = ("directory", "Order-Confirmations directory")
        print("❌ Order-Confirmations directory not found at:")
        print(f"   {config.CONFIRMATIONS_DIR}")
    else:
        print("✅ Order-Confirmations directory found")

    # Check Quotes directory
    if not path_exists(config.QUOTES_DIR):
        all_valid = False
        missing_paths["QUOTES_DIR"] = ("directory", "Quotes directory")
        print("❌ Quotes directory not found at:")
        print(f"   {config.QUOTES_DIR}")
    else:
        print("✅ Quotes directory found")

    # Check BOMs directory (Ticket 26)
    if not path_exists(config.BOMS_DIR):
        all_valid = False
        missing_paths["BOMS_DIR"] = ("directory", "BOMs directory")
        print("❌ BOMs directory not found at:")
        print(f"   {config.BOMS_DIR}")
    else:
        print("✅ BOMs directory found")

    # Check Purchasing Channel (Ticket 15)
    if not check_purchasing_channel():
        all_valid = False

    if all_valid:
        print("\n✅ All storage paths are accessible!")
        print("="*70 + "\n")
        return True

    # Paths are missing - try to auto-locate or prompt user
    print("\n" + "="*70)
    print("⚠️  Some paths are missing. Attempting to auto-locate...")
    print("="*70 + "\n")

    env_updates = {}

    # Try to auto-find Purchasing-Log.xlsx
    if "PURCHASING_LOG_PATH" in missing_paths:
        found = search_for_purchasing_log()
        if found:
            print("✅ Found Purchasing-Log.xlsx at:")
            print(f"   {found}\n")
            env_updates["PURCHASING_LOG_PATH"] = found
            del missing_paths["PURCHASING_LOG_PATH"]

    # Prompt for remaining missing paths
    for key, (path_type, description) in missing_paths.items():
        meta = STORAGE_PATHS[key]
        path = prompt_for_path(path_type, description, meta["example"])
        if path:
            env_updates[key] = path
        else:
            raise ValueError(
                f"❌ Cannot proceed without {description}.\n"
                f"   Please set the {key} environment variable or .env file entry."
            )

    # Save to .env file for persistence
    if env_updates:
        env_file = os.path.join(config.BASE_DIR, ".env")
        print("\n💾 Saving configuration to .env...")

        # Read existing .env preserving all lines (comments, blanks, etc.)
        original_lines = []
        existing_keys = set()
        if os.path.exists(env_file):
            with open(env_file, "r", encoding="utf-8") as f:
                original_lines = f.readlines()
            for line in original_lines:
                stripped = line.strip()
                if stripped and "=" in stripped and not stripped.startswith("#"):
                    k = stripped.split("=", 1)[0].strip()
                    existing_keys.add(k)

        # Update existing keys in-place, preserving file structure
        updated_keys = set()
        new_lines = []
        for line in original_lines:
            stripped = line.strip()
            if stripped and "=" in stripped and not stripped.startswith("#"):
                k = stripped.split("=", 1)[0].strip()
                if k in env_updates:
                    new_lines.append(f'{k}="{env_updates[k]}"\n')
                    updated_keys.add(k)
                    continue
            new_lines.append(line)

        # Append any new keys that weren't already in the file
        for k, v in env_updates.items():
            if k not in updated_keys:
                new_lines.append(f'{k}="{v}"\n')

        with open(env_file, "w", encoding="utf-8") as f:
            f.writelines(new_lines)

        print("✅ Configuration saved to .env\n")

        # Also update os.environ for this session
        for k, v in env_updates.items():
            os.environ[k] = v

        # Reload config module to pick up new paths
        import importlib
        importlib.reload(config)

        return True

    print("✅ All paths configured!")
    print("="*70 + "\n")
    return True
