"""Session-oriented orchestration helpers."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from src.orchestrator.context_store import ContextStore
from src.orchestrator.task_manager import TaskManager


def _derive_title(text: str) -> str:
    value = " ".join(text.strip().split())
    if not value:
        return "New session"
    if len(value) <= 60:
        return value
    return value[:57].rstrip() + "..."


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
        working_directory: str = "",
        activate: bool = True,
    ) -> Dict[str, Any]:
        session = self.task_manager.create_session(
            user_id=user_id,
            title=title.strip() or "New session",
            working_directory=working_directory,
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
            title=_derive_title(title_hint),
            working_directory=working_directory,
            activate=True,
        )

    def use_session(self, user_id: str, session_id: str) -> Optional[Dict[str, Any]]:
        session = self.task_manager.get_session(session_id)
        if session is None or str(session.get("user_id")) != user_id:
            return None
        self.task_manager.set_active_session(user_id, session_id)
        return self.task_manager.get_session(session_id)

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
