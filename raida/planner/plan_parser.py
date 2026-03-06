"""Parser utilities for strict planner JSON payloads."""

from __future__ import annotations

import json
import re
from typing import Any, Dict, Iterable

from pydantic import ValidationError

from raida.planner.action_models import ActionPlan


class PlanParseError(ValueError):
    """Raised when planner output cannot be parsed into ActionPlan."""


def _json_candidates(raw_output: str) -> Iterable[str]:
    text = raw_output.strip()
    if text:
        yield text

    for match in re.finditer(r"```(?:json)?\s*([\s\S]*?)```", raw_output, flags=re.IGNORECASE):
        block = match.group(1).strip()
        if block:
            yield block

    start = raw_output.find("{")
    end = raw_output.rfind("}")
    if start != -1 and end != -1 and end > start:
        block = raw_output[start : end + 1].strip()
        if block:
            yield block


def _load_json_payload(raw_output: str) -> Dict[str, Any]:
    errors = []
    for candidate in _json_candidates(raw_output):
        try:
            payload = json.loads(candidate)
        except json.JSONDecodeError as exc:
            errors.append(str(exc))
            continue
        if isinstance(payload, dict):
            return payload
        errors.append("root JSON value is not an object")
    joined = "; ".join(errors[-3:]) if errors else "no JSON candidate found"
    raise PlanParseError(f"Planner output is not valid JSON object: {joined}")


def parse_action_plan(raw_output: str, task_id: str) -> ActionPlan:
    """Parse strict planner output into validated ActionPlan."""
    payload = _load_json_payload(raw_output)
    payload["task_id"] = task_id
    try:
        return ActionPlan.model_validate(payload)
    except ValidationError as exc:
        raise PlanParseError(f"Invalid action plan schema: {exc}") from exc

