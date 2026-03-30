"""Factory helpers for model providers."""

from __future__ import annotations

from typing import Optional

from src.config import Settings
from src.models.codex_cli_adapter import CodexCliModelAdapter
from src.models.model_adapter import ModelAdapter
from src.models.openai_compatible_adapter import JsonTransport, OpenAICompatibleModelAdapter
from src.utils.command_runner import CommandRunner



def build_model_adapter(
    settings: Settings,
    *,
    command_runner: Optional[CommandRunner] = None,
    http_transport: JsonTransport | None = None,
) -> ModelAdapter:
    """Build the configured model provider implementation."""

    provider = settings.model.provider.strip().lower()
    if provider in {"codex", "codex_cli"}:
        if command_runner is None:
            raise ValueError("command_runner is required for codex_cli provider")
        return CodexCliModelAdapter(
            settings.model.codex_cli_path,
            command_runner,
            model_name=settings.model.model_name,
            timeout_seconds=settings.model.timeout_seconds,
            skip_git_repo_check=settings.model.codex_skip_git_repo_check,
        )
    if provider in {"openai", "openai_compatible"}:
        return OpenAICompatibleModelAdapter(
            api_base=settings.model.api_base,
            api_key=settings.model.api_key,
            model_name=settings.model.model_name,
            timeout_seconds=settings.model.timeout_seconds,
            temperature=settings.model.temperature,
            transport=http_transport,
        )
    raise ValueError(f"Unsupported model provider: {settings.model.provider}")
