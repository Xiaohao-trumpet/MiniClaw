import json
import sqlite3

from src.orchestrator.task_manager import TaskManager


def test_task_manager_creates_and_switches_sessions(tmp_path) -> None:  # noqa: ANN001
    manager = TaskManager(tmp_path / "src.db")
    manager.activate_user("tg_1")

    session_a = manager.create_session("tg_1", title="Session A", working_directory=str(tmp_path), activate=True)
    session_b = manager.create_session("tg_1", title="Session B", working_directory=str(tmp_path), activate=False)

    manager.set_active_session("tg_1", str(session_b["session_id"]))
    active = manager.get_active_session("tg_1")

    assert active is not None
    assert active["session_id"] == session_b["session_id"]
    assert len(manager.list_sessions("tg_1")) == 2

    task = manager.create_task("tg_1", "inspect repo", working_directory=str(tmp_path), session_id=str(session_b["session_id"]))
    assert task["session_id"] == session_b["session_id"]


def test_task_manager_migrates_legacy_tasks_into_sessions(tmp_path) -> None:  # noqa: ANN001
    db_path = tmp_path / "legacy.db"
    conn = sqlite3.connect(db_path)
    with conn:
        conn.execute(
            """
            CREATE TABLE tasks (
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
        conn.execute(
            """
            CREATE TABLE users (
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
        conn.execute(
            """
            CREATE TABLE runtime_state (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            INSERT INTO users (user_id, status, role, invite_code_used, created_at, updated_at, last_seen_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            ("tg_1", "active", "user", None, "2026-03-30T00:00:00+00:00", "2026-03-30T00:00:00+00:00", "2026-03-30T00:00:00+00:00"),
        )
        conn.execute(
            """
            INSERT INTO tasks (task_id, user_id, status, created_at, updated_at, current_step, history, instruction, working_directory)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "task-legacy",
                "tg_1",
                "completed",
                "2026-03-30T00:00:00+00:00",
                "2026-03-30T00:05:00+00:00",
                "done",
                json.dumps([]),
                "legacy task",
                str(tmp_path),
            ),
        )
    conn.close()

    manager = TaskManager(db_path)
    task = manager.get_task("task-legacy")
    sessions = manager.list_sessions("tg_1")
    user = manager.get_user("tg_1")

    assert task is not None
    assert task["session_id"]
    assert len(sessions) == 1
    assert user is not None
    assert user["active_session_id"] == sessions[0]["session_id"]
