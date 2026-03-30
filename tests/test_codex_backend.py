from __future__ import annotations

from pathlib import Path

from src.agents.codex_backend import CodexBackend
from src.utils.command_runner import CommandResult


class RecordingRunner:
    def __init__(self) -> None:
        self.last_command: str = ""

    def run(self, command: str, cwd=None, timeout_seconds=None, env=None, on_output=None):  # noqa: ANN001, ARG002
        self.last_command = command
        return CommandResult(
            command=command,
            returncode=0,
            stdout="{}",
            stderr="",
            duration_seconds=0.01,
            timed_out=False,
        )


def test_codex_backend_shell_quotes_instruction_with_backticks() -> None:
    runner = RecordingRunner()
    backend = CodexBackend("codex", runner, timeout_seconds=30)

    backend.execute_instruction("return field `task_id` and `properties`", cwd=Path("."))

    assert runner.last_command.startswith("codex exec --skip-git-repo-check ")
    assert "'return field `task_id` and `properties`'" in runner.last_command


def test_codex_backend_shell_quotes_instruction_with_single_quote() -> None:
    runner = RecordingRunner()
    backend = CodexBackend("codex", runner, timeout_seconds=30)

    backend.execute_instruction("it's safe", cwd=Path("."))

    assert runner.last_command.startswith("codex exec --skip-git-repo-check ")
    assert "'it'\"'\"'s safe'" in runner.last_command


def test_codex_backend_can_disable_skip_git_repo_check() -> None:
    runner = RecordingRunner()
    backend = CodexBackend("codex", runner, timeout_seconds=30, skip_git_repo_check=False)

    backend.execute_instruction("hello", cwd=Path("."))

    assert runner.last_command.startswith("codex exec ")
    assert "--skip-git-repo-check" not in runner.last_command
