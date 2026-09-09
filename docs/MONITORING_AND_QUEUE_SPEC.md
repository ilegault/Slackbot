# P-Bot: Monitoring, Remote Management & Excel Lock Queue Specification

This document provides the complete architecture and step-by-step implementation guide for:
1. **The Automatic Excel Lock Queue** (deferred retries when `Purchasing-Log.xlsx` is open in Excel).
2. **In-Slack Health & Diagnostic Suite** (`@p-bot status`, `@p-bot health`, `@p-bot queue`).
3. **Remote Log Viewer** (`@p-bot logs [n]`).
4. **Proactive Alerts & Heartbeats** (boot notification, crash dispatcher, and dead-man's switch).
5. **Remote Lifecycle & Update Management** (`@p-bot update`, `@p-bot restart`).

---

## 1. Architecture Overview

```
                      ┌─────────────────────────────────┐
                      │    Slack Events / User Input    │
                      └────────────────┬────────────────┘
                                       │
                 ┌─────────────────────┼─────────────────────┐
                 ▼                     ▼                     ▼
        ┌─────────────────┐   ┌─────────────────┐   ┌─────────────────┐
        │  Admin Commands │   │ Diagnostic Cmds │   │ Order Commands  │
        │ update, restart │   │  health, logs,  │   │ approved, claim │
        │ (Admin Guarded) │   │      queue      │   │ submitted, etc. │
        └────────┬────────┘   └────────┬────────┘   └────────┬────────┘
                 │                     │                     │
                 ▼                     ▼                     ▼
        ┌─────────────────┐   ┌─────────────────┐   ┌─────────────────┐
        │ Process Control │   │ System / Log    │   │  Write Request  │
        │ Git & Subproc   │   │  Diagnostics    │   │   Dispatcher    │
        └─────────────────┘   └─────────────────┘   └────────┬────────┘
                                                             │
                                        ┌────────────────────┴────────────────────┐
                                        │ Is Purchasing-Log.xlsx locked by Excel? │
                                        └──────────┬───────────────────┬──────────┘
                                                NO │                   │ YES
                                                   ▼                   ▼
                                         ┌───────────────────┐ ┌───────────────────┐
                                         │  Atomic Open &    │ │ 1. Reply in Slack │
                                         │    Write Row      │ │    "File locked;  │
                                         └───────────────────┘ │    queued."       │
                                                               │ 2. Push to Queue  │
                                                               └─────────┬─────────┘
                                                                         │
                                                                         ▼
                                                               ┌───────────────────┐
                                                               │ Lock Queue Worker │
                                                               │ (Retries every 5s)│
                                                               └─────────┬─────────┘
                                                                         │ Lock released
                                                                         ▼
                                                               ┌───────────────────┐
                                                               │ Write to Excel &  │
                                                               │ Reply in Thread   │
                                                               └───────────────────┘
```

---

## 2. Configuration & Environment Variables (`.env`)

Add the following configuration options to `src/config.py` and document in `.env.example`:

```env
# --- Admin & Notification Settings ---
# Comma-separated list of Slack User IDs allowed to run admin commands (e.g., U12345678,U87654321)
ADMIN_SLACK_USER_IDS=U0123456789

# Channel ID or Admin User ID where startup, crash, and system health alerts should be sent
ADMIN_ALERT_CHANNEL=C0123456789

# --- External Heartbeat (Dead-Man's Switch) ---
# (Optional) Healthchecks.io / BetterStack ping URL for remote uptime monitoring
HEALTHCHECK_URL=https://hc-ping.com/your-uuid-here
HEALTHCHECK_INTERVAL_SECONDS=300

# --- Lock Queue Settings ---
EXCEL_QUEUE_POLL_INTERVAL=5
EXCEL_LOCK_ALERT_TIMEOUT_SECONDS=600
```

---

## 3. Component Specifications

### 3.1. Excel Lock Queue Engine (`src/queue_worker.py`)

Create a new module `src/queue_worker.py` to manage background serial writes and lock retries.

#### Data Structure: `WriteTask`
```python
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable, Any, Dict, Optional

@dataclass
class WriteTask:
    task_id: str
    task_type: str                  # 'append' or 'update'
    channel: str
    thread_ts: str
    user_id: str
    action_fn: Callable[[], Any]    # e.g., lambda: log_writer.append_row(values)
    success_callback: Callable[[Any], None]
    failure_callback: Callable[[Exception], None]
    description: str                # e.g. "Order for Isaac: 100x Pipette Tips"
    created_at: datetime = field(default_factory=datetime.now)
    last_retry: Optional[datetime] = None
    retry_count: int = 0
```

#### Worker Behavior:
1. **Thread-Safe Queue:** Uses `queue.Queue` with a single background worker thread (`LockQueueWorker`) to guarantee strictly serialized writes to `Purchasing-Log.xlsx` (avoiding race conditions).
2. **Immediate Execution vs. Queueing:**
   - When a write is submitted, if the queue is empty, the worker immediately checks for the lock file (`~$Purchasing-Log.xlsx`) or attempts the write.
   - If `WorkbookLockedError` or `PermissionError` is caught:
     - Worker does NOT discard the task.
     - Worker notifies the Slack thread:
       > ⏳ `Purchasing-Log.xlsx` is currently open in Excel by someone in the lab. I've queued this update and will automatically write it as soon as the file is closed.
     - Worker retains the task at the front of the queue and enters a backoff poll loop (every `EXCEL_QUEUE_POLL_INTERVAL` seconds, default 5s).
3. **Lock Release Notification:**
   - Once the file is writable, the write completes, and the worker calls `success_callback(result)`.
   - The thread is notified:
     > ✅ **Update Applied:** `Purchasing-Log.xlsx` was released and your request has been logged! (Row `#XX`)
4. **Prolonged Lock Alert:**
   - If a task remains queued for longer than `EXCEL_LOCK_ALERT_TIMEOUT_SECONDS` (10 minutes), send an alert to `ADMIN_ALERT_CHANNEL`:
     > ⚠️ **Warning:** `Purchasing-Log.xlsx` has been locked for over 10 minutes. `N` pending writes are in queue.

---

### 3.2. Diagnostic & Health Commands (`src/app.py` or `src/admin.py`)

#### Command: `@p-bot health` / `@p-bot status`
Accessible to all lab members. Returns a Slack Block Kit card:

* **Host Machine:** Hostname and Platform (e.g., `LAB-PC-01 (Windows 11)`).
* **Bot Uptime:** Humanized duration since startup (e.g., `4 days, 6 hours, 12 minutes`).
* **Disk & Resource Health:**
  * Free space on local drive (e.g. `C:\ - 128.4 GB free (78%)`).
  * Process memory usage (MB).
* **Storage & OneDrive Health:**
  * `Purchasing-Log.xlsx`: Exists? Writable? Locked (`~$`)?
  * `EPIFs/`: Exists and writable?
  * `Order-Confirmations/`: Exists and writable?
  * `Quotes/`: Exists and writable?
* **Write Queue:** Current pending tasks count (e.g., `0 pending`).

#### Command: `@p-bot queue`
Shows a list of currently queued write tasks, when they were submitted, and who submitted them.

---

### 3.3. Remote Log Viewer (`@p-bot logs [n]`)

#### Security & Access Control:
- Restricted to users in `ADMIN_SLACK_USER_IDS` or private DMs with authorized users.
- Non-admin callers receive: `🔒 This command is restricted to bot administrators.`

#### Functionality:
- Reads the tail of `p_bot.log` (last `n` lines, default: 30, maximum: 100).
- Cleans and formats the text inside a markdown code block (or snippet upload if > 3000 characters).
- Filters/masks sensitive tokens if present.

---

### 3.4. Proactive Alerts & Heartbeat Engine

#### 1. Startup / Reboot Alert:
On startup in `app.py`:
- Checks environment and network connectivity.
- Dispatches a message to `ADMIN_ALERT_CHANNEL`:
  > 🟢 **P-Bot Online**
  > • **Host:** `{platform.node()}`
  > • **Version:** `1.2.0`
  > • **Log Path:** `{config.WORKBOOK_PATH}`
  > • **Status:** Listening for Slack events via Socket Mode.

#### 2. Global Exception Catcher / Crash Dispatcher:
- Wrap top-level Slack event dispatchers in a global error handler.
- If an unhandled exception occurs, log the full traceback to `p_bot.log` and post a summary alert to `ADMIN_ALERT_CHANNEL`.

#### 3. Heartbeat / Dead-Man's Switch (`src/heartbeat.py`):
- Background daemon thread running every `HEALTHCHECK_INTERVAL_SECONDS`.
- If `HEALTHCHECK_URL` is set, makes a `GET` request.
- If the lab computer loses power, crashes, or drops offline, Healthchecks.io / BetterStack alerts the admin via email/SMS.

---

### 3.5. Remote Lifecycle Management (`src/admin.py`)

#### Command: `@p-bot update` (Admin Only)
1. Runs `git pull origin main` via `subprocess.run()`.
2. Checks output for `"Already up to date."` vs changed files.
3. If dependencies changed (`requirements.txt`), runs `pip install -r requirements.txt`.
4. If update succeeded, triggers a clean restart.

#### Command: `@p-bot restart` (Admin Only)
1. Flushes log handlers and ensures the write queue is idle.
2. Uses `sys.executable` and `os.execv` (or a launcher script trigger on Windows) to re-spawn the process cleanly.
3. On Windows when running under Task Scheduler or Python wrapper:
   - Spawns a background detached restarter process and terminates current process:
     ```python
     subprocess.Popen([sys.executable, "app.py"], cwd=config.BASE_DIR, creationflags=subprocess.CREATE_NEW_PROCESS_GROUP)
     sys.exit(0)
     ```

---

## 4. Implementation Steps for the Agent

1. **Step 1: Update Configuration (`src/config.py`)**
   - Add `ADMIN_SLACK_USER_IDS` (parsed as list of strings).
   - Add `ADMIN_ALERT_CHANNEL`.
   - Add `HEALTHCHECK_URL` and `HEALTHCHECK_INTERVAL_SECONDS`.
   - Add `EXCEL_QUEUE_POLL_INTERVAL` and `EXCEL_LOCK_ALERT_TIMEOUT_SECONDS`.

2. **Step 2: Create Write Queue Engine (`src/queue_worker.py`)**
   - Implement `WriteTask`, `LockQueueWorker`, `submit_write_task()`, `get_queue_status()`.
   - Update `src/log_writer.py` helper functions if necessary to return structured lock status.

3. **Step 3: Integrate Queue in Slack Handlers (`src/app.py`)**
   - Route approval logging, claim updates, submission tracking, confirmations, and deliveries through `submit_write_task()`.

4. **Step 4: Implement Health & Remote Diagnostics (`src/admin.py` / `src/app.py`)**
   - Add `@p-bot health` and `@p-bot status` handlers.
   - Add `@p-bot logs [n]` and `@p-bot queue` handlers.
   - Implement admin permission validator decorator/helper (`@admin_only`).

5. **Step 5: Implement Remote Update and Restart**
   - Add `@p-bot update` and `@p-bot restart` handlers.

6. **Step 6: Implement Heartbeat & Startup Dispatcher**
   - Launch heartbeat background thread during bot initialization.
   - Post startup diagnostic card to `ADMIN_ALERT_CHANNEL`.

7. **Step 7: Update Unit & Integration Tests (`tests/`)**
   - Add unit tests for `queue_worker.py` (simulating file locks, FIFO order, and retry completion).
   - Add tests for admin authorization and health checks.

---

## 5. Verification Checklist

- [ ] Simulating lock file `~$Purchasing-Log.xlsx` queues the order, sends Slack thread notice, and finishes immediately once the lock file is removed.
- [ ] `@p-bot health` correctly detects if files exist, disk space, and process uptime.
- [ ] `@p-bot logs 20` outputs the last 20 log lines in Slack when run by an admin, and rejects unauthorized users.
- [ ] `@p-bot update` pulls latest code from git and notifies in Slack.
- [ ] On startup, an alert is posted to `ADMIN_ALERT_CHANNEL`.
