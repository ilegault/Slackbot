"""Self-service roster management for requesters, admins, approvers, buyers, and vendors.

Stores data in roster.json with atomic writes.

WHY THIS EXISTS:
----------------
Manages lab purchasing roles and permissions. Changes to roster.json take effect
immediately because all accessors re-read from disk without requiring a bot restart.
Roles are stored as Slack IDs (never display names) so users can be mentioned and
profile changes do not break permissions.
"""
import json
import logging
import os
import tempfile
from typing import Any, Dict, List, Set

try:
    from . import config
except ImportError:
    import config

log = logging.getLogger("p-bot.roster")

ROSTER_PATH = os.path.join(config.BASE_DIR, "roster.json")

DEFAULT_WORKDAY_VENDORS = [
    "Abcam", "Airgas", "Apple", "B&H Photo", "Bio Rad", "CDWG", "Dell",
    "Dot Scientific", "Eppendorf", "Fastenal", "First Supply", "Fisher Scientific",
    "Grainger", "IDT", "Life Technologies", "McKesson", "Medline", "MIDSCI",
    "MSC", "Neta Scientific", "Newark", "New England BioLabs", "Promega",
    "Qiagen", "Rainin", "Santa Cruz", "Sigma Aldrich", "Staples", "USA Scientific",
    "Vanguard", "VWR-AVANTOR", "Anixter", "Kranz", "NASSCO",
]

DEFAULT_VALID_REQUESTERS = [
    "Isaac", "Smeet", "Dylan", "Charlie H.", "Alex", "Casey", "Prof. Hirst",
    "Copeland", "Erich", "Finn", "Eddie", "Katarina", "Keyvan",
]

DEFAULT_APPROVER_ID = "U07L2RFEPJ9"


def _get_initial_seed() -> Dict[str, Any]:
    """Generate initial seed data from current config or defaults."""
    requesters = {}
    if hasattr(config, "SLACK_USER_TO_REQUESTER") and config.SLACK_USER_TO_REQUESTER:
        requesters.update(config.SLACK_USER_TO_REQUESTER)

    admins = []
    if hasattr(config, "ADMIN_SLACK_USER_IDS") and config.ADMIN_SLACK_USER_IDS:
        admins.extend([a for a in config.ADMIN_SLACK_USER_IDS if a])

    approvers = [DEFAULT_APPROVER_ID]
    if hasattr(config, "APPROVER_SLACK_USER_IDS") and config.APPROVER_SLACK_USER_IDS:
        for apprv in config.APPROVER_SLACK_USER_IDS:
            if apprv and apprv not in approvers:
                approvers.append(apprv)

    buyers = []
    if hasattr(config, "BUYER_SLACK_USER_IDS") and config.BUYER_SLACK_USER_IDS:
        for b in config.BUYER_SLACK_USER_IDS:
            if b and b not in buyers:
                buyers.append(b)

    vendors = list(DEFAULT_WORKDAY_VENDORS)
    if hasattr(config, "WORKDAY_VENDORS") and config.WORKDAY_VENDORS:
        for v in config.WORKDAY_VENDORS:
            if v and v not in vendors:
                vendors.append(v)

    return {
        "requesters": requesters,
        "admins": admins,
        "approvers": approvers,
        "buyers": buyers,
        "vendors": sorted(vendors),
    }


def load_roster() -> Dict[str, Any]:
    """Load roster from JSON file, initializing and saving initial seed if missing."""
    if not os.path.exists(ROSTER_PATH):
        initial_data = _get_initial_seed()
        save_roster(initial_data)
        return initial_data

    try:
        with open(ROSTER_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)

        changed = False
        if "requesters" not in data:
            data["requesters"] = {}
            changed = True
        if "admins" not in data:
            data["admins"] = []
            changed = True
        if "approvers" not in data:
            data["approvers"] = [DEFAULT_APPROVER_ID]
            changed = True
        if "buyers" not in data:
            data["buyers"] = []
            changed = True
        if "vendors" not in data:
            data["vendors"] = list(DEFAULT_WORKDAY_VENDORS)
            changed = True

        if changed:
            save_roster(data)
        return data
    except Exception as e:
        log.error("Failed to read roster file from %s: %s. Re-seeding defaults.", ROSTER_PATH, e)
        initial_data = _get_initial_seed()
        save_roster(initial_data)
        return initial_data


def save_roster(data: Dict[str, Any]) -> None:
    """Atomically save roster data to JSON file."""
    os.makedirs(os.path.dirname(os.path.abspath(ROSTER_PATH)), exist_ok=True)
    temp_dir = os.path.dirname(os.path.abspath(ROSTER_PATH))
    with tempfile.NamedTemporaryFile("w", dir=temp_dir, delete=False, encoding="utf-8") as tf:
        json.dump(data, tf, indent=2, ensure_ascii=False)
        temp_name = tf.name

    os.replace(temp_name, ROSTER_PATH)
    log.info("Saved updated roster to %s", ROSTER_PATH)


