"""Background Excel Lock Queue Worker for P-Bot.

Guarantees strictly serialized writes to Purchasing-Log.xlsx and automatically
handles retries when the workbook is locked by Excel (~$Purchasing-Log.xlsx).
"""
from dataclasses import dataclass, field
from datetime import datetime
import logging
import queue
import threading
import time
from typing import Any, Callable, Dict, List, Optional
import uuid

try:
    from . import config
    from . import log_writer
except ImportError:
    import config
    import log_writer

log = logging.getLogger("p-bot.queue")


@dataclass
class WriteTask:
    task_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    task_type: str = "append"  # 'append' or 'update'
    channel: str = ""
    thread_ts: str = ""
    user_id: str = ""
    action_fn: Optional[Callable[[], Any]] = None
    success_callback: Optional[Callable[[Any], None]] = None
    failure_callback: Optional[Callable[[Exception], None]] = None
    description: str = ""
    created_at: datetime = field(default_factory=datetime.now)
    last_retry: Optional[datetime] = None
    retry_count: int = 0


class LockQueueWorker:
    """Manages background serialized writes and automatic lock retries for Excel."""

    def __init__(self, client=None):
        self.client = client
        self._queue: queue.Queue = queue.Queue()
        self._stop_event = threading.Event()
        self._worker_thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        self._current_task: Optional[WriteTask] = None
        self._pending_tasks: List[WriteTask] = []
        self._lock_notified_task_ids: set = set()
        self._admin_alerted_task_ids: set = set()

    def start(self):
        """Start the background worker thread."""
        with self._lock:
            if self._worker_thread and self._worker_thread.is_alive():
                return
            self._stop_event.clear()
            self._worker_thread = threading.Thread(
                target=self._worker_loop,
                name="LockQueueWorkerThread",
                daemon=True,
            )
            self._worker_thread.start()
            log.info("LockQueueWorker background thread started.")

    def stop(self, timeout: float = 5.0):
        """Stop the background worker thread cleanly."""
        self._stop_event.set()
        if self._worker_thread and self._worker_thread.is_alive():
            self._worker_thread.join(timeout=timeout)
            log.info("LockQueueWorker background thread stopped.")

    def submit(self, task: WriteTask) -> WriteTask:
        """Enqueue a write task for serialized processing."""
        with self._lock:
            self._pending_tasks.append(task)
        self._queue.put(task)
        log.info(
            "Enqueued write task [%s] (Type: %s, Desc: '%s', User: %s)",
            task.task_id,
            task.task_type,
            task.description,
            task.user_id,
        )
        return task

    def get_status(self) -> Dict[str, Any]:
        """Return a snapshot of current queue state."""
        with self._lock:
            current = None
            if self._current_task:
                current = {
                    "task_id": self._current_task.task_id,
                    "task_type": self._current_task.task_type,
                    "description": self._current_task.description,
                    "user_id": self._current_task.user_id,
                    "channel": self._current_task.channel,
                    "thread_ts": self._current_task.thread_ts,
                    "created_at": self._current_task.created_at.strftime("%Y-%m-%d %H:%M:%S"),
                    "retry_count": self._current_task.retry_count,
                    "last_retry": self._current_task.last_retry.strftime("%Y-%m-%d %H:%M:%S") if self._current_task.last_retry else None,
                }
            queued = []
            for t in self._pending_tasks:
                if self._current_task and t.task_id == self._current_task.task_id:
                    continue
                queued.append({
                    "task_id": t.task_id,
                    "task_type": t.task_type,
                    "description": t.description,
                    "user_id": t.user_id,
                    "channel": t.channel,
                    "thread_ts": t.thread_ts,
                    "created_at": t.created_at.strftime("%Y-%m-%d %H:%M:%S"),
                    "retry_count": t.retry_count,
                })

            total_pending = len(self._pending_tasks)
            is_locked = bool(self._current_task and self._current_task.retry_count > 0)
            return {
                "pending_count": total_pending,
                "is_locked": is_locked,
                "current_task": current,
                "queued_tasks": queued,
            }

    def _notify_slack(self, channel: str, thread_ts: str, text: str):
        """Send a message to a Slack channel/thread safely."""
        if not self.client or not channel:
            return
        try:
            self.client.chat_postMessage(
                channel=channel,
                thread_ts=thread_ts or None,
                text=text,
            )
        except Exception as e:
            log.warning("Could not send queue notification to Slack (%s, %s): %s", channel, thread_ts, e)

    def _notify_admin_alert(self, text: str):
        """Send an alert to ADMIN_ALERT_CHANNEL."""
        if not self.client or not config.ADMIN_ALERT_CHANNEL:
            return
        try:
            self.client.chat_postMessage(
                channel=config.ADMIN_ALERT_CHANNEL,
                text=text,
            )
        except Exception as e:
            log.warning("Could not send admin queue alert to %s: %s", config.ADMIN_ALERT_CHANNEL, e)

    def _worker_loop(self):
        """Continuous execution loop processing tasks one by one."""
        while not self._stop_event.is_set():
            try:
                task: WriteTask = self._queue.get(timeout=0.5)
            except queue.Empty:
                continue

            with self._lock:
                self._current_task = task

            # Loop retrying the current task until success, non-lock failure, or shutdown
            while not self._stop_event.is_set():
                try:
                    if task.action_fn is None:
                        raise ValueError("No action_fn provided for WriteTask")

                    result = task.action_fn()

                    # Write completed successfully!
                    log.info("WriteTask [%s] completed successfully. Result: %s", task.task_id, result)

                    # If this task was previously delayed by a lock, notify the thread that lock is released
                    if task.retry_count > 0:
                        row_str = f" (Row `#{result}`)" if isinstance(result, int) else ""
                        self._notify_slack(
                            channel=task.channel,
                            thread_ts=task.thread_ts,
                            text=(
                                f"✅ *Update Applied:* `Purchasing-Log.xlsx` was released and your request has been logged!{row_str}"
                            ),
                        )

                    # Call success callback
                    if task.success_callback:
                        try:
                            task.success_callback(result)
                        except Exception as cb_err:
                            log.exception("Error in success_callback for task [%s]: %s", task.task_id, cb_err)

                    break  # Exit retry loop for this task

                except (log_writer.WorkbookLockedError, PermissionError) as lock_error:
                    # Workbook is locked by Excel
                    task.retry_count += 1
                    task.last_retry = datetime.now()

                    # Notify thread if first lock encounter
                    if task.task_id not in self._lock_notified_task_ids:
                        self._lock_notified_task_ids.add(task.task_id)
                        log.warning(
                            "Workbook locked during task [%s]. Notifying thread and queueing retry.",
                            task.task_id,
                        )
                        self._notify_slack(
                            channel=task.channel,
                            thread_ts=task.thread_ts,
                            text=(
                                "⏳ `Purchasing-Log.xlsx` is currently open in Excel by someone in the lab. "
                                "I've queued this update and will automatically write it as soon as the file is closed."
                            ),
                        )

                    # Check for prolonged lock timeout
                    elapsed = (datetime.now() - task.created_at).total_seconds()
                    if (
                        elapsed >= config.EXCEL_LOCK_ALERT_TIMEOUT_SECONDS
                        and task.task_id not in self._admin_alerted_task_ids
                    ):
                        self._admin_alerted_task_ids.add(task.task_id)
                        with self._lock:
                            pending_count = len(self._pending_tasks)
                        mins = int(elapsed // 60)
                        log.warning(
                            "Workbook locked for > %ds (%d mins). Alerting admin.",
                            config.EXCEL_LOCK_ALERT_TIMEOUT_SECONDS,
                            mins,
                        )
                        self._notify_admin_alert(
                            f"⚠️ *Warning:* `Purchasing-Log.xlsx` has been locked for over {mins} minutes. "
                            f"{pending_count} pending write(s) are in queue."
                        )

                    # Wait before next retry attempt
                    poll_interval = max(0.5, config.EXCEL_QUEUE_POLL_INTERVAL)
                    self._stop_event.wait(poll_interval)

                except Exception as exc:
                    # Non-recoverable error (e.g. LogFullError, ValueError)
                    log.exception("WriteTask [%s] failed with non-lock error: %s", task.task_id, exc)
                    if task.failure_callback:
                        try:
                            task.failure_callback(exc)
                        except Exception as cb_err:
                            log.exception("Error in failure_callback for task [%s]: %s", task.task_id, cb_err)
                    break

            with self._lock:
                if task in self._pending_tasks:
                    self._pending_tasks.remove(task)
                self._current_task = None
                self._lock_notified_task_ids.discard(task.task_id)
                self._admin_alerted_task_ids.discard(task.task_id)

            self._queue.task_done()


# --- Global Singleton Instance & Accessors ------------------------------------
_WORKER_INSTANCE: Optional[LockQueueWorker] = None
_WORKER_LOCK = threading.Lock()


def get_queue_worker(client=None) -> LockQueueWorker:
    """Get or create the global LockQueueWorker singleton."""
    global _WORKER_INSTANCE
    with _WORKER_LOCK:
        if _WORKER_INSTANCE is None:
            _WORKER_INSTANCE = LockQueueWorker(client=client)
        elif client and _WORKER_INSTANCE.client is None:
            _WORKER_INSTANCE.client = client
        return _WORKER_INSTANCE


def submit_write_task(
    action_fn: Callable[[], Any],
    channel: str = "",
    thread_ts: str = "",
    user_id: str = "",
    task_type: str = "append",
    description: str = "",
    success_callback: Optional[Callable[[Any], None]] = None,
    failure_callback: Optional[Callable[[Exception], None]] = None,
    client=None,
) -> WriteTask:
    """Convenience helper to submit a write task to the global queue."""
    worker = get_queue_worker(client=client)
    task = WriteTask(
        task_type=task_type,
        channel=channel,
        thread_ts=thread_ts,
        user_id=user_id,
        action_fn=action_fn,
        success_callback=success_callback,
        failure_callback=failure_callback,
        description=description,
    )
    return worker.submit(task)


def get_queue_status() -> Dict[str, Any]:
    """Get the current queue status from the global worker."""
    return get_queue_worker().get_status()


def start_queue_worker(client=None):
    """Start the global queue worker."""
    worker = get_queue_worker(client=client)
    worker.start()


def stop_queue_worker(timeout: float = 5.0):
    """Stop the global queue worker."""
    if _WORKER_INSTANCE:
        _WORKER_INSTANCE.stop(timeout=timeout)
