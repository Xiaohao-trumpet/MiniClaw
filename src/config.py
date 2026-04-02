"""Application configuration for MiniClaw."""

from __future__ import annotations

import os
import shutil
from functools import lru_cache
from pathlib import Path
from typing import Callable, List

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
    session_data_dir: Path = Field(default=Path("data/sessions"))
    project_data_dir: Path = Field(default=Path("data/projects"))
    planner_prompt_file: Path = Field(default=Path("prompts/action_planner.md"))
    allowed_workdirs: List[Path] = Field(default_factory=lambda: [Path.cwd()])
    session_recent_turns: int = 12
    auto_create_session_on_run: bool = True

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


def _is_valid_chat_id(value: str) -> bool:
    raw = value.strip()
    if not raw:
        return False
    if raw.startswith("tg_"):
        raw = raw[3:]
    if raw.startswith("-"):
        return raw[1:].isdigit()
    return raw.isdigit()


def validate_settings(settings: Settings, *, warn: Callable[[str], None] | None = None) -> None:
    """Fail fast on invalid runtime configuration and emit actionable warnings."""

    provider = settings.model.provider.strip().lower()
    if provider not in {"codex", "codex_cli", "openai", "openai_compatible"}:
        raise ValueError(f"Unsupported model provider: {settings.model.provider}")

    if not settings.planner_prompt_file.exists():
        raise ValueError(f"Planner prompt file not found: {settings.planner_prompt_file}")
    if not settings.allowed_workdirs:
        raise ValueError("SRC_ALLOWED_WORKDIRS must contain at least one path.")
    if settings.session_recent_turns < 1:
        raise ValueError("SRC_SESSION_RECENT_TURNS must be at least 1.")

    missing_roots = [str(path) for path in settings.allowed_workdirs if not path.exists()]
    if missing_roots:
        raise ValueError(f"Allowed workdirs do not exist: {', '.join(missing_roots)}")

    if provider in {"codex", "codex_cli"}:
        cli_path = settings.model.codex_cli_path.strip()
        cli_exists = bool(cli_path) and (Path(cli_path).exists() or shutil.which(cli_path))
        if not cli_exists:
            raise ValueError(f"SRC_CODEX_CLI_PATH is not executable: {settings.model.codex_cli_path}")

    if provider in {"openai", "openai_compatible"} and not settings.model.api_base.strip():
        raise ValueError("SRC_MODEL_API_BASE is required when using openai_compatible provider.")

    invalid_chat_ids = [item for item in settings.telegram_allowed_chat_ids if not _is_valid_chat_id(item)]
    if invalid_chat_ids:
        raise ValueError(f"Invalid SRC_TELEGRAM_ALLOWED_CHAT_IDS values: {', '.join(invalid_chat_ids)}")

    if warn is not None and not settings.telegram_bot_token.strip():
        warn("SRC_TELEGRAM_BOT_TOKEN is empty. Runtime will use Mock Telegram mode.")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Build and cache application settings."""
    return Settings(
        host=os.getenv("SRC_HOST", "0.0.0.0"),
        port=int(os.getenv("SRC_PORT", "8000")),
        database_path=Path(os.getenv("SRC_DB_PATH", "data/src.db")),
        task_data_dir=Path(os.getenv("SRC_TASK_DATA_DIR", "data/tasks")),
        session_data_dir=Path(os.getenv("SRC_SESSION_DATA_DIR", "data/sessions")),
        project_data_dir=Path(os.getenv("SRC_PROJECT_DATA_DIR", "data/projects")),
        planner_prompt_file=Path(os.getenv("SRC_PLANNER_PROMPT_FILE", "prompts/action_planner.md")),
        allowed_workdirs=_parse_allowed_workdirs(os.getenv("SRC_ALLOWED_WORKDIRS")),
        session_recent_turns=max(1, int(os.getenv("SRC_SESSION_RECENT_TURNS", "12"))),
        auto_create_session_on_run=os.getenv("SRC_AUTO_CREATE_SESSION_ON_RUN", "true").lower() == "true",
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
