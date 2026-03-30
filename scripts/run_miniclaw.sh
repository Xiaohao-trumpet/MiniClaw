#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT_DIR}"

if [[ -z "${VIRTUAL_ENV:-}" && -f "${ROOT_DIR}/.venv/bin/activate" ]]; then
  # Auto-activate the local virtualenv when it exists.
  # shellcheck disable=SC1091
  source "${ROOT_DIR}/.venv/bin/activate"
fi

# Load secrets from .env if it exists (never commit .env to git).
if [[ -f "${ROOT_DIR}/.env" ]]; then
  # shellcheck disable=SC1091
  set -a
  source "${ROOT_DIR}/.env"
  set +a
fi

export PYTHONPATH="${ROOT_DIR}:${PYTHONPATH:-}"
set -a

###############################################################################
# MiniClaw runtime configuration
# Edit the values below before starting the service.
###############################################################################

# Service
: "${SRC_HOST:=0.0.0.0}"
: "${SRC_PORT:=8000}"
: "${SRC_DB_PATH:=data/src.db}"
: "${SRC_TASK_DATA_DIR:=data/tasks}"
: "${SRC_PLANNER_PROMPT_FILE:=prompts/action_planner.md}"
: "${SRC_ALLOWED_WORKDIRS:=${ROOT_DIR},/home/zhouxiaohao/code_search}"
: "${SRC_COMMAND_TIMEOUT:=1800}"
: "${SRC_SHELL_EXECUTABLE:=/bin/bash}"
: "${SRC_LOG_LEVEL:=INFO}"

# Safety
: "${SRC_CONFIRM_NETWORK:=true}"
: "${SRC_CONFIRM_OVERWRITE:=true}"

# Telegram
# Leave SRC_TELEGRAM_BOT_TOKEN empty to run in Mock Telegram mode.
# Set these in .env, not here.
: "${SRC_TELEGRAM_BOT_TOKEN:=}"
: "${SRC_TELEGRAM_ALLOWED_CHAT_IDS:=}"
: "${SRC_TELEGRAM_INVITE_CODE:=}"
: "${SRC_TELEGRAM_REQUIRE_REGISTRATION:=false}"
: "${SRC_TELEGRAM_POLL_TIMEOUT:=30}"
: "${SRC_TELEGRAM_POLL_RETRY:=3}"

# Model provider
# Supported values: codex_cli | openai_compatible
: "${SRC_MODEL_PROVIDER:=codex_cli}"
: "${SRC_MODEL_NAME:=codex}"
: "${SRC_MODEL_TIMEOUT:=1800}"
: "${SRC_MODEL_TEMPERATURE:=0}"

# Codex CLI provider
: "${SRC_CODEX_CLI_PATH:=codex}"
: "${SRC_CODEX_SKIP_GIT_REPO_CHECK:=true}"

# OpenAI-compatible provider
: "${SRC_MODEL_API_BASE:=}"
: "${SRC_MODEL_API_KEY:=}"

set +a

###############################################################################
# Validation
###############################################################################

case "${SRC_MODEL_PROVIDER}" in
  codex_cli)
    if ! command -v "${SRC_CODEX_CLI_PATH}" >/dev/null 2>&1; then
      echo "error: SRC_CODEX_CLI_PATH is not executable: ${SRC_CODEX_CLI_PATH}" >&2
      exit 1
    fi
    ;;
  openai_compatible)
    if [[ -z "${SRC_MODEL_API_BASE}" ]]; then
      echo "error: SRC_MODEL_API_BASE is required when SRC_MODEL_PROVIDER=openai_compatible" >&2
      exit 1
    fi
    ;;
  *)
    echo "error: unsupported SRC_MODEL_PROVIDER: ${SRC_MODEL_PROVIDER}" >&2
    exit 1
    ;;
esac

mkdir -p "$(dirname "${SRC_DB_PATH}")" "${SRC_TASK_DATA_DIR}"

echo "MiniClaw startup configuration"
echo "  host=${SRC_HOST}"
echo "  port=${SRC_PORT}"
echo "  model_provider=${SRC_MODEL_PROVIDER}"
echo "  model_name=${SRC_MODEL_NAME}"
echo "  allowed_workdirs=${SRC_ALLOWED_WORKDIRS}"
if [[ -n "${SRC_TELEGRAM_BOT_TOKEN}" ]]; then
  echo "  telegram_mode=bot"
else
  echo "  telegram_mode=mock"
fi

exec uvicorn src.main:app --host "${SRC_HOST}" --port "${SRC_PORT}"
