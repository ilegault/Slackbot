"""OS-backed single-instance lock for the Purchasing bot.

WHY THIS EXISTS:
----------------
ADR 0022: Running two copies of the bot on the same computer doubles nudges,
splits `@Purchasing update` across old and new code, and creates two workbook
write queues. Claiming an OS-held file lock at startup guarantees at most one
copy runs per machine.

The lock is held by the operating system (`msvcrt.locking` on Windows,
`fcntl.flock` elsewhere) rather than by writing a PID to a file, so a crash or
power cut releases it immediately and never leaves a stale lock behind. The
open file handle is non-inheritable (Python's default) so `@Purchasing restart`
and `update` can spawn the replacement copy before exiting, and the 15-second
wait lets the new copy take over as soon as the old one exits. Held locks are
stored at module level so garbage collection never closes the file while the
bot is running.

Imports only the standard library so it can be tested directly against a real
second Python process without importing config, Slack, or app.
"""
import logging
import os
import sys
import time
from typing import TextIO

if sys.platform == "win32":
    import msvcrt
else:
    import fcntl

log = logging.getLogger("p-bot.single_instance")

_HELD_LOCKS: list["HeldLock"] = []


def _try_lock(fd: int) -> None:
    """Attempt a non-blocking exclusive lock on byte 0 of ``fd``."""
    if sys.platform == "win32":
        msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
    else:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)


def _unlock(fd: int) -> None:
    """Release the OS lock on ``fd``."""
    if sys.platform == "win32":
        msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
    else:
        fcntl.flock(fd, fcntl.LOCK_UN)


class HeldLock:
    """An OS-held single-instance lock kept open for the life of the process."""

    def __init__(self, file_obj: TextIO) -> None:
        self._file = file_obj
        self._released = False

    def release(self) -> None:
        """Unlock and close the lock file (used by tests; the bot never calls this)."""
        if self._released:
            return
        self._released = True
        try:
            self._file.seek(0)
            _unlock(self._file.fileno())
        finally:
            self._file.close()


def acquire(path: str, wait_seconds: float, poll_seconds: float = 0.5) -> HeldLock | None:
    """Claim an exclusive OS lock on ``path``, waiting up to ``wait_seconds``.

    Always makes at least one attempt (``wait_seconds=0`` tries once). Returns a
    ``HeldLock`` kept alive at module level on success, or ``None`` if another
    process still holds the lock when the wait expires.
    """
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)

    deadline = time.monotonic() + max(0.0, wait_seconds)
    while True:
        f = open(path, "a+", encoding="utf-8")
        try:
            f.seek(0)
            _try_lock(f.fileno())
        except OSError:
            f.close()
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return None
            time.sleep(min(poll_seconds, remaining))
            continue

        lock = HeldLock(f)
        _HELD_LOCKS.append(lock)
        log.debug("Acquired single-instance lock: %s", path)
        return lock
