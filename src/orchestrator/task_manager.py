"""SQLite-backed task, session, and user state manager."""

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
    "planning",
    "running",
    "awaiting_confirmation",
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

SESSION_STATUSES = {
    "active",
    "archived",
    "closed",
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _derive_session_title(text: str) -> str:
    value = " ".join(str(text).strip().split())
    if not value:
        return "New session"
    if len(value) <= 60:
        return value
    return value[:57].rstrip() + "..."


class TaskManager:
    """Persistent task/session/user storage with lightweight state transitions."""

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
                CREATE TABLE IF NOT EXISTS sessions (
                    session_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    status TEXT NOT NULL,
                    working_directory TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    last_task_id TEXT,
                    metadata TEXT NOT NULL
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
        self._ensure_column("tasks", "session_id", "TEXT")
        self._ensure_column("users", "active_session_id", "TEXT")
        with self._conn:
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_tasks_user_created_at ON tasks(user_id, created_at DESC)"
            )
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_tasks_session_created_at ON tasks(session_id, created_at DESC)"
            )
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_sessions_user_updated_at ON sessions(user_id, updated_at DESC)"
            )
        self._migrate_legacy_tasks_to_sessions()

    def _column_exists(self, table: str, column: str) -> bool:
        rows = self._conn.execute(f"PRAGMA table_info({table})").fetchall()
        return any(str(row["name"]) == column for row in rows)

    def _ensure_column(self, table: str, column: str, column_type: str) -> None:
        if self._column_exists(table, column):
            return
        with self._conn:
            self._conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {column_type}")

    def _migrate_legacy_tasks_to_sessions(self) -> None:
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT task_id, user_id, instruction, working_directory, created_at, updated_at
                FROM tasks
                WHERE session_id IS NULL OR session_id = ''
                ORDER BY created_at ASC
                """
            ).fetchall()
            if not rows:
                self._ensure_active_sessions_for_users()
                return

            with self._conn:
                for row in rows:
                    task_id = str(row["task_id"])
                    user_id = str(row["user_id"])
                    session_id = str(uuid.uuid4())
                    created_at = str(row["created_at"])
                    updated_at = str(row["updated_at"])
                    title = _derive_session_title(str(row["instruction"]))
                    self._conn.execute(
                        """
                        INSERT OR IGNORE INTO sessions (
                            session_id, user_id, title, status, working_directory,
                            created_at, updated_at, last_task_id, metadata
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            session_id,
                            user_id,
                            title,
                            "active",
                            str(row["working_directory"] or ""),
                            created_at,
                            updated_at,
                            task_id,
                            json.dumps({"migrated_from_legacy_task": True}, ensure_ascii=False),
                        ),
                    )
                    self._conn.execute(
                        "UPDATE tasks SET session_id = ?, updated_at = ? WHERE task_id = ?",
                        (session_id, updated_at, task_id),
                    )
            self._ensure_active_sessions_for_users()

    def _ensure_active_sessions_for_users(self) -> None:
        rows = self._conn.execute("SELECT user_id, active_session_id FROM users").fetchall()
        with self._conn:
            for row in rows:
                user_id = str(row["user_id"])
                active_session_id = str(row["active_session_id"] or "")
                if active_session_id:
                    continue
                session = self._conn.execute(
                    """
                    SELECT session_id
                    FROM sessions
                    WHERE user_id = ?
                    ORDER BY updated_at DESC
                    LIMIT 1
                    """,
                    (user_id,),
                ).fetchone()
                if session is None:
                    continue
                self._conn.execute(
                    "UPDATE users SET active_session_id = ?, updated_at = ? WHERE user_id = ?",
                    (str(session["session_id"]), _utc_now(), user_id),
                )

    @staticmethod
    def _normalize_task(row: sqlite3.Row) -> Dict[str, Any]:
        task = dict(row)
        task["history"] = json.loads(task["history"]) if task.get("history") else []
        return task

    @staticmethod
    def _normalize_session(row: sqlite3.Row) -> Dict[str, Any]:
        session = dict(row)
        session["metadata"] = json.loads(session["metadata"]) if session.get("metadata") else {}
        return session

    def create_session(
        self,
        user_id: str,
        *,
        title: str,
        working_directory: str = "",
        activate: bool = True,
        status: str = "active",
    ) -> Dict[str, Any]:
        if status not in SESSION_STATUSES:
            raise ValueError(f"Unsupported session status: {status}")
        self.ensure_user(user_id)
        session_id = str(uuid.uuid4())
        now = _utc_now()
        with self._lock, self._conn:
            self._conn.execute(
                """
                INSERT INTO sessions (
                    session_id, user_id, title, status, working_directory,
                    created_at, updated_at, last_task_id, metadata
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session_id,
                    user_id,
                    title.strip() or "New session",
                    status,
                    working_directory,
                    now,
                    now,
                    "",
                    json.dumps({}, ensure_ascii=False),
                ),
            )
            if activate:
                self._conn.execute(
                    "UPDATE users SET active_session_id = ?, updated_at = ? WHERE user_id = ?",
                    (session_id, now, user_id),
                )
        return self.get_session(session_id)  # type: ignore[return-value]

    def get_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            row = self._conn.execute("SELECT * FROM sessions WHERE session_id = ?", (session_id,)).fetchone()
        if row is None:
            return None
        return self._normalize_session(row)

    def list_sessions(self, user_id: str, limit: int = 100) -> List[Dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT * FROM sessions
                WHERE user_id = ?
                ORDER BY updated_at DESC
                LIMIT ?
                """,
                (user_id, limit),
            ).fetchall()
        return [self._normalize_session(row) for row in rows]

    def update_session(
        self,
        session_id: str,
        *,
        title: Optional[str] = None,
        status: Optional[str] = None,
        working_directory: Optional[str] = None,
        last_task_id: Optional[str] = None,
    ) -> None:
        if status is not None and status not in SESSION_STATUSES:
            raise ValueError(f"Unsupported session status: {status}")
        fields: List[str] = []
        params: List[Any] = []
        if title is not None:
            fields.append("title = ?")
            params.append(title.strip() or "New session")
        if status is not None:
            fields.append("status = ?")
            params.append(status)
        if working_directory is not None:
            fields.append("working_directory = ?")
            params.append(working_directory)
        if last_task_id is not None:
            fields.append("last_task_id = ?")
            params.append(last_task_id)
        fields.append("updated_at = ?")
        params.append(_utc_now())
        params.append(session_id)
        with self._lock, self._conn:
            self._conn.execute(
                f"UPDATE sessions SET {', '.join(fields)} WHERE session_id = ?",
                tuple(params),
            )

    def touch_session(self, session_id: str, *, last_task_id: str = "") -> None:
        self.update_session(session_id, last_task_id=last_task_id if last_task_id else None)

    def set_active_session(self, user_id: str, session_id: str) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "UPDATE users SET active_session_id = ?, updated_at = ? WHERE user_id = ?",
                (session_id, _utc_now(), user_id),
            )
        self.touch_user(user_id)

    def get_active_session(self, user_id: str) -> Optional[Dict[str, Any]]:
        user = self.get_user(user_id)
        active_session_id = str(user.get("active_session_id", "") if user else "")
        if active_session_id:
            session = self.get_session(active_session_id)
            if session is not None:
                return session
        sessions = self.list_sessions(user_id=user_id, limit=1)
        if sessions:
            self.set_active_session(user_id, str(sessions[0]["session_id"]))
            return self.get_session(str(sessions[0]["session_id"]))
        return None

    def create_task(
        self,
        user_id: str,
        instruction: str,
        working_directory: str = "",
        *,
        session_id: str = "",
    ) -> Dict[str, Any]:
        self.ensure_user(user_id)
        resolved_session_id = session_id.strip()
        if not resolved_session_id:
            active_session = self.get_active_session(user_id)
            if active_session is None:
                active_session = self.create_session(
                    user_id,
                    title=_derive_session_title(instruction),
                    working_directory=working_directory,
                    activate=True,
                )
            resolved_session_id = str(active_session["session_id"])
        else:
            session = self.get_session(resolved_session_id)
            if session is None:
                session = self.create_session(
                    user_id,
                    title=_derive_session_title(instruction),
                    working_directory=working_directory,
                    activate=True,
                )
                resolved_session_id = str(session["session_id"])
            elif str(session.get("user_id")) == user_id:
                self.set_active_session(user_id, resolved_session_id)
            else:
                session = self.create_session(
                    user_id,
                    title=_derive_session_title(instruction),
                    working_directory=working_directory,
                    activate=True,
                )
                resolved_session_id = str(session["session_id"])

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
                    task_id, user_id, session_id, status, created_at, updated_at,
                    current_step, history, instruction, working_directory
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    task_id,
                    user_id,
                    resolved_session_id,
                    "pending",
                    now,
                    now,
                    "created",
                    json.dumps(history, ensure_ascii=False),
                    instruction,
                    working_directory,
                ),
            )
            self._conn.execute(
                "UPDATE sessions SET last_task_id = ?, updated_at = ? WHERE session_id = ?",
                (task_id, now, resolved_session_id),
            )
            self._conn.execute(
                "UPDATE users SET active_session_id = ?, updated_at = ?, last_seen_at = ? WHERE user_id = ?",
                (resolved_session_id, now, now, user_id),
            )

        return self.get_task(task_id)  # type: ignore[return-value]

    def get_task(self, task_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            row = self._conn.execute("SELECT * FROM tasks WHERE task_id = ?", (task_id,)).fetchone()
        if row is None:
            return None
        return self._normalize_task(row)

    def list_tasks(
        self,
        user_id: Optional[str] = None,
        session_id: str = "",
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        query = "SELECT * FROM tasks"
        clauses: List[str] = []
        params: List[Any] = []
        if user_id:
            clauses.append("user_id = ?")
            params.append(user_id)
        if session_id.strip():
            clauses.append("session_id = ?")
            params.append(session_id.strip())
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        with self._lock:
            rows = self._conn.execute(query, tuple(params)).fetchall()
        return [self._normalize_task(row) for row in rows]

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
                    "awaiting_confirmation",
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

    def get_latest_waiting_confirmation_task(self, user_id: str, session_id: str = "") -> Optional[Dict[str, Any]]:
        query = """
            SELECT *
            FROM tasks
            WHERE user_id = ? AND status IN ('awaiting_confirmation', 'waiting_confirmation')
        """
        params: List[Any] = [user_id]
        if session_id.strip():
            query += " AND session_id = ?"
            params.append(session_id.strip())
        query += " ORDER BY updated_at DESC LIMIT 1"
        with self._lock:
            row = self._conn.execute(query, tuple(params)).fetchone()
        if row is None:
            return None
        return self._normalize_task(row)

    def get_waiting_confirmation_task(self, user_id: str, task_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            row = self._conn.execute(
                """
                SELECT *
                FROM tasks
                WHERE user_id = ? AND task_id = ? AND status IN ('awaiting_confirmation', 'waiting_confirmation')
                LIMIT 1
                """,
                (user_id, task_id),
            ).fetchone()
        if row is None:
            return None
        return self._normalize_task(row)

    def ensure_user(self, user_id: str) -> Dict[str, Any]:
        now = _utc_now()
        with self._lock:
            row = self._conn.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()
            if row is None:
                with self._conn:
                    self._conn.execute(
                        """
                        INSERT INTO users (
                            user_id, status, role, invite_code_used, created_at, updated_at, last_seen_at, active_session_id
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (user_id, "pending", "user", None, now, now, now, ""),
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
                        user_id, status, role, invite_code_used, created_at, updated_at, last_seen_at, active_session_id
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (user_id, "active", "user", invite_code_used, now, now, now, ""),
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
