"""Heartbeat Monitor (Dead-Man's Switch) and Alerting Dispatcher for P-Bot.

Sends periodic heartbeat pings to external monitoring services (e.g., Healthchecks.io,
BetterStack) and dispatches boot & crash alerts to the configured Slack admin channel.
"""
from datetime import datetime
import logging
import platform
import sys
import threading
import time
from typing import Optional

import requests

try:
    from . import config
except ImportError:
    import config

log = logging.getLogger("p-bot.heartbeat")


class HeartbeatMonitor:
    """Runs a background daemon thread that pings an external healthcheck endpoint."""

    def __init__(self, url: Optional[str] = None, interval: Optional[int] = None):
        self.url = url or config.HEALTHCHECK_URL
        self.interval = interval or config.HEALTHCHECK_INTERVAL_SECONDS
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def start(self):
        """Start the background heartbeat monitor thread."""
        if not self.url:
            log.info("No HEALTHCHECK_URL configured. Heartbeat monitor will not start.")
            return

        if self._thread and self._thread.is_alive():
            return

        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run_loop,
            name="HeartbeatMonitorThread",
            daemon=True,
        )
        self._thread.start()
        log.info(
            "Heartbeat monitor started (URL: %s, Interval: %ds)",
            self.url,
            self.interval,
        )

    def stop(self, timeout: float = 3.0):
        """Stop the heartbeat monitor thread cleanly."""
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=timeout)
            log.info("Heartbeat monitor stopped.")

    def ping(self) -> bool:
        """Send a single healthcheck ping request."""
        if not self.url:
            return False
        try:
            res = requests.get(self.url, timeout=15)
            log.debug("Heartbeat ping returned status code %s", res.status_code)
            return res.status_code == 200
        except Exception as e:
            log.warning("Failed to send heartbeat ping to %s: %s", self.url, e)
            return False

    def _run_loop(self):
        """Periodic loop executing heartbeat pings."""
        # Initial ping on startup
        self.ping()
        while not self._stop_event.is_set():
            if self._stop_event.wait(max(10, self.interval)):
                break
            self.ping()


_HEARTBEAT_INSTANCE: Optional[HeartbeatMonitor] = None


def start_heartbeat(url: Optional[str] = None, interval: Optional[int] = None) -> Optional[HeartbeatMonitor]:
    """Start global heartbeat monitor if HEALTHCHECK_URL is provided."""
    global _HEARTBEAT_INSTANCE
    if _HEARTBEAT_INSTANCE is None:
        _HEARTBEAT_INSTANCE = HeartbeatMonitor(url=url, interval=interval)
    _HEARTBEAT_INSTANCE.start()
    return _HEARTBEAT_INSTANCE


def stop_heartbeat(timeout: float = 3.0):
    """Stop global heartbeat monitor."""
    global _HEARTBEAT_INSTANCE
    if _HEARTBEAT_INSTANCE:
        _HEARTBEAT_INSTANCE.stop(timeout=timeout)


def send_startup_alert(client) -> bool:
    """Send boot / startup diagnostic notification to ADMIN_ALERT_CHANNEL."""
    if not client or not config.ADMIN_ALERT_CHANNEL:
        log.info("ADMIN_ALERT_CHANNEL not set or client unavailable; skipping startup alert.")
        return False

    host = platform.node() or "Unknown Host"
    os_info = f"{platform.system()} {platform.release()}"
    py_ver = sys.version.split()[0]
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    blocks = [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": "🟢 P-Bot Online & Ready",
                "emoji": True,
            },
        },
        {
            "type": "section",
            "fields": [
                {
                    "type": "mrkdwn",
                    "text": f"*Host Machine:*\n`{host}` ({os_info})",
                },
                {
                    "type": "mrkdwn",
                    "text": f"*Bot Version:*\n`v{config.BOT_VERSION}` (Python {py_ver})",
                },
                {
                    "type": "mrkdwn",
                    "text": f"*Started At:*\n{now_str}",
                },
                {
                    "type": "mrkdwn",
                    "text": f"*Socket Mode:*\n`Connected`",
                },
            ],
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*Workbook Path:*\n`{config.WORKBOOK_PATH}`",
            },
        },
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": "Hirst Lab Automation • Send `@p-bot health` for system diagnostics",
                },
            ],
        },
    ]

    fallback_text = (
        f"🟢 *P-Bot Online*\n"
        f"• *Host:* `{host}` ({os_info})\n"
        f"• *Version:* `v{config.BOT_VERSION}`\n"
        f"• *Log Path:* `{config.WORKBOOK_PATH}`\n"
        f"• *Status:* Listening for Slack events via Socket Mode."
    )

    try:
        client.chat_postMessage(
            channel=config.ADMIN_ALERT_CHANNEL,
            text=fallback_text,
            blocks=blocks,
        )
        log.info("Sent startup alert to ADMIN_ALERT_CHANNEL (%s)", config.ADMIN_ALERT_CHANNEL)
        return True
    except Exception as e:
        log.warning("Could not dispatch startup alert to %s: %s", config.ADMIN_ALERT_CHANNEL, e)
        return False


def send_crash_alert(client, error_msg: str, exc_info: Optional[str] = None) -> bool:
    """Send crash or critical exception alert to ADMIN_ALERT_CHANNEL."""
    if not client or not config.ADMIN_ALERT_CHANNEL:
        return False

    host = platform.node() or "Unknown Host"
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    text = f"🚨 *P-Bot Critical Error / Crash Alert*\n• *Host:* `{host}`\n• *Time:* {now_str}\n• *Error:* {error_msg}"
    if exc_info:
        snippet = exc_info[-1500:] if len(exc_info) > 1500 else exc_info
        text += f"\n```{snippet}```"

    try:
        client.chat_postMessage(
            channel=config.ADMIN_ALERT_CHANNEL,
            text=text,
        )
        log.info("Sent crash alert to ADMIN_ALERT_CHANNEL (%s)", config.ADMIN_ALERT_CHANNEL)
        return True
    except Exception as e:
        log.warning("Could not dispatch crash alert to %s: %s", config.ADMIN_ALERT_CHANNEL, e)
        return False
