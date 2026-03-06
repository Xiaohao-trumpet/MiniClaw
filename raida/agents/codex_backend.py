"""Codex CLI backend implementation."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Callable, Optional

from raida.agents.agent_backend import AgentBackend
from raida.utils.command_runner import CommandResult, CommandRunner


class CodexBackend(AgentBackend):
    """Wraps Codex CLI as an AgentBackend implementation."""

    def __init__(self, codex_cli_path: str, command_runner: CommandRunner, timeout_seconds: int = 1800) -> None:
        self._codex_cli_path = codex_cli_path
        self._runner = command_runner
        self._timeout_seconds = timeout_seconds

    @property
    def name(self) -> str:
        return "codex-cli"

    def execute_instruction(
        self,
        instruction: str,
        cwd: Path | None = None,
        on_output: Optional[Callable[[str], None]] = None,
    ) -> CommandResult:
        command = subprocess.list2cmdline([self._codex_cli_path, "exec", instruction])
        return self._runner.run(
            command=command,
            cwd=cwd,
            timeout_seconds=self._timeout_seconds,
            on_output=on_output,
        )
