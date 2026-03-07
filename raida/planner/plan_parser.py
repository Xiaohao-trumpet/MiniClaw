"""Parser utilities for strict planner JSON payloads."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Sequence, Tuple

from pydantic import ValidationError

from raida.planner.action_models import ActionPlan

_SCHEMA_KEYWORDS = {
    "properties",
    "required",
    "additionalProperties",
    "patternProperties",
    "definitions",
    "$defs",
    "$schema",
    "oneOf",
    "anyOf",
    "allOf",
}
_SCHEMA_TYPES = {"object", "array", "string", "number", "integer", "boolean", "null"}
_SCHEMA_TEXT_SIGNALS = {
    "json schema",
    "schema",
    "contract",
    "versioning",
    "response contract",
    "request contract",
    "planner contract",
    "specification",
}


@dataclass
class PlanParseResult:
    """Validated action plan and parser diagnostics."""

    plan: ActionPlan
    cleaned_output: str
    extracted_json: str
    parsed_json: Dict[str, Any]
    cleanup_applied: bool
    schema_like_detected: bool
    schema_like_signals: List[str]


class PlanParseError(ValueError):
    """Raised when planner output cannot be parsed into ActionPlan."""

    def __init__(
        self,
        message: str,
        *,
        kind: str,
        cleaned_output: str = "",
        extracted_json: str = "",
        parsed_json: Dict[str, Any] | None = None,
        cleanup_applied: bool = False,
        schema_like_detected: bool = False,
        schema_like_signals: Sequence[str] | None = None,
    ) -> None:
        super().__init__(message)
        self.kind = kind
        self.cleaned_output = cleaned_output
        self.extracted_json = extracted_json
        self.parsed_json = parsed_json
        self.cleanup_applied = cleanup_applied
        self.schema_like_detected = schema_like_detected
        self.schema_like_signals = list(schema_like_signals or [])


def _strip_outer_code_fence(text: str) -> Tuple[str, bool]:
    match = re.fullmatch(r"\s*```(?:json)?\s*([\s\S]*?)\s*```\s*", text, flags=re.IGNORECASE)
    if not match:
        return text, False
    return match.group(1).strip(), True


def _cleanup_raw_output(raw_output: str) -> Tuple[str, bool]:
    cleaned = raw_output.strip()
    fence_stripped = False
    cleaned, fence_stripped = _strip_outer_code_fence(cleaned)
    cleanup_applied = cleaned != raw_output or fence_stripped
    return cleaned, cleanup_applied


def _iter_json_object_candidates(text: str) -> Iterable[Tuple[str, Dict[str, Any]]]:
    if not text:
        return

    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        payload = None
    if isinstance(payload, dict):
        yield text, payload

    decoder = json.JSONDecoder()
    for index, char in enumerate(text):
        if char != "{":
            continue
        try:
            parsed, end = decoder.raw_decode(text[index:])
        except json.JSONDecodeError:
            continue
        if not isinstance(parsed, dict):
            continue
        candidate = text[index : index + end].strip()
        if candidate:
            yield candidate, parsed


def _load_json_payload(cleaned_output: str, cleanup_applied: bool) -> Tuple[str, Dict[str, Any]]:
    for candidate_json, candidate_payload in _iter_json_object_candidates(cleaned_output):
        return candidate_json, candidate_payload
    raise PlanParseError(
        "Planner output is not valid JSON object.",
        kind="invalid_json",
        cleaned_output=cleaned_output,
        cleanup_applied=cleanup_applied,
    )


def _flatten_object(obj: Any, path: str = "") -> Iterable[Tuple[str, Any]]:
    if isinstance(obj, dict):
        for key, value in obj.items():
            next_path = f"{path}.{key}" if path else str(key)
            yield next_path, value
            yield from _flatten_object(value, next_path)
    elif isinstance(obj, list):
        for index, value in enumerate(obj):
            next_path = f"{path}[{index}]"
            yield from _flatten_object(value, next_path)


def _detect_schema_like_payload(payload: Dict[str, Any], cleaned_output: str) -> Tuple[bool, List[str]]:
    strong_signals: List[str] = []
    weak_signals: List[str] = []

    for path, value in _flatten_object(payload):
        key = path.split(".")[-1]
        if key in _SCHEMA_KEYWORDS:
            strong_signals.append(f"{path} key indicates schema metadata")
        if key == "type" and isinstance(value, str) and value.lower() in _SCHEMA_TYPES:
            strong_signals.append(f"{path} uses schema type '{value}'")
        if key == "description" and isinstance(value, str):
            weak_signals.append(f"{path} looks like field metadata")

    text_blob = cleaned_output.lower()
    for phrase in _SCHEMA_TEXT_SIGNALS:
        if phrase in text_blob:
            weak_signals.append(f"output contains schema/contract wording '{phrase}'")

    signals = strong_signals + weak_signals
    if strong_signals:
        return True, signals
    if len(weak_signals) >= 3:
        return True, signals
    return False, signals


def _path(loc: Tuple[Any, ...]) -> str:
    return ".".join(str(item) for item in loc)


def _format_validation_error(exc: ValidationError) -> Tuple[str, str]:
    errors = exc.errors()
    missing_fields = sorted({_path(tuple(err.get("loc", ()))) for err in errors if err.get("type") == "missing"})
    if missing_fields:
        return (
            f"Planner output is missing required runtime fields: {', '.join(missing_fields)}.",
            "missing_fields",
        )

    type_errors = []
    for err in errors:
        error_type = str(err.get("type", ""))
        if "type" in error_type or error_type == "literal_error":
            type_errors.append(f"{_path(tuple(err.get('loc', ())))}: {err.get('msg', 'invalid type')}")
    if type_errors:
        return f"Planner output has wrong field types: {'; '.join(type_errors)}.", "wrong_field_types"

    details = "; ".join(f"{_path(tuple(err.get('loc', ())))}: {err.get('msg', 'invalid value')}" for err in errors[:5])
    return f"Planner output failed ActionPlan validation: {details}.", "validation_error"


def parse_action_plan_output(raw_output: str, task_id: str) -> PlanParseResult:
    """Parse strict planner output into validated ActionPlan with diagnostics."""
    cleaned_output, cleanup_applied = _cleanup_raw_output(raw_output)
    extracted_json, payload = _load_json_payload(cleaned_output, cleanup_applied)

    schema_like_detected, schema_signals = _detect_schema_like_payload(payload, cleaned_output)
    if schema_like_detected:
        details = "; ".join(schema_signals[:6])
        raise PlanParseError(
            f"Planner returned a schema/contract instead of a runtime ActionPlan instance. {details}",
            kind="schema_like_output",
            cleaned_output=cleaned_output,
            extracted_json=extracted_json,
            parsed_json=payload,
            cleanup_applied=cleanup_applied,
            schema_like_detected=True,
            schema_like_signals=schema_signals,
        )

    payload["task_id"] = task_id
    try:
        plan = ActionPlan.model_validate(payload)
    except ValidationError as exc:
        message, kind = _format_validation_error(exc)
        raise PlanParseError(
            message,
            kind=kind,
            cleaned_output=cleaned_output,
            extracted_json=extracted_json,
            parsed_json=payload,
            cleanup_applied=cleanup_applied,
            schema_like_detected=False,
            schema_like_signals=schema_signals,
        ) from exc

    return PlanParseResult(
        plan=plan,
        cleaned_output=cleaned_output,
        extracted_json=extracted_json,
        parsed_json=payload,
        cleanup_applied=cleanup_applied,
        schema_like_detected=False,
        schema_like_signals=schema_signals,
    )


def parse_action_plan(raw_output: str, task_id: str) -> ActionPlan:
    """Backward-compatible parser entrypoint returning only ActionPlan."""
    return parse_action_plan_output(raw_output=raw_output, task_id=task_id).plan
