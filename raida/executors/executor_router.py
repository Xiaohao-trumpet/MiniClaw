"""Action planner and executor router."""

from __future__ import annotations

import re
from typing import Dict, List

from raida.executors.code_executor import CodeExecutor
from raida.executors.desktop_executor import DesktopExecutor


class ExecutorRouter:
    """Plans high-level actions and routes each one to the right executor."""

    def __init__(self, code_executor: CodeExecutor, desktop_executor: DesktopExecutor) -> None:
        self.code_executor = code_executor
        self.desktop_executor = desktop_executor

    def plan_actions(self, instruction: str) -> List[Dict[str, object]]:
        lowered = instruction.lower()
        actions: List[Dict[str, object]] = []

        if "pull latest code" in lowered or ("git" in lowered and "pull" in lowered):
            actions.append({"type": "git_pull"})

        if "install dependencies" in lowered or "pip install" in lowered:
            actions.append({"type": "install_dependencies"})

        if "run tests" in lowered or "pytest" in lowered:
            actions.append({"type": "run_tests"})

        if "open ide" in lowered or "open vscode" in lowered:
            actions.append({"type": "open_application", "name": "code"})

        if "open browser" in lowered:
            actions.append({"type": "open_application", "name": "msedge"})

        if "screenshot" in lowered:
            actions.append({"type": "take_screenshot"})

        url_match = re.search(r"(https?://[^\s]+)", instruction)
        if url_match:
            actions.append({"type": "open_url", "url": url_match.group(1)})

        # If no deterministic action matched, delegate entire instruction to Codex.
        if not actions:
            actions.append({"type": "codex_exec", "instruction": instruction})
        else:
            # Add Codex summarization so user receives concise diagnostics after execution.
            actions.append(
                {
                    "type": "codex_exec",
                    "instruction": (
                        "Summarize the execution results, identify failures, and suggest concrete next steps."
                    ),
                }
            )
        return actions

    def execute_action(
        self,
        action: Dict[str, object],
        working_directory,
        on_output=None,
    ) -> Dict[str, object]:
        action_type = str(action.get("type", ""))
        if action_type in {"run_command", "git_pull", "install_dependencies", "run_tests", "codex_exec", "analyze_logs"}:
            return self.code_executor.execute(action, working_directory=working_directory, on_output=on_output)
        return self.desktop_executor.execute(action)

