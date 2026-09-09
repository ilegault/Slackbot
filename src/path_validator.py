"""Validate and configure storage paths at startup.

If storage paths don't exist, prompts the user to either:
  1. Locate them manually (search OneDrive)
  2. Use alternative paths on different drives
  3. Use default test directories
"""
import os
import logging
from pathlib import Path

try:
    from . import config
except ImportError:
    import config

log = logging.getLogger("p-bot")

STORAGE_PATHS = {
    "PURCHASING_LOG_PATH": {
        "env": "PURCHASING_LOG_PATH",
        "config_attr": "WORKBOOK_PATH",
        "description": "Purchasing-Log.xlsx (Excel workbook)",
        "example": r"C:\Users\USERNAME\OneDrive\Purchasing\Purchasing-Log.xlsx",
    },
    "EPIFS_DIR": {
        "env": "EPIFS_DIR",
        "config_attr": "EPIFS_DIR",
        "description": "EPIFs directory (where PDFs are saved)",
        "example": r"C:\Users\USERNAME\OneDrive\Purchasing\EPIFs",
    },
    "CONFIRMATIONS_DIR": {
        "env": "CONFIRMATIONS_DIR",
        "config_attr": "CONFIRMATIONS_DIR",
        "description": "Order-Confirmations directory",
        "example": r"C:\Users\USERNAME\OneDrive\Purchasing\Order-Confirmations",
    },
    "QUOTES_DIR": {
        "env": "QUOTES_DIR",
        "config_attr": "QUOTES_DIR",
        "description": "Quotes directory (vendor quotes)",
        "example": r"C:\Users\USERNAME\OneDrive\Purchasing\Quotes",
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
            print(f"❌ Path not found or not the right type. Please try again.\n")


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
        print(f"❌ Purchasing-Log.xlsx not found at:")
        print(f"   {config.WORKBOOK_PATH}")
    else:
        print(f"✅ Purchasing-Log.xlsx found")

    # Check EPIFs directory
    if not path_exists(config.EPIFS_DIR):
        all_valid = False
        missing_paths["EPIFS_DIR"] = ("directory", "EPIFs directory")
        print(f"❌ EPIFs directory not found at:")
        print(f"   {config.EPIFS_DIR}")
    else:
        print(f"✅ EPIFs directory found")

    # Check Order-Confirmations directory
    if not path_exists(config.CONFIRMATIONS_DIR):
        all_valid = False
        missing_paths["CONFIRMATIONS_DIR"] = ("directory", "Order-Confirmations directory")
        print(f"❌ Order-Confirmations directory not found at:")
        print(f"   {config.CONFIRMATIONS_DIR}")
    else:
        print(f"✅ Order-Confirmations directory found")

    # Check Quotes directory
    if not path_exists(config.QUOTES_DIR):
        all_valid = False
        missing_paths["QUOTES_DIR"] = ("directory", "Quotes directory")
        print(f"❌ Quotes directory not found at:")
        print(f"   {config.QUOTES_DIR}")
    else:
        print(f"✅ Quotes directory found")

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
            print(f"✅ Found Purchasing-Log.xlsx at:")
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
        print(f"\n💾 Saving configuration to .env...")

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

        print(f"✅ Configuration saved to .env\n")

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
