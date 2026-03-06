"""Executor router that dispatches planned actions to executors."""

from __future__ import annotations

from pathlib import Path
from typing import Callable, Dict, Optional

from raida.executors.desktop_executor import DesktopExecutor
from raida.executors.system_executor import SystemExecutor


class ExecutorRouter:
    """Routes each structured action to system or desktop executor."""

    DESKTOP_ACTIONS = {
        "open_application",
        "open_url",
        "take_screenshot",
        "focus_window",
        "type_text",
        "press_key",
        "mouse_click",
    }

    SYSTEM_ACTIONS = {
        "run_command",
        "list_directory",
        "read_file",
        "write_file",
        "request_confirmation",
        "respond_only",
    }

    def __init__(self, system_executor: SystemExecutor, desktop_executor: DesktopExecutor) -> None:
        self.system_executor = system_executor
        self.desktop_executor = desktop_executor

    def execute_action(
        self,
        action: Dict[str, object],
        working_directory: Path | None,
        task_dir: Path,
        on_output: Optional[Callable[[str], None]] = None,
    ) -> Dict[str, object]:
        action_type = str(action.get("action_type", ""))
        if action_type in self.DESKTOP_ACTIONS:
            return self.desktop_executor.execute(action, task_dir=task_dir)
        if action_type in self.SYSTEM_ACTIONS:
            return self.system_executor.execute(
                action=action,
                working_directory=working_directory,
                task_dir=task_dir,
                on_output=on_output,
            )
        return {
            "success": False,
            "status": "failed",
            "summary": f"Unsupported action_type: {action_type}",
            "output": "",
            "artifacts": [],
            "metadata": {},
        }

