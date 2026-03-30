"""Codex CLI provider implementation."""

from __future__ import annotations

import os
import shlex
import subprocess
from pathlib import Path
from typing import Callable, Optional

from src.models.model_adapter import ModelAdapter, ModelRequest, ModelResponse
from src.utils.command_runner import CommandRunner


class CodexCliModelAdapter(ModelAdapter):
    """Wraps Codex CLI behind the provider-agnostic model interface."""

    def __init__(
        self,
        codex_cli_path: str,
        command_runner: CommandRunner,
        *,
        model_name: str = "codex",
        timeout_seconds: int = 1800,
        skip_git_repo_check: bool = True,
    ) -> None:
        self._codex_cli_path = codex_cli_path
        self._runner = command_runner
        self._configured_model_name = model_name
        self._timeout_seconds = timeout_seconds
        self._skip_git_repo_check = skip_git_repo_check

    @property
    def provider_name(self) -> str:
        return "codex_cli"

    @property
    def model_name(self) -> str:
        return self._configured_model_name

    def generate(
        self,
        request: ModelRequest,
        on_output: Optional[Callable[[str], None]] = None,
    ) -> ModelResponse:
        argv = [self._codex_cli_path, "exec"]
        if self._skip_git_repo_check:
            argv.append("--skip-git-repo-check")
        argv.append(self._build_instruction(request))

        command = subprocess.list2cmdline(argv) if os.name == "nt" else shlex.join(argv)
        raw_working_directory = str(request.metadata.get("working_directory", "")).strip()
        working_directory = Path(raw_working_directory).resolve() if raw_working_directory else None
        result = self._runner.run(
            command=command,
            cwd=working_directory,
            timeout_seconds=request.options.timeout_seconds or self._timeout_seconds,
            on_output=on_output,
        )

        text = (result.stdout or result.stderr or "").strip()
        finish_reason = "timeout" if result.timed_out else ("stop" if result.success else "error")
        raw_payload = {
            "command": command,
            "returncode": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "duration_seconds": result.duration_seconds,
            "timed_out": result.timed_out,
            "working_directory": str(working_directory) if working_directory else "",
        }
        return ModelResponse(
            text=text,
            raw_payload=raw_payload,
            usage=None,
            finish_reason=finish_reason,
            provider=self.provider_name,
            model=self.model_name,
        )

    @staticmethod
    def _build_instruction(request: ModelRequest) -> str:
        if request.system_prompt.strip():
            return f"{request.system_prompt.strip()}\n\n{request.prompt.strip()}".strip()
        return request.prompt.strip()
