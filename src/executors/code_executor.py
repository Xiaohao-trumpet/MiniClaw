"""Executor for coding and terminal-based development tasks."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Callable, Dict, List, Optional

from src.agents.agent_backend import AgentBackend
from src.config import Settings
from src.utils.command_runner import CommandResult, CommandRunner
from src.utils.logger import get_logger

logger = get_logger(__name__)


class CodeExecutor:
    """Runs development operations and Codex-assisted tasks."""

    def __init__(
        self,
        settings: Settings,
        command_runner: CommandRunner,
        agent_backend: AgentBackend,
    ) -> None:
        self.settings = settings
        self.command_runner = command_runner
        self.agent_backend = agent_backend

    def execute(
        self,
        action: Dict[str, object],
        working_directory: Path | None,
        on_output: Optional[Callable[[str], None]] = None,
    ) -> Dict[str, object]:
        action_type = str(action.get("type", ""))
        try:
            if action_type == "run_command":
                command = str(action["command"])
                result = self._run_command(command, working_directory, on_output)
                return self._to_response(result, summary=f"Command finished: {command}")

            if action_type == "git_pull":
                result = self._run_command("git pull", working_directory, on_output)
                return self._to_response(result, summary="Git pull completed.")

            if action_type == "install_dependencies":
                result = self._run_command("pip install -r requirements.txt", working_directory, on_output)
                return self._to_response(result, summary="Dependency installation completed.")

            if action_type == "run_tests":
                result = self._run_command("pytest -q", working_directory, on_output)
                summary = "Tests passed." if result.success else "Tests failed."
                return self._to_response(result, summary=summary)

            if action_type == "codex_exec":
                instruction = str(action["instruction"])
                result = self.agent_backend.execute_instruction(instruction, cwd=working_directory, on_output=on_output)
                return self._to_response(
                    result,
                    summary=f"{self.agent_backend.name} execution completed.",
                )

            if action_type == "analyze_logs":
                logs = str(action.get("logs", ""))
                analysis = self._quick_log_analysis(logs)
                return {
                    "success": True,
                    "summary": "Generated log analysis.",
                    "output": analysis,
                    "artifacts": [],
                }

            return {
                "success": False,
                "summary": f"Unsupported code action: {action_type}",
                "output": "",
                "artifacts": [],
            }
        except Exception as exc:  # pragma: no cover - defensive catch for external tools
            logger.exception("Code execution failed: %s", exc)
            return {
                "success": False,
                "summary": f"Code execution failed: {exc}",
                "output": "",
                "artifacts": [],
            }

    def _run_command(
        self,
        command: str,
        working_directory: Path | None,
        on_output: Optional[Callable[[str], None]] = None,
    ) -> CommandResult:
        safe_cwd = self._sanitize_working_directory(working_directory)
        return self.command_runner.run(
            command=command,
            cwd=safe_cwd,
            timeout_seconds=self.settings.command_timeout_seconds,
            on_output=on_output,
        )

    def _sanitize_working_directory(self, working_directory: Path | None) -> Path | None:
        if working_directory is None:
            return None
        resolved = working_directory.resolve()
        for allowed in self.settings.allowed_workdirs:
            if resolved == allowed.resolve() or str(resolved).startswith(str(allowed.resolve())):
                return resolved
        raise PermissionError(f"Working directory not allowed: {resolved}")

    @staticmethod
    def _to_response(result: CommandResult, summary: str) -> Dict[str, object]:
        output = result.stdout if result.stdout else result.stderr
        return {
            "success": result.success,
            "summary": summary,
            "output": output,
            "metadata": {
                "returncode": result.returncode,
                "duration_seconds": round(result.duration_seconds, 2),
                "timed_out": result.timed_out,
            },
            "artifacts": [],
        }

    @staticmethod
    def _quick_log_analysis(logs: str) -> str:
        lowered = logs.lower()
        findings: List[str] = []
        if "traceback" in lowered:
            findings.append("Detected Python traceback. Start by checking the first exception in stack trace.")
        if "module not found" in lowered or "modulenotfounderror" in lowered:
            findings.append("Dependency issue detected. Verify virtualenv and install missing package.")
        if "permission denied" in lowered:
            findings.append("Permission issue detected. Check file ownership and execute permissions.")
        if "failed" in lowered and not findings:
            findings.append("General failure detected. Inspect the first failure block.")
        if not findings:
            findings.append("No obvious failure signature detected; inspect complete logs.")
        return json.dumps({"findings": findings}, ensure_ascii=False, indent=2)

