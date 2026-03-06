#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT_DIR}"

export PYTHONPATH="${ROOT_DIR}:${PYTHONPATH:-}"
uvicorn raida.main:app --host "${RAIDA_HOST:-0.0.0.0}" --port "${RAIDA_PORT:-8000}"

