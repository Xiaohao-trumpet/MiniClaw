"""Outbound reporting to messaging clients."""

from __future__ import annotations

from pathlib import Path
from typing import Dict, Optional

from raida.gateway.message_gateway import MessageGateway
from raida.planner.action_models import ActionPlan
from raida.utils.logger import get_logger

logger = get_logger(__name__)


class Reporter:
    """Formats and sends execution updates through MessageGateway."""

    def __init__(self, gateway: MessageGateway) -> None:
        self.gateway = gateway

    def task_created(self, user_id: str, task_id: str, instruction: str) -> None:
        self.gateway.send_message(
            user_id,
            (
                f"[MiniClaw] Task created\n"
                f"task_id: {task_id}\n"
                f"instruction: {instruction}\n"
                f"status: pending"
            ),
        )

    def planning_started(self, user_id: str, task_id: str) -> None:
        self.gateway.send_message(user_id, f"[MiniClaw][{task_id}] Planning started.")

    def plan_accepted(self, user_id: str, task_id: str, plan: ActionPlan) -> None:
        self.gateway.send_message(
            user_id,
            (
                f"[MiniClaw][{task_id}] Plan accepted.\n"
                f"goal: {plan.goal}\n"
                f"actions: {len(plan.actions)}"
            ),
        )

    def waiting_confirmation(self, user_id: str, task_id: str, reason: str) -> None:
        self.gateway.send_message(
            user_id,
            (
                f"[MiniClaw][{task_id}] Waiting for confirmation.\n"
                f"reason: {reason}\n"
                "Reply with: confirm or /confirm <task_id>"
            ),
        )

    def action_started(self, user_id: str, task_id: str, index: int, total: int, action_type: str) -> None:
        self.gateway.send_message(
            user_id,
            f"[MiniClaw][{task_id}] Action started ({index}/{total}): {action_type}",
        )

    def action_result(self, user_id: str, task_id: str, status: str, summary: str) -> None:
        self.gateway.send_message(
            user_id,
            f"[MiniClaw][{task_id}] Action {status}: {summary}",
        )

    def task_failed(self, user_id: str, task_id: str, error: str) -> None:
        self.gateway.send_message(
            user_id,
            f"[MiniClaw] Task {task_id} failed.\nerror: {error}",
        )

    def task_completed(self, user_id: str, task_id: str, summary: str) -> None:
        self.gateway.send_message(
            user_id,
            f"[MiniClaw] Task {task_id} completed.\n{summary}",
        )

    def send_screenshot(self, user_id: str, image_path: Path) -> None:
        try:
            self.gateway.send_image(user_id, str(image_path))
        except Exception as exc:  # pragma: no cover - gateway implementations vary
            logger.exception("Failed to send screenshot: %s", exc)

    def send_file(self, user_id: str, file_path: Path) -> None:
        try:
            self.gateway.send_file(user_id, str(file_path))
        except Exception as exc:  # pragma: no cover
            logger.exception("Failed to send file: %s", exc)

    def maybe_send_path(self, user_id: str, path: Optional[Path]) -> None:
        if path is None:
            return
        if path.suffix.lower() in {".png", ".jpg", ".jpeg"}:
            self.send_screenshot(user_id, path)
        else:
            self.send_file(user_id, path)

    @staticmethod
    def build_final_summary(counts: Dict[str, int], suggested_next_steps: str = "") -> str:
        lines = [
            "Final summary:",
            f"planned_actions: {counts.get('planned', 0)}",
            f"executed_actions: {counts.get('executed', 0)}",
            f"successful_actions: {counts.get('successful', 0)}",
            f"failed_actions: {counts.get('failed', 0)}",
            f"blocked_actions: {counts.get('blocked', 0)}",
            f"skipped_actions: {counts.get('skipped', 0)}",
        ]
        if suggested_next_steps.strip():
            lines.append(f"suggested_next_steps: {suggested_next_steps.strip()}")
        return "\n".join(lines)

