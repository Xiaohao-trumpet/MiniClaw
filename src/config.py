"""Application configuration for MiniClaw."""

from __future__ import annotations

import os
import shutil
from functools import lru_cache
from pathlib import Path
from typing import List

from pydantic import BaseModel, Field


class ModelSettings(BaseModel):
    """Config for the pluggable model provider layer."""

    provider: str = "codex_cli"
    model_name: str = "codex"
    api_base: str = ""
    api_key: str = ""
    timeout_seconds: int = 1800
    temperature: float = 0.0
    codex_cli_path: str = "codex"
    codex_skip_git_repo_check: bool = True


class Settings(BaseModel):
    """Runtime settings loaded from environment variables."""

    app_name: str = "Remote AI Developer Agent"
    host: str = Field(default="0.0.0.0")
    port: int = Field(default=8000)

    database_path: Path = Field(default=Path("data/src.db"))
    task_data_dir: Path = Field(default=Path("data/tasks"))
    planner_prompt_file: Path = Field(default=Path("prompts/action_planner.md"))
    allowed_workdirs: List[Path] = Field(default_factory=lambda: [Path.cwd()])

    model: ModelSettings = Field(default_factory=ModelSettings)
    command_timeout_seconds: int = 1800
    shell_executable: str = ""
    log_level: str = "INFO"

    require_confirmation_for_network: bool = True
    require_confirmation_for_overwrite: bool = True

    telegram_bot_token: str = ""
    telegram_allowed_chat_ids: List[str] = Field(default_factory=list)
    telegram_invite_code: str = ""
    telegram_require_registration: bool = True
    telegram_poll_timeout_seconds: int = 30
    telegram_poll_retry_seconds: int = 3


def _parse_allowed_workdirs(raw: str | None) -> List[Path]:
    if not raw:
        return [Path.cwd()]
    return [Path(item.strip()).expanduser().resolve() for item in raw.split(",") if item.strip()]


def _parse_string_list(raw: str | None) -> List[str]:
    if not raw:
        return []
    return [item.strip() for item in raw.split(",") if item.strip()]


def _default_shell_executable() -> str:
    if os.name == "nt":
        return os.getenv("COMSPEC", "cmd.exe")
    for candidate in ("bash", "zsh", "sh"):
        resolved = shutil.which(candidate)
        if resolved:
            return resolved
    return "/bin/sh"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Build and cache application settings."""
    return Settings(
        host=os.getenv("SRC_HOST", "0.0.0.0"),
        port=int(os.getenv("SRC_PORT", "8000")),
        database_path=Path(os.getenv("SRC_DB_PATH", "data/src.db")),
        task_data_dir=Path(os.getenv("SRC_TASK_DATA_DIR", "data/tasks")),
        planner_prompt_file=Path(os.getenv("SRC_PLANNER_PROMPT_FILE", "prompts/action_planner.md")),
        allowed_workdirs=_parse_allowed_workdirs(os.getenv("SRC_ALLOWED_WORKDIRS")),
        model=ModelSettings(
            provider=os.getenv("SRC_MODEL_PROVIDER", "codex_cli"),
            model_name=os.getenv("SRC_MODEL_NAME", "codex"),
            api_base=os.getenv("SRC_MODEL_API_BASE", ""),
            api_key=os.getenv("SRC_MODEL_API_KEY", ""),
            timeout_seconds=max(1, int(os.getenv("SRC_MODEL_TIMEOUT", os.getenv("SRC_COMMAND_TIMEOUT", "1800")))),
            temperature=float(os.getenv("SRC_MODEL_TEMPERATURE", "0.0")),
            codex_cli_path=os.getenv("SRC_CODEX_CLI_PATH", "codex"),
            codex_skip_git_repo_check=os.getenv("SRC_CODEX_SKIP_GIT_REPO_CHECK", "true").lower() == "true",
        ),
        command_timeout_seconds=int(os.getenv("SRC_COMMAND_TIMEOUT", "1800")),
        shell_executable=os.getenv("SRC_SHELL_EXECUTABLE", _default_shell_executable()),
        log_level=os.getenv("SRC_LOG_LEVEL", "INFO").upper(),
        require_confirmation_for_network=os.getenv("SRC_CONFIRM_NETWORK", "true").lower() == "true",
        require_confirmation_for_overwrite=os.getenv("SRC_CONFIRM_OVERWRITE", "true").lower() == "true",
        telegram_bot_token=os.getenv("SRC_TELEGRAM_BOT_TOKEN", ""),
        telegram_allowed_chat_ids=_parse_string_list(os.getenv("SRC_TELEGRAM_ALLOWED_CHAT_IDS")),
        telegram_invite_code=os.getenv("SRC_TELEGRAM_INVITE_CODE", ""),
        telegram_require_registration=os.getenv("SRC_TELEGRAM_REQUIRE_REGISTRATION", "true").lower() == "true",
        telegram_poll_timeout_seconds=max(1, int(os.getenv("SRC_TELEGRAM_POLL_TIMEOUT", "30"))),
        telegram_poll_retry_seconds=max(1, int(os.getenv("SRC_TELEGRAM_POLL_RETRY", "3"))),
    )