def get_requesters() -> Dict[str, str]:
    """Return dictionary of Slack User ID -> Display / Requester Name."""
    data = load_roster()
    return data.get("requesters", {})


def get_valid_requesters() -> Set[str]:
    """Return set of valid requester names (both mapped users and lab members)."""
    data = load_roster()
    names = set(data.get("requesters", {}).values())
    names.update(DEFAULT_VALID_REQUESTERS)
    return names


def get_admins() -> List[str]:
    """Return list of admin Slack User IDs."""
    data = load_roster()
    return data.get("admins", [])


def get_approvers() -> List[str]:
    """Return list of authorized approver Slack User IDs."""
    data = load_roster()
    return data.get("approvers", [DEFAULT_APPROVER_ID])


def get_buyers() -> List[str]:
    """Return list of purchase buyer Slack User IDs."""
    data = load_roster()
    return data.get("buyers", [])


def is_buyer(slack_id: str) -> bool:
    """Check if a Slack user ID is an authorized purchase buyer."""
    if not slack_id:
        return False
    return slack_id in get_buyers()


def get_vendors() -> List[str]:
    """Return sorted list of active Workday punchout/catalog vendor names."""
    data = load_roster()
    return sorted(data.get("vendors", []))


def add_requester(slack_id: str, name: str) -> None:
    """Add or update a Slack ID -> Requester Name mapping."""
    data = load_roster()
    data.setdefault("requesters", {})[slack_id] = name.strip()
    save_roster(data)
    log.info("Added requester mapping: %s -> %s", slack_id, name)


def add_admin(slack_id: str) -> None:
    """Add a Slack user ID to the administrator list."""
    data = load_roster()
    admins = data.setdefault("admins", [])
    if slack_id not in admins:
        admins.append(slack_id)
        save_roster(data)
        log.info("Added admin user: %s", slack_id)


def add_approver(slack_id: str) -> None:
    """Add a Slack user ID to the purchase request approver list."""
    data = load_roster()
    approvers = data.setdefault("approvers", [])
    if slack_id not in approvers:
        approvers.append(slack_id)
        save_roster(data)
        log.info("Added approver user: %s", slack_id)


def remove_approver(slack_id: str) -> bool:
    """Remove a Slack user ID from the purchase request approver list.

    Returns True if removed, False if not present.
    """
    data = load_roster()
    approvers = data.setdefault("approvers", [])
    if slack_id in approvers:
        approvers.remove(slack_id)
        save_roster(data)
        log.info("Removed approver user: %s", slack_id)
        return True
    return False


def add_buyer(slack_id: str) -> None:
    """Add a Slack user ID to the purchase buyer list."""
    data = load_roster()
    buyers = data.setdefault("buyers", [])
    if slack_id not in buyers:
        buyers.append(slack_id)
        save_roster(data)
        log.info("Added buyer user: %s", slack_id)


def remove_buyer(slack_id: str) -> bool:
    """Remove a Slack user ID from the purchase buyer list.

    Returns True if removed, False if not present.
    """
    data = load_roster()
    buyers = data.setdefault("buyers", [])
    if slack_id in buyers:
        buyers.remove(slack_id)
        save_roster(data)
        log.info("Removed buyer user: %s", slack_id)
        return True
    return False


def add_vendor(name: str) -> None:
    """Add a vendor name to the active Workday punchout catalog list."""
    clean_name = name.strip()
    if not clean_name:
        return
    data = load_roster()
    vendors = data.setdefault("vendors", [])
    if clean_name not in vendors:
        vendors.append(clean_name)
        vendors.sort()
        save_roster(data)
        log.info("Added vendor: %s", clean_name)


def remove_vendor(name: str) -> bool:
    """Remove a vendor name from the Workday punchout catalog list.

    Matches case-insensitively or exact match.
    Returns True if removed, False if not found.
    """
    clean_name = name.strip()
    data = load_roster()
    vendors = data.setdefault("vendors", [])

    # Exact match first
    if clean_name in vendors:
        vendors.remove(clean_name)
        save_roster(data)
        log.info("Removed vendor: %s", clean_name)
        return True

    # Case-insensitive match fallback
    for v in list(vendors):
        if v.lower() == clean_name.lower():
            vendors.remove(v)
            save_roster(data)
            log.info("Removed vendor (matched '%s'): %s", clean_name, v)
            return True

    return False
