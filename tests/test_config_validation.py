from __future__ import annotations

from pathlib import Path

import pytest

from src.config import ModelSettings, Settings, validate_settings


def test_validate_settings_rejects_invalid_chat_id(tmp_path: Path) -> None:
    prompt = tmp_path / "prompt.md"
    prompt.write_text("prompt", encoding="utf-8")
    settings = Settings(
        planner_prompt_file=prompt,
        allowed_workdirs=[tmp_path],
        telegram_allowed_chat_ids=["abc-not-chat-id"],
        model=ModelSettings(provider="openai_compatible", api_base="https://example.com/v1"),
    )

    with pytest.raises(ValueError, match="Invalid SRC_TELEGRAM_ALLOWED_CHAT_IDS"):
        validate_settings(settings)


def test_validate_settings_requires_api_base_for_openai_provider(tmp_path: Path) -> None:
    prompt = tmp_path / "prompt.md"
    prompt.write_text("prompt", encoding="utf-8")
    settings = Settings(
        planner_prompt_file=prompt,
        allowed_workdirs=[tmp_path],
        model=ModelSettings(provider="openai_compatible", api_base=""),
    )

    with pytest.raises(ValueError, match="SRC_MODEL_API_BASE"):
        validate_settings(settings)
