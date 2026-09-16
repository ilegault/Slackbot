"""The request index store for P-Bot.

Maintains requests.json with atomic writes and thread-level request tracking.
Excel remains the source of truth for row processing stages; this store tracks
request metadata, multi-item batch mappings, card message timestamps, and history.
"""
import json
import logging
import os
import secrets
import shutil
import tempfile
from datetime import datetime
from typing import Any, Dict, List, Optional

try:
    from . import config
except ImportError:
    import config

log = logging.getLogger("p-bot.store")

STORE_PATH = os.path.join(config.BASE_DIR, "requests.json")


def load_store(alert_callback=None) -> Dict[str, Dict[str, Any]]:
    """Load the request store from JSON.

    If the file does not exist, returns an empty dictionary.
    If corrupted, moves the bad file to requests.json.bad, triggers an admin alert,
    and returns an empty dictionary.
    """
    if not os.path.exists(STORE_PATH):
        return {}

    try:
        with open(STORE_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, dict):
                return data
            log.error("Corrupt store structure (expected dict, got %s)", type(data))
            raise ValueError("Store root must be a JSON object")
    except Exception as e:
        log.error("Failed to load request store from %s: %s", STORE_PATH, e)
        bad_path = STORE_PATH + ".bad"
        try:
            shutil.copyfile(STORE_PATH, bad_path)
            log.warning("Preserved corrupted store file to %s", bad_path)
        except Exception as copy_err:
            log.error("Could not copy corrupted store file: %s", copy_err)

        if alert_callback:
            try:
                alert_callback(f"⚠️ *Store Corruption Alert:* `requests.json` was corrupted and moved to `{bad_path}`.")
            except Exception as alert_err:
                log.warning("Could not dispatch store corruption alert: %s", alert_err)

        return {}


def save_store(data: Dict[str, Dict[str, Any]]) -> None:
    """Save the store atomically using a temporary file."""
    dir_name = os.path.dirname(os.path.abspath(STORE_PATH))
    os.makedirs(dir_name, exist_ok=True)

    with tempfile.NamedTemporaryFile("w", dir=dir_name, delete=False, encoding="utf-8") as tf:
        json.dump(data, tf, indent=2)
        temp_path = tf.name

    try:
        os.replace(temp_path, STORE_PATH)
        log.debug("Saved request store to %s (%d requests)", STORE_PATH, len(data))
    except Exception as e:
        log.error("Failed to replace store file with %s: %s", temp_path, e)
        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except Exception:
                pass
        raise


def generate_request_id(existing_keys: set) -> str:
    """Generate a unique request_id in format req_XXXX (4 hex chars)."""
    while True:
        candidate = f"req_{secrets.token_hex(2)}"
        if candidate not in existing_keys:
            return candidate


def create(
    channel: str,
    thread_ts: str,
    requester: str,
    requester_id: Optional[str] = None,
    card_ts: Optional[str] = None,
    buyer: Optional[str] = None,
    buyer_id: Optional[str] = None,
    rows: Optional[List[int]] = None,
    items: Optional[List[Dict[str, Any]]] = None,
    attachments: Optional[List[str]] = None,
    history: Optional[List[str]] = None,
    created_at: Optional[str] = None,
    **extra,
) -> str:
    """Create and persist a new request record. Returns the generated request_id."""
    store = load_store()
    req_id = generate_request_id(set(store.keys()))

    record = {
        "channel": channel,
        "card_ts": card_ts,
        "thread_ts": thread_ts,
        "requester": requester,
        "requester_id": requester_id,
        "buyer": buyer,
        "buyer_id": buyer_id,
        "rows": rows or [],
        "items": items or [],
        "attachments": attachments or [],
        "history": history or [],
        "created_at": created_at or datetime.now().isoformat(timespec="seconds"),
    }
    record.update(extra)

    store[req_id] = record
    save_store(store)
    log.info("Created request record [%s] for thread %s in channel %s (rows: %s)", req_id, thread_ts, channel, record["rows"])
    return req_id


def get(request_id: str) -> Optional[Dict[str, Any]]:
    """Retrieve a request record by request_id."""
    store = load_store()
    return store.get(request_id)


def get_by_thread(channel: str, thread_ts: str) -> Optional[Dict[str, Any]]:
    """Find a request record associated with a specific channel and thread_ts."""
    store = load_store()
    for req_id, record in store.items():
        if record.get("channel") == channel and record.get("thread_ts") == thread_ts:
            req_copy = dict(record)
            req_copy["request_id"] = req_id
            return req_copy
    return None


def update(request_id: str, **fields) -> Optional[Dict[str, Any]]:
    """Update specific fields of an existing request record and save."""
    store = load_store()
    if request_id not in store:
        log.warning("Attempted to update non-existent request [%s]", request_id)
        return None

    store[request_id].update(fields)
    save_store(store)
    log.debug("Updated request [%s] with fields: %s", request_id, list(fields.keys()))
    return store[request_id]


def append_history(request_id: str, line: str) -> Optional[Dict[str, Any]]:
    """Append a timestamped/formatted event line to the request's history list."""
    store = load_store()
    if request_id not in store:
        log.warning("Attempted to append history to non-existent request [%s]", request_id)
        return None

    history = store[request_id].setdefault("history", [])
    history.append(line)
    save_store(store)
    log.debug("Appended history line to request [%s]: '%s'", request_id, line)
    return store[request_id]


def delete(request_id: str) -> bool:
    """Delete a request record from the store."""
    store = load_store()
    if request_id in store:
        del store[request_id]
        save_store(store)
        log.info("Deleted request record [%s]", request_id)
        return True
    return False
