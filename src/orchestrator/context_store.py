"""File-based runtime context for each task."""

from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List


def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


class ContextStore:
    """Stores artifacts under data/tasks/{task_id}/."""

    def __init__(self, base_dir: Path) -> None:
        self.base_dir = base_dir
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def task_dir(self, task_id: str) -> Path:
        return self.base_dir / task_id

    def init_task_context(self, task_id: str) -> Path:
        task_dir = self.task_dir(task_id)
        (task_dir / "logs").mkdir(parents=True, exist_ok=True)
        (task_dir / "screenshots").mkdir(parents=True, exist_ok=True)
        (task_dir / "patches").mkdir(parents=True, exist_ok=True)
        return task_dir

    def artifact_path(self, task_id: str, name: str) -> Path:
        self.init_task_context(task_id)
        return self.task_dir(task_id) / name

    def conversation_file(self, task_id: str) -> Path:
        return self.task_dir(task_id) / "conversation.jsonl"

    def state_file(self, task_id: str) -> Path:
        return self.task_dir(task_id) / "state.json"

    def append_conversation(self, task_id: str, role: str, content: str) -> None:
        self.init_task_context(task_id)
        line = json.dumps(
            {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "role": role,
                "content": content,
            },
            ensure_ascii=False,
        )
        with self.conversation_file(task_id).open("a", encoding="utf-8") as f:
            f.write(line + "\n")

    def append_log(self, task_id: str, log_name: str, text: str) -> Path:
        self.init_task_context(task_id)
        log_path = self.task_dir(task_id) / "logs" / log_name
        with log_path.open("a", encoding="utf-8") as f:
            f.write(text.rstrip("\n") + "\n")
        return log_path

    def write_log(self, task_id: str, log_name: str, text: str) -> Path:
        self.init_task_context(task_id)
        log_path = self.task_dir(task_id) / "logs" / log_name
        with log_path.open("w", encoding="utf-8") as f:
            f.write(text)
        return log_path

    def save_screenshot(self, task_id: str, image_path: Path) -> Path:
        self.init_task_context(task_id)
        target = self.task_dir(task_id) / "screenshots" / f"{_timestamp()}_{image_path.name}"
        shutil.copy(image_path, target)
        return target

    def save_patch(self, task_id: str, patch_text: str) -> Path:
        self.init_task_context(task_id)
        patch_path = self.task_dir(task_id) / "patches" / f"{_timestamp()}.diff"
        with patch_path.open("w", encoding="utf-8") as f:
            f.write(patch_text)
        return patch_path

    def write_json_artifact(self, task_id: str, name: str, payload: Any) -> Path:
        target = self.artifact_path(task_id, name)
        with target.open("w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        return target

    def write_text_artifact(self, task_id: str, name: str, text: str) -> Path:
        target = self.artifact_path(task_id, name)
        target.write_text(text, encoding="utf-8")
        return target

    def load_json_artifact(self, task_id: str, name: str, default: Any) -> Any:
        target = self.artifact_path(task_id, name)
        if not target.exists():
            return default
        with target.open("r", encoding="utf-8") as f:
            return json.load(f)

    def append_execution_record(self, task_id: str, record: Dict[str, Any]) -> Path:
        current = self.load_json_artifact(task_id, "execution_log.json", default=[])
        if not isinstance(current, list):
            current = []
        current.append(record)
        return self.write_json_artifact(task_id, "execution_log.json", current)

    def load_state(self, task_id: str) -> Dict[str, Any]:
        self.init_task_context(task_id)
        path = self.state_file(task_id)
        if not path.exists():
            return {
                "actions": [],
                "cursor": 0,
                "cancel_requested": False,
                "pause_requested": False,
                "confirmation_granted_for_cursor": None,
                "pending_instructions": [],
                "working_directory": "",
            }
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)

    def save_state(self, task_id: str, state: Dict[str, Any]) -> None:
        self.init_task_context(task_id)
        with self.state_file(task_id).open("w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)

    def list_artifacts(self, task_id: str) -> List[Path]:
        self.init_task_context(task_id)
        artifacts: List[Path] = []
        for child in self.task_dir(task_id).rglob("*"):
            if child.is_file():
                artifacts.append(child)
        return sorted(artifacts)
