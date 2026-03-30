"""Backward-compatible Codex backend shim."""

from __future__ import annotations

from pathlib import Path
from typing import Callable, Optional

from src.models.codex_cli_adapter import CodexCliModelAdapter
from src.models.model_adapter import ModelRequest
from src.utils.command_runner import CommandResult, CommandRunner


class CodexBackend(CodexCliModelAdapter):
    """Compatibility wrapper exposing the legacy execute_instruction method."""

    def __init__(
        self,
        codex_cli_path: str,
        command_runner: CommandRunner,
        timeout_seconds: int = 1800,
        *,
        skip_git_repo_check: bool = True,
    ) -> None:
        super().__init__(
            codex_cli_path,
            command_runner,
            model_name="codex",
            timeout_seconds=timeout_seconds,
            skip_git_repo_check=skip_git_repo_check,
        )

    def execute_instruction(
        self,
        instruction: str,
        cwd: Path | None = None,
        on_output: Optional[Callable[[str], None]] = None,
    ) -> CommandResult:
        response = self.generate(
            ModelRequest(
                prompt=instruction,
                metadata={"working_directory": str(cwd) if cwd else ""},
            ),
            on_output=on_output,
        )
        raw_payload = response.raw_payload if isinstance(response.raw_payload, dict) else {}
        return CommandResult(
            command=str(raw_payload.get("command", "")),
            returncode=int(raw_payload.get("returncode", 1)),
            stdout=str(raw_payload.get("stdout", "")),
            stderr=str(raw_payload.get("stderr", "")),
            duration_seconds=float(raw_payload.get("duration_seconds", 0.0)),
            timed_out=bool(raw_payload.get("timed_out", False)),
        )
