"""SQLite-backed task and user state manager."""

from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

TASK_STATUSES = {
    "pending",
    "running",
    "waiting_confirmation",
    "completed",
    "failed",
    "cancelled",
}

USER_STATUSES = {
    "pending",
    "active",
    "blocked",
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class TaskManager:
    """Persistent task/user storage with lightweight state transitions."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self) -> None:
        with self._conn:
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS tasks (
                    task_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    current_step TEXT NOT NULL,
                    history TEXT NOT NULL,
                    instruction TEXT NOT NULL,
                    working_directory TEXT,
                    pending_action TEXT,
                    pending_reason TEXT
                )
                """
            )
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                    user_id TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    role TEXT NOT NULL,
                    invite_code_used TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    last_seen_at TEXT NOT NULL
                )
                """
            )
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS runtime_state (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )

    def create_task(self, user_id: str, instruction: str, working_directory: str = "") -> Dict[str, Any]:
        task_id = str(uuid.uuid4())
        now = _utc_now()
        history = [
            {
                "timestamp": now,
                "type": "instruction",
                "role": "user",
                "content": instruction,
            }
        ]

        with self._lock, self._conn:
            self._conn.execute(
                """
                INSERT INTO tasks (
                    task_id, user_id, status, created_at, updated_at,
                    current_step, history, instruction, working_directory
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    task_id,
                    user_id,
                    "pending",
                    now,
                    now,
                    "created",
                    json.dumps(history, ensure_ascii=False),
                    instruction,
                    working_directory,
                ),
            )

        return self.get_task(task_id)  # type: ignore[return-value]

    def get_task(self, task_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            row = self._conn.execute("SELECT * FROM tasks WHERE task_id = ?", (task_id,)).fetchone()
        if row is None:
            return None
        task = dict(row)
        task["history"] = json.loads(task["history"]) if task.get("history") else []
        return task

    def list_tasks(self, user_id: Optional[str] = None, limit: int = 100) -> List[Dict[str, Any]]:
        with self._lock:
            if user_id:
                rows = self._conn.execute(
                    "SELECT * FROM tasks WHERE user_id = ? ORDER BY created_at DESC LIMIT ?",
                    (user_id, limit),
                ).fetchall()
            else:
                rows = self._conn.execute(
                    "SELECT * FROM tasks ORDER BY created_at DESC LIMIT ?",
                    (limit,),
                ).fetchall()

        tasks: List[Dict[str, Any]] = []
        for row in rows:
            task = dict(row)
            task["history"] = json.loads(task["history"]) if task.get("history") else []
            tasks.append(task)
        return tasks

    def set_status(self, task_id: str, status: str, current_step: Optional[str] = None) -> None:
        if status not in TASK_STATUSES:
            raise ValueError(f"Unsupported status: {status}")
        now = _utc_now()
        with self._lock, self._conn:
            if current_step is None:
                self._conn.execute(
                    "UPDATE tasks SET status = ?, updated_at = ? WHERE task_id = ?",
                    (status, now, task_id),
                )
            else:
                self._conn.execute(
                    "UPDATE tasks SET status = ?, current_step = ?, updated_at = ? WHERE task_id = ?",
                    (status, current_step, now, task_id),
                )

    def update_current_step(self, task_id: str, current_step: str) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "UPDATE tasks SET current_step = ?, updated_at = ? WHERE task_id = ?",
                (current_step, _utc_now(), task_id),
            )

    def append_history(self, task_id: str, event: Dict[str, Any]) -> None:
        with self._lock:
            row = self._conn.execute("SELECT history FROM tasks WHERE task_id = ?", (task_id,)).fetchone()
            if row is None:
                raise KeyError(f"Task not found: {task_id}")
            history = json.loads(row["history"]) if row["history"] else []
            event.setdefault("timestamp", _utc_now())
            history.append(event)
            with self._conn:
                self._conn.execute(
                    "UPDATE tasks SET history = ?, updated_at = ? WHERE task_id = ?",
                    (json.dumps(history, ensure_ascii=False), _utc_now(), task_id),
                )

    def set_pending_confirmation(self, task_id: str, action: Dict[str, Any], reason: str) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                """
                UPDATE tasks
                SET status = ?, current_step = ?, pending_action = ?, pending_reason = ?, updated_at = ?
                WHERE task_id = ?
                """,
                (
                    "waiting_confirmation",
                    "awaiting user confirmation",
                    json.dumps(action, ensure_ascii=False),
                    reason,
                    _utc_now(),
                    task_id,
                ),
            )

    def clear_pending_confirmation(self, task_id: str) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                """
                UPDATE tasks
                SET pending_action = NULL, pending_reason = NULL, updated_at = ?
                WHERE task_id = ?
                """,
                (_utc_now(), task_id),
            )

    def get_latest_waiting_confirmation_task(self, user_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            row = self._conn.execute(
                """
                SELECT *
                FROM tasks
                WHERE user_id = ? AND status = 'waiting_confirmation'
                ORDER BY updated_at DESC
                LIMIT 1
                """,
                (user_id,),
            ).fetchone()
        if row is None:
            return None
        task = dict(row)
        task["history"] = json.loads(task["history"]) if task.get("history") else []
        return task

    def ensure_user(self, user_id: str) -> Dict[str, Any]:
        now = _utc_now()
        with self._lock:
            row = self._conn.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()
            if row is None:
                with self._conn:
                    self._conn.execute(
                        """
                        INSERT INTO users (
                            user_id, status, role, invite_code_used, created_at, updated_at, last_seen_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        (user_id, "pending", "user", None, now, now, now),
                    )
        user = self.get_user(user_id)
        if user is None:
            raise RuntimeError(f"Failed to ensure user: {user_id}")
        return user

    def get_user(self, user_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            row = self._conn.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()
        if row is None:
            return None
        return dict(row)

    def list_users(self, limit: int = 200) -> List[Dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM users ORDER BY updated_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def activate_user(self, user_id: str, invite_code_used: Optional[str] = None) -> None:
        now = _utc_now()
        with self._lock, self._conn:
            row = self._conn.execute("SELECT user_id FROM users WHERE user_id = ?", (user_id,)).fetchone()
            if row is None:
                self._conn.execute(
                    """
                    INSERT INTO users (
                        user_id, status, role, invite_code_used, created_at, updated_at, last_seen_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (user_id, "active", "user", invite_code_used, now, now, now),
                )
            else:
                self._conn.execute(
                    """
                    UPDATE users
                    SET status = ?, invite_code_used = COALESCE(?, invite_code_used), updated_at = ?, last_seen_at = ?
                    WHERE user_id = ?
                    """,
                    ("active", invite_code_used, now, now, user_id),
                )

    def set_user_status(self, user_id: str, status: str) -> None:
        if status not in USER_STATUSES:
            raise ValueError(f"Unsupported user status: {status}")
        with self._lock, self._conn:
            self._conn.execute(
                "UPDATE users SET status = ?, updated_at = ? WHERE user_id = ?",
                (status, _utc_now(), user_id),
            )

    def touch_user(self, user_id: str) -> None:
        now = _utc_now()
        with self._lock, self._conn:
            self._conn.execute(
                "UPDATE users SET last_seen_at = ?, updated_at = ? WHERE user_id = ?",
                (now, now, user_id),
            )

    def set_runtime_state(self, key: str, value: str) -> None:
        now = _utc_now()
        with self._lock, self._conn:
            self._conn.execute(
                """
                INSERT INTO runtime_state(key, value, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
                """,
                (key, value, now),
            )

    def get_runtime_state(self, key: str) -> Optional[str]:
        with self._lock:
            row = self._conn.execute("SELECT value FROM runtime_state WHERE key = ?", (key,)).fetchone()
        if row is None:
            return None
        return str(row["value"])

    def get_runtime_state_int(self, key: str) -> Optional[int]:
        raw = self.get_runtime_state(key)
        if raw is None:
            return None
        try:
            return int(raw)
        except (TypeError, ValueError):
            return None
