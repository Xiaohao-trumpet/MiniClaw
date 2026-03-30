"""Canonical action specifications and normalization helpers."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Mapping, Sequence


@dataclass(frozen=True)
class ActionSpec:
    """Canonical runtime contract for one action type."""

    required_args: tuple[str, ...] = ()
    arg_aliases: Dict[str, tuple[str, ...]] = field(default_factory=dict)
    defaults: Dict[str, Any] = field(default_factory=dict)


ACTION_TYPE_ALIASES: Dict[str, str] = {
    "list_files": "list_directory",
    "ls": "list_directory",
    "read_files": "read_multiple_files",
    "final_response": "respond_only",
    "reply": "respond_only",
    "confirm": "request_confirmation",
    "confirmation": "request_confirmation",
}

RISK_LEVEL_ALIASES: Dict[str, str] = {
    "moderate": "medium",
    "normal": "low",
    "safe": "low",
    "dangerous": "high",
    "severe": "high",
}

FINAL_RESPONSE_STYLE_ALIASES: Dict[str, str] = {
    "brief": "concise",
    "short": "concise",
    "verbose": "detailed",
    "full": "detailed",
}

ACTION_SPECS: Dict[str, ActionSpec] = {
    "run_command": ActionSpec(
        required_args=("command",),
        arg_aliases={
            "command": ("cmd", "shell_command"),
            "working_directory": ("cwd", "workdir"),
        },
    ),
    "open_application": ActionSpec(
        required_args=("name",),
        arg_aliases={"name": ("app", "application")},
    ),
    "open_url": ActionSpec(
        required_args=("url",),
        arg_aliases={"url": ("link", "href")},
    ),
    "list_directory": ActionSpec(
        required_args=("path",),
        arg_aliases={"path": ("directory", "dir", "root")},
        defaults={"path": "."},
    ),
    "read_file": ActionSpec(
        required_args=("path",),
        arg_aliases={"path": ("file", "file_path")},
    ),
    "write_file": ActionSpec(
        required_args=("path", "content"),
        arg_aliases={
            "path": ("file", "file_path"),
            "content": ("text", "body"),
        },
    ),
    "focus_window": ActionSpec(
        required_args=("title",),
        arg_aliases={"title": ("window_title", "name")},
    ),
    "type_text": ActionSpec(
        required_args=("text",),
        arg_aliases={"text": ("message", "content")},
    ),
    "press_key": ActionSpec(
        required_args=("key",),
        arg_aliases={"key": ("button", "keys")},
    ),
    "mouse_click": ActionSpec(required_args=("x", "y")),
    "find_files": ActionSpec(
        required_args=("pattern",),
        arg_aliases={
            "path": ("directory", "dir", "root"),
            "pattern": ("glob", "query"),
        },
        defaults={"path": "."},
    ),
    "search_text": ActionSpec(
        required_args=("query",),
        arg_aliases={
            "path": ("directory", "dir", "root"),
            "query": ("pattern", "needle", "text"),
        },
        defaults={"path": "."},
    ),
    "read_multiple_files": ActionSpec(
        required_args=("paths",),
        arg_aliases={"paths": ("files", "file_paths")},
    ),
    "request_confirmation": ActionSpec(
        required_args=("prompt",),
        arg_aliases={"prompt": ("message", "text")},
    ),
    "respond_only": ActionSpec(
        required_args=("message",),
        arg_aliases={"message": ("prompt", "response", "summary", "text")},
    ),
}

_TRUE_VALUES = {"1", "true", "yes", "y", "on"}
_FALSE_VALUES = {"0", "false", "no", "n", "off"}


def canonical_action_type(value: object) -> str:
    """Normalize action type aliases to canonical runtime names."""

    raw = str(value or "").strip().lower()
    return ACTION_TYPE_ALIASES.get(raw, raw)


def normalize_bool(value: object) -> object:
    """Normalize common string booleans while preserving other types."""

    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in _TRUE_VALUES:
            return True
        if lowered in _FALSE_VALUES:
            return False
    return value


def normalize_action_payload(action: Mapping[str, Any]) -> tuple[Dict[str, Any], list[str]]:
    """Normalize an action payload into the canonical runtime shape."""

    normalized = dict(action)
    notes: list[str] = []

    action_type = canonical_action_type(normalized.get("action_type", ""))
    if action_type and action_type != normalized.get("action_type"):
        notes.append(f"action_type:{normalized.get('action_type')}->{action_type}")
    normalized["action_type"] = action_type

    raw_args = normalized.get("args", {})
    args = dict(raw_args) if isinstance(raw_args, Mapping) else {}
    spec = ACTION_SPECS.get(action_type, ActionSpec())

    for canonical_key, aliases in spec.arg_aliases.items():
        if canonical_key in args:
            continue
        for alias in aliases:
            if alias in args:
                args[canonical_key] = args.pop(alias)
                notes.append(f"args.{alias}->{canonical_key}")
                break

    for key, value in list(args.items()):
        args[key] = normalize_bool(value)

    if action_type == "read_multiple_files":
        if "paths" not in args:
            for alias in ("path", "file"):
                if alias in args:
                    args["paths"] = [args.pop(alias)]
                    notes.append(f"args.{alias}->paths")
                    break
        elif isinstance(args.get("paths"), str):
            args["paths"] = [str(args["paths"])]
            notes.append("args.paths:string->list")

    if action_type == "request_confirmation" and "prompt" not in args:
        reason = str(normalized.get("reason", "")).strip()
        if reason:
            args["prompt"] = reason
            notes.append("args.prompt<-reason")

    if action_type == "respond_only" and "message" not in args:
        reason = str(normalized.get("reason", "")).strip()
        if reason:
            args["message"] = reason
            notes.append("args.message<-reason")

    for key, value in spec.defaults.items():
        if key not in args:
            args[key] = value
            notes.append(f"args.{key}<-default")

    normalized["args"] = args

    risk_level = str(normalized.get("risk_level", "low") or "low").strip().lower()
    risk_level = RISK_LEVEL_ALIASES.get(risk_level, risk_level or "low")
    normalized["risk_level"] = risk_level
    normalized["requires_confirmation"] = bool(normalize_bool(normalized.get("requires_confirmation", False)))
    return normalized, notes


def normalize_plan_payload(payload: Mapping[str, Any], *, task_id: str = "") -> tuple[Dict[str, Any], list[str]]:
    """Normalize the full action plan payload into the canonical runtime shape."""

    normalized = dict(payload)
    notes: list[str] = []

    if task_id:
        normalized["task_id"] = task_id

    final_response_style = str(normalized.get("final_response_style", "concise") or "concise").strip().lower()
    canonical_style = FINAL_RESPONSE_STYLE_ALIASES.get(final_response_style, final_response_style or "concise")
    if canonical_style != final_response_style:
        notes.append(f"final_response_style:{final_response_style}->{canonical_style}")
    normalized["final_response_style"] = canonical_style

    if "actions" in normalized:
        raw_actions = normalized.get("actions")
        if isinstance(raw_actions, Mapping):
            raw_actions = [dict(raw_actions)]
            notes.append("actions:object->list")

        if isinstance(raw_actions, Sequence) and not isinstance(raw_actions, (str, bytes)):
            actions: list[Dict[str, Any]] = []
            for index, item in enumerate(raw_actions):
                if isinstance(item, Mapping):
                    action, action_notes = normalize_action_payload(item)
                    actions.append(action)
                    notes.extend(f"actions[{index}].{note}" for note in action_notes)
                else:
                    actions.append({"action_type": str(item), "args": {}, "reason": "Normalized from shorthand action."})
                    notes.append(f"actions[{index}]:shorthand->object")
            normalized["actions"] = actions

    return normalized, notes
