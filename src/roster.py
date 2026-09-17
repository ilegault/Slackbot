"""Self-service roster management for requesters, admins, approvers, buyers, and vendors.

Stores data in roster.json with atomic writes.

WHY THIS EXISTS:
----------------
Manages lab purchasing roles and permissions. Changes to roster.json take effect
immediately because all accessors re-read from disk without requiring a bot restart.
Roles are stored as Slack IDs (never display names) so users can be mentioned and
profile changes do not break permissions.

roster.json is also the single source of truth for valid requester names and the
Requester Name and Grad Student lists on the workbook's Roles & Lists tab. Adding a
requester or buyer submits a sync task to log_writer through the lock queue so the
workbook's dropdowns stay current.

DEFAULT_VALID_REQUESTERS is purely an initial seed for when roster.json does not yet
exist on disk; get_valid_requesters() returns names in roster.json requesters and
nothing else, so new lab members can register without gatekeeping against a hardcoded list.
"""
import json
import logging
import os
import tempfile
from typing import Any, Dict, List, Set

try:
    from . import config, text_rules
except ImportError:
    import config
    import text_rules


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
    "Isaac", "Smeet", "Dylan", "Alex", "Casey", "Prof. Hirst",
    "Erich", "Finn", "Eddie", "Katarina", "Keyvan", "Hansel", "Zehui",
]

DEFAULT_APPROVER_ID = "U07L2RFEPJ9"


def _get_initial_seed() -> Dict[str, Any]:
    """Generate initial seed data from current config or defaults."""
    requesters = {}
    if hasattr(config, "SLACK_USER_TO_REQUESTER") and config.SLACK_USER_TO_REQUESTER:
        requesters.update(config.SLACK_USER_TO_REQUESTER)

    # Seed default valid requesters into unmapped requesters on fresh roster
    mapped_names = set(requesters.values())
    for name in DEFAULT_VALID_REQUESTERS:
        if name not in mapped_names:
            requesters[name] = name

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
    """Return set of valid requester names from roster.json."""
    data = load_roster()
    return set(data.get("requesters", {}).values())


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


def _trigger_roster_sync() -> None:
    """Submit a background task to sync roster lists to the Roles & Lists tab."""
    if not getattr(config, "ROSTER_XLSX_SYNC", True):
        return
    wb_path = getattr(config, "WORKBOOK_PATH", None)
    if not wb_path or not os.path.exists(wb_path):
        return
    try:
        from . import log_writer, queue_worker
    except ImportError:
        import log_writer
        import queue_worker

    try:
        queue_worker.submit_write_task(
            action_fn=lambda: log_writer.sync_roster_lists(),
            task_type="roster_sync",
            description="Sync roster lists to workbook",
        )
    except Exception as e:
        log.warning("Could not submit roster sync write task: %s", e)


def add_requester(slack_id: str, name: str) -> None:
    """Add or update a Slack ID -> Requester Name mapping."""
    data = load_roster()
    reqs = data.setdefault("requesters", {})
    clean_name = name.strip()
    norm_name = text_rules.normalize_requester_name(clean_name)
    # Remove unmapped seed placeholder if present
    for k, v in list(reqs.items()):
        if k == v and text_rules.normalize_requester_name(v) == norm_name:
            reqs.pop(k, None)
    reqs[slack_id] = clean_name
    save_roster(data)
    log.info("Added requester mapping: %s -> %s", slack_id, clean_name)
    _trigger_roster_sync()



def rename_requester(slack_id: str, new_name: str) -> None:
    """Rename an existing requester in the roster and trigger workbook sync.

    WHY THIS EXISTS:
    ----------------
    Ticket 19: Provides an explicit semantic helper for renaming an existing lab member,
    delegating to add_requester so atomic persistence and sync_roster_lists fire.
    """
    add_requester(slack_id, new_name)



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
        _trigger_roster_sync()


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
        _trigger_roster_sync()
        return True
    return False


def remove_member(slack_id: str) -> dict:
    """Hard-delete a member from requesters and strip all three roles in one atomic save.

    Refused if removing the user would leave the roster with no admin or no approver.
    Does NOT write to the workbook (workbook mirror is append-only by design).

    WHY THIS EXISTS:
    ----------------
    Ticket 20: Remove a role (remove-buyer / remove-approver) vs remove a member
    (remove-member) are distinct operations. Graduating students leave the lab cleanly:
    their requesters entry is hard-deleted and their admin, approver, and buyer roles
    are stripped simultaneously. Lockout guard ensures the lab is never left without
    an admin or an approver before any write to disk occurs.

    Returns dict of removed details:
        {
            "slack_id": str,
            "name": str | None,
            "roles": list[str],
            "roles_removed": list[str],
            "requester_removed": bool,
        }
    """
    clean_id = (slack_id or "").strip()
    if not clean_id:
        return {
            "slack_id": "",
            "name": None,
            "roles": [],
            "roles_removed": [],
            "requester_removed": False,
        }

    data = load_roster()
    admins = data.setdefault("admins", [])
    approvers = data.setdefault("approvers", [DEFAULT_APPROVER_ID])
    buyers = data.setdefault("buyers", [])
    requesters = data.setdefault("requesters", {})

    # Lockout checks: runs before ANY modification or write
    if clean_id in admins:
        remaining_admins = [a for a in admins if a != clean_id]
        if not remaining_admins:
            raise ValueError(f"Cannot remove <@{clean_id}>: they are the last admin in the roster.")

    if clean_id in approvers:
        remaining_approvers = [a for a in approvers if a != clean_id]
        if not remaining_approvers:
            raise ValueError(f"Cannot remove <@{clean_id}>: they are the last approver in the roster.")

    roles_removed = []
    if clean_id in admins:
        admins.remove(clean_id)
        roles_removed.append("admin")
    if clean_id in approvers:
        approvers.remove(clean_id)
        roles_removed.append("approver")
    if clean_id in buyers:
        buyers.remove(clean_id)
        roles_removed.append("buyer")

    removed_name = requesters.pop(clean_id, None)

    # Save atomically only if something actually changed
    if removed_name is not None or roles_removed:
        save_roster(data)
        log.info(
            "Removed member %s (%s) from roster; stripped roles: %s",
            clean_id,
            removed_name,
            roles_removed,
        )

    return {
        "slack_id": clean_id,
        "name": removed_name,
        "roles": roles_removed,
        "roles_removed": roles_removed,
        "requester_removed": removed_name is not None,
    }


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
