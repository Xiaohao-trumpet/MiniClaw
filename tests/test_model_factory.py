from __future__ import annotations

import json
from pathlib import Path

from src.config import ModelSettings, Settings
from src.models.factory import build_model_adapter
from src.models.model_adapter import ModelRequest
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


def test_factory_builds_codex_provider() -> None:
    runner = RecordingRunner()
    settings = Settings(
        allowed_workdirs=[Path.cwd()],
        model=ModelSettings(
            provider="codex_cli",
            model_name="codex-mini",
            codex_cli_path="codex",
        ),
    )

    adapter = build_model_adapter(settings, command_runner=runner)
    response = adapter.generate(ModelRequest(prompt="hello", system_prompt="system"))

    assert response.provider == "codex_cli"
    assert response.model == "codex-mini"
    assert runner.last_command.startswith("codex exec --skip-git-repo-check ")
    assert "system" in runner.last_command
    assert "hello" in runner.last_command


def test_factory_builds_openai_compatible_provider() -> None:
    captured: dict[str, object] = {}

    def transport(url: str, body: bytes, headers, timeout_seconds: int):  # noqa: ANN001
        captured["url"] = url
        captured["headers"] = dict(headers)
        captured["timeout_seconds"] = timeout_seconds
        captured["payload"] = json.loads(body.decode("utf-8"))
        return {
            "model": "kimi-k2",
            "choices": [
                {
                    "message": {"content": "ok"},
                    "finish_reason": "stop",
                }
            ],
            "usage": {
                "prompt_tokens": 3,
                "completion_tokens": 4,
                "total_tokens": 7,
            },
        }

    settings = Settings(
        allowed_workdirs=[Path.cwd()],
        model=ModelSettings(
            provider="openai_compatible",
            model_name="kimi-k2",
            api_base="https://example.com/v1",
            api_key="sk-test",
            timeout_seconds=12,
            temperature=0.2,
        ),
    )

    adapter = build_model_adapter(settings, http_transport=transport)
    response = adapter.generate(ModelRequest(prompt="hello", system_prompt="system"))

    assert response.provider == "openai_compatible"
    assert response.model == "kimi-k2"
    assert response.text == "ok"
    assert response.usage is not None
    assert response.usage.total_tokens == 7
    assert captured["url"] == "https://example.com/v1/chat/completions"
    assert captured["headers"] == {
        "Content-Type": "application/json",
        "Authorization": "Bearer sk-test",
    }
    assert captured["timeout_seconds"] == 12
    payload = captured["payload"]
    assert isinstance(payload, dict)
    assert payload["model"] == "kimi-k2"
