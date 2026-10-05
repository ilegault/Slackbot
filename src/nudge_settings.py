"""Per-stage nudge settings, kept in nudge_settings.json.

WHY THIS EXISTS:
----------------
Nudges were hardcoded (day 3, day 6 with a channel post, then every 3), so the lab
could not tune how loud the bot is without a code change and a deploy. ADR 0013
moves the schedule into a settings file: per stage (approved, processed, confirmed,
delivered) on or off, every N working days, by DM and/or by a thread reply that is
also sent to the channel.

Why a file of its own: not roster.json (that is who may do what, and is read on
every permission check) and not requests.json (that is request state). Settings are
neither. The file is gitignored like nudge_run.json: the dev copy says nothing
about the server's.

A missing file means DEFAULTS. A corrupt file also means DEFAULTS, plus an ERROR
log and one admin alert, because a nudge that silently stops is the failure this
module must not cause. A stage whose key is missing or whose `every` is not an
int >= 1 takes that stage's default, so one bad field cannot turn nudges off for
the other three stages. Pure apart from reading and writing its own file; it
imports no Slack code.
"""
import copy
import json
import logging
import os
import tempfile
from typing import Callable, Optional

try:
    from . import config
except ImportError:
    import config  # type: ignore[no-redef]

log = logging.getLogger("p-bot.nudge_settings")

SETTINGS_PATH = os.path.join(config.BASE_DIR, "nudge_settings.json")

STAGES = ("approved", "processed", "confirmed", "delivered")

DEFAULTS: dict = {
    "approved": {"enabled": False, "every": 3, "dm": True, "channel": False},
    "processed": {"enabled": True, "every": 3, "dm": True, "channel": False},
    "confirmed": {"enabled": True, "every": 5, "dm": True, "channel": False},
    "delivered": {"enabled": True, "every": 10, "dm": False, "channel": True},
}


def _valid_every(value) -> bool:
    # bool is an int subclass; `true` is not a number of days.
    return isinstance(value, int) and not isinstance(value, bool) and value >= 1


def load(alert_callback: Optional[Callable[[str], object]] = None) -> dict:
    """Return the settings, falling back to DEFAULTS stage by stage."""
    if not os.path.exists(SETTINGS_PATH):
        return copy.deepcopy(DEFAULTS)
    try:
        with open(SETTINGS_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            raise ValueError("top level is not a JSON object")
    except Exception as e:
        log.error("Could not read %s, using default nudge settings: %s", SETTINGS_PATH, e)
        if alert_callback:
            try:
                alert_callback(
                    "nudge_settings.json is unreadable, so nudges are using the default "
                    f"settings until it is fixed: {e}"
                )
            except Exception as alert_err:
                log.error("Could not send nudge_settings.json alert: %s", alert_err)
        return copy.deepcopy(DEFAULTS)

    result = copy.deepcopy(DEFAULTS)
    for stage in STAGES:
        stage_data = data.get(stage)
        if not isinstance(stage_data, dict) or not _valid_every(stage_data.get("every")):
            continue
        merged = dict(result[stage])
        for key in ("enabled", "dm", "channel"):
            if isinstance(stage_data.get(key), bool):
                merged[key] = stage_data[key]
        merged["every"] = stage_data["every"]
        result[stage] = merged
    return result


def validate(settings: dict) -> dict[str, str]:
    """Return {field_key: message} for every problem; empty means valid."""
    errors: dict[str, str] = {}
    for stage in STAGES:
        s = settings.get(stage) or {}
        if not _valid_every(s.get("every")):
            errors[f"{stage}_every"] = "Whole number, 1 or more."
        if s.get("enabled") and not (s.get("dm") or s.get("channel")):
            errors[f"{stage}_send"] = "Pick DM, Channel or both."
    return errors


def save(settings: dict) -> None:
    """Atomically write the settings (temp file + os.replace)."""
    dir_name = os.path.dirname(os.path.abspath(SETTINGS_PATH))
    os.makedirs(dir_name, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", dir=dir_name, delete=False, encoding="utf-8") as tf:
        json.dump(settings, tf, indent=2)
        temp_path = tf.name
    try:
        os.replace(temp_path, SETTINGS_PATH)
        log.info("Saved nudge settings to %s", SETTINGS_PATH)
    except Exception:
        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except Exception:
                pass
        raise
