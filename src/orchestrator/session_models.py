"""Session and grouped-progress models."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Literal, Optional

from pydantic import BaseModel, Field


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class SessionRecord(BaseModel):
    """Persistent user session."""

    session_id: str
    user_id: str
    title: str
    status: Literal["active", "archived", "closed"] = "active"
    working_directory: str = ""
    created_at: str = Field(default_factory=_utc_now)
    updated_at: str = Field(default_factory=_utc_now)
    last_task_id: str = ""
    metadata: dict = Field(default_factory=dict)


class SessionState(BaseModel):
    """Session-scoped runtime state."""

    active_task_id: str = ""
    recent_task_ids: List[str] = Field(default_factory=list)
    last_final_answer_at: str = ""
    working_directory_override: str = ""
    memory_stub: dict = Field(default_factory=dict)


class ProgressSnapshot(BaseModel):
    """Compact execution-progress state suitable for Telegram updates."""

    task_id: str
    session_id: str = ""
    session_title: str = ""
    instruction: str = ""
    phase: Literal["created", "planning", "running", "waiting_confirmation", "completed", "failed"] = "created"
    goal: str = ""
    action_count: int = 0
    action_types: List[str] = Field(default_factory=list)
    current_action_index: int = 0
    current_action_total: int = 0
    current_action_type: str = ""
    last_status: str = ""
    last_summary: str = ""
    recent_updates: List[str] = Field(default_factory=list)
    recent_outputs: List[str] = Field(default_factory=list)
    detail_artifact_path: str = ""
    progress_message_id: Optional[int] = None
    final_answer_sent: bool = False
    updated_at: str = Field(default_factory=_utc_now)
