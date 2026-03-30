"""Helpers for consistent execution record payloads."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional

from src.safety.safety_guard import SafetyDecision


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def build_execution_record(
    index: int,
    action: Dict[str, Any],
    status: str,
    summary: str,
    success: bool,
    metadata: Dict[str, Any],
    safety_decision: Optional[SafetyDecision] = None,
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
        "safety_decision": safety_decision.decision if safety_decision else "allow",
        "safety_reason": safety_decision.reason if safety_decision else "",
        "safety_preview": safety_decision.preview if safety_decision else "",
        "safety_category": safety_decision.category if safety_decision else "",
        "metadata": metadata,
    }
