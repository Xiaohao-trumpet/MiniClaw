"""Helpers for consistent execution record payloads."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def build_execution_record(
    index: int,
    action: Dict[str, Any],
    status: str,
    summary: str,
    success: bool,
    metadata: Dict[str, Any],
) -> Dict[str, Any]:
    return {
        "timestamp": utc_now_iso(),
        "index": index,
        "action_type": str(action.get("action_type", "")),
        "status": status,
        "success": success,
        "summary": summary,
        "risk_level": action.get("risk_level", "low"),
        "requires_confirmation": bool(action.get("requires_confirmation", False)),
        "metadata": metadata,
    }

