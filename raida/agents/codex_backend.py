"""Codex CLI backend implementation."""

from __future__ import annotations

import os
import shlex
import subprocess
from pathlib import Path
from typing import Callable, Optional

from raida.agents.agent_backend import AgentBackend
from raida.utils.command_runner import CommandResult, CommandRunner


class CodexBackend(AgentBackend):
    """Wraps Codex CLI as an AgentBackend implementation."""

    def __init__(
        self,
        codex_cli_path: str,
        command_runner: CommandRunner,
        timeout_seconds: int = 1800,
        *,
        skip_git_repo_check: bool = True,
    ) -> None:
        self._codex_cli_path = codex_cli_path
        self._runner = command_runner
        self._timeout_seconds = timeout_seconds
        self._skip_git_repo_check = skip_git_repo_check

    @property
    def name(self) -> str:
        return "codex-cli"

    def execute_instruction(
        self,
        instruction: str,
        cwd: Path | None = None,
        on_output: Optional[Callable[[str], None]] = None,
    ) -> CommandResult:
        argv = [self._codex_cli_path, "exec"]
        if self._skip_git_repo_check:
            argv.append("--skip-git-repo-check")
        argv.append(instruction)
        command = subprocess.list2cmdline(argv) if os.name == "nt" else shlex.join(argv)
        return self._runner.run(
            command=command,
            cwd=cwd,
            timeout_seconds=self._timeout_seconds,
            on_output=on_output,
        )
