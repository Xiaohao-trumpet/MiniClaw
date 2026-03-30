"""Helpers for compact grouped progress output."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable

from src.orchestrator.session_models import ProgressSnapshot
from src.planner.action_models import ActionPlan


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def append_update(snapshot: ProgressSnapshot, text: str, *, limit: int = 8) -> ProgressSnapshot:
    message = text.strip()
    if message:
        snapshot.recent_updates.append(message)
        snapshot.recent_updates = snapshot.recent_updates[-limit:]
    snapshot.updated_at = _utc_now()
    return snapshot


def append_output_preview(snapshot: ProgressSnapshot, action_type: str, output: str, *, limit: int = 3, max_chars: int = 240) -> ProgressSnapshot:
    text = output.strip()
    if not text:
        return snapshot
    preview = text[:max_chars]
    if len(text) > max_chars:
        preview += "..."
    snapshot.recent_outputs.append(f"{action_type}: {preview}")
    snapshot.recent_outputs = snapshot.recent_outputs[-limit:]
    snapshot.updated_at = _utc_now()
    return snapshot


def record_plan(snapshot: ProgressSnapshot, plan: ActionPlan) -> ProgressSnapshot:
    snapshot.phase = "planning"
    snapshot.goal = plan.goal
    snapshot.action_count = len(plan.actions)
    snapshot.action_types = [item.action_type for item in plan.actions]
    snapshot.current_action_index = 0
    snapshot.current_action_total = len(plan.actions)
    snapshot.current_action_type = ""
    snapshot.last_status = "plan_ready"
    snapshot.last_summary = f"Planned {len(plan.actions)} actions."
    append_update(snapshot, snapshot.last_summary)
    snapshot.updated_at = _utc_now()
    return snapshot


def record_action_started(snapshot: ProgressSnapshot, *, index: int, total: int, action_type: str) -> ProgressSnapshot:
    snapshot.phase = "running"
    snapshot.current_action_index = index
    snapshot.current_action_total = total
    snapshot.current_action_type = action_type
    snapshot.last_status = "running"
    snapshot.last_summary = f"Running {action_type} ({index}/{total})."
    append_update(snapshot, snapshot.last_summary)
    snapshot.updated_at = _utc_now()
    return snapshot


def record_action_result(
    snapshot: ProgressSnapshot,
    *,
    action_type: str,
    status: str,
    summary: str,
    output: str = "",
) -> ProgressSnapshot:
    snapshot.phase = "running"
    snapshot.current_action_type = action_type
    snapshot.last_status = status
    snapshot.last_summary = summary.strip()
    append_update(snapshot, f"{action_type}: {status} - {summary.strip()}")
    append_output_preview(snapshot, action_type, output)
    snapshot.updated_at = _utc_now()
    return snapshot


def record_waiting_confirmation(snapshot: ProgressSnapshot, *, reason: str, preview: str = "") -> ProgressSnapshot:
    snapshot.phase = "waiting_confirmation"
    snapshot.last_status = "waiting_confirmation"
    summary = reason.strip()
    if preview.strip():
        summary = f"{summary} Preview: {preview.strip()}"
    snapshot.last_summary = summary
    append_update(snapshot, "Waiting for confirmation.")
    snapshot.updated_at = _utc_now()
    return snapshot


def record_failed(snapshot: ProgressSnapshot, *, summary: str) -> ProgressSnapshot:
    snapshot.phase = "failed"
    snapshot.last_status = "failed"
    snapshot.last_summary = summary.strip()
    append_update(snapshot, f"Failed: {summary.strip()}")
    snapshot.updated_at = _utc_now()
    return snapshot


def record_completed(snapshot: ProgressSnapshot, *, summary: str) -> ProgressSnapshot:
    snapshot.phase = "completed"
    snapshot.last_status = "completed"
    snapshot.last_summary = summary.strip()
    append_update(snapshot, "Task completed.")
    snapshot.updated_at = _utc_now()
    return snapshot


def build_progress_message(snapshot: ProgressSnapshot) -> str:
    lines = [f"[MiniClaw][{snapshot.task_id}] Progress"]
    if snapshot.session_title:
        lines.append(f"session: {snapshot.session_title} ({snapshot.session_id})")
    elif snapshot.session_id:
        lines.append(f"session: {snapshot.session_id}")
    lines.append(f"phase: {snapshot.phase}")
    if snapshot.goal:
        lines.append(f"goal: {snapshot.goal}")
    if snapshot.action_count:
        lines.append(f"actions: {snapshot.action_count}")
    if snapshot.current_action_type:
        lines.append(
            f"current: {snapshot.current_action_type} ({snapshot.current_action_index}/{max(snapshot.current_action_total, snapshot.action_count)})"
        )
    if snapshot.last_summary:
        lines.append(f"latest: {snapshot.last_summary}")
    if snapshot.recent_outputs:
        lines.append("recent_outputs:")
        lines.extend(f"- {item}" for item in snapshot.recent_outputs[-2:])
    if snapshot.detail_artifact_path:
        lines.append("use /details <task_id> to view full planning/execution details")
    return "\n".join(lines)


def build_progress_details(snapshot: ProgressSnapshot) -> str:
    lines = [
        f"task_id: {snapshot.task_id}",
        f"session_id: {snapshot.session_id}",
        f"session_title: {snapshot.session_title}",
        f"phase: {snapshot.phase}",
        f"instruction: {snapshot.instruction}",
        f"goal: {snapshot.goal}",
        f"action_count: {snapshot.action_count}",
        f"action_types: {', '.join(snapshot.action_types)}",
        f"current_action: {snapshot.current_action_type}",
        f"current_index: {snapshot.current_action_index}/{snapshot.current_action_total}",
        f"last_status: {snapshot.last_status}",
        f"last_summary: {snapshot.last_summary}",
        f"updated_at: {snapshot.updated_at}",
        "",
        "recent_updates:",
    ]
    lines.extend(_prefixed(snapshot.recent_updates))
    lines.append("")
    lines.append("recent_outputs:")
    lines.extend(_prefixed(snapshot.recent_outputs))
    return "\n".join(lines)


def _prefixed(items: Iterable[str]) -> list[str]:
    values = [str(item).strip() for item in items if str(item).strip()]
    if not values:
        return ["-"]
    return [f"- {item}" for item in values]
