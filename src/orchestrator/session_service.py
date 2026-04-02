"""Session-oriented orchestration helpers."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from src.orchestrator.context_store import ContextStore
from src.orchestrator.task_manager import TaskManager
from src.utils.path_utils import find_project_root


def _derive_title(text: str) -> str:
    value = " ".join(text.strip().split())
    if not value:
        return "New session"
    if len(value) <= 60:
        return value
    return value[:57].rstrip() + "..."


def _derive_project_key(working_directory: str) -> str:
    raw = working_directory.strip()
    if not raw:
        return ""
    resolved = Path(raw).resolve()
    project_root = find_project_root(resolved)
    return str((project_root or resolved).resolve())


class SessionService:
    """High-level session helpers built on top of TaskManager and ContextStore."""

    def __init__(self, task_manager: TaskManager, context_store: ContextStore, *, auto_create_on_run: bool = True) -> None:
        self.task_manager = task_manager
        self.context_store = context_store
        self.auto_create_on_run = auto_create_on_run

    def create_session(
        self,
        user_id: str,
        *,
        title: str = "",
        alias: str = "",
        working_directory: str = "",
        activate: bool = True,
    ) -> Dict[str, Any]:
        session = self.task_manager.create_session(
            user_id=user_id,
            title=title.strip() or "New session",
            alias=alias.strip() or title.strip(),
            working_directory=working_directory,
            project_key=_derive_project_key(working_directory),
            activate=activate,
        )
        self.context_store.init_session_context(str(session["session_id"]))
        return session

    def get_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        return self.task_manager.get_session(session_id)

    def list_sessions(self, user_id: str, limit: int = 50) -> List[Dict[str, Any]]:
        return self.task_manager.list_sessions(user_id=user_id, limit=limit)

    def get_active_session(self, user_id: str) -> Optional[Dict[str, Any]]:
        return self.task_manager.get_active_session(user_id)

    def ensure_active_session(
        self,
        user_id: str,
        *,
        working_directory: str = "",
        title_hint: str = "",
    ) -> Optional[Dict[str, Any]]:
        active = self.task_manager.get_active_session(user_id)
        if active:
            return active
        if not self.auto_create_on_run:
            return None
        return self.create_session(
            user_id,
            title="Main",
            alias="main",
            working_directory=working_directory,
            activate=True,
        )

    def resolve_session(self, user_id: str, session_ref: str) -> Optional[Dict[str, Any]]:
        token = session_ref.strip()
        if not token:
            return None
        session = self.task_manager.get_session(token)
        if session is None:
            session = self.task_manager.get_session_by_alias(user_id, token)
        if session is None or str(session.get("user_id")) != user_id:
            return None
        return session

    def use_session(self, user_id: str, session_ref: str) -> Optional[Dict[str, Any]]:
        session = self.resolve_session(user_id, session_ref)
        if session is None or str(session.get("user_id")) != user_id:
            return None
        self.task_manager.set_active_session(user_id, str(session["session_id"]))
        return self.task_manager.get_session(str(session["session_id"]))

    def record_user_turn(self, session_id: str, task_id: str, content: str, *, message_type: str = "user_turn") -> None:
        if not session_id.strip() or not content.strip():
            return
        self.context_store.append_session_conversation(
            session_id,
            "user",
            content,
            task_id=task_id,
            message_type=message_type,
        )

    def record_assistant_turn(
        self,
        session_id: str,
        task_id: str,
        content: str,
        *,
        message_type: str = "assistant_turn",
    ) -> None:
        if not session_id.strip() or not content.strip():
            return
        self.context_store.append_session_conversation(
            session_id,
            "assistant",
            content,
            task_id=task_id,
            message_type=message_type,
        )

    def load_recent_conversation(
        self,
        session_id: str,
        *,
        limit: int,
        exclude_task_id: str = "",
    ) -> List[Dict[str, Any]]:
        return self.context_store.load_recent_session_conversation(
            session_id,
            limit=limit,
            exclude_task_id=exclude_task_id,
        )
