"""Outbound reporting to messaging clients."""

from __future__ import annotations

from pathlib import Path
from typing import Dict, Optional

from src.gateway.message_gateway import MessageGateway
from src.orchestrator.progress_aggregator import build_progress_message
from src.orchestrator.session_models import ProgressSnapshot
from src.planner.action_models import ActionPlan
from src.utils.logger import get_logger

logger = get_logger(__name__)


class Reporter:
    """Formats and sends execution updates through MessageGateway."""

    def __init__(self, gateway: MessageGateway) -> None:
        self.gateway = gateway
        self._progress_message_ids: Dict[str, int] = {}

    def task_created(
        self,
        user_id: str,
        task_id: str,
        instruction: str,
        *,
        session_id: str = "",
        session_title: str = "",
    ) -> None:
        lines = [
            "[MiniClaw] Task created",
            f"task_id: {task_id}",
            f"instruction: {instruction}",
        ]
        if session_id:
            label = session_title or session_id
            lines.append(f"session: {label} ({session_id})")
        lines.append("status: pending")
        self.gateway.send_message(user_id, "\n".join(lines))

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

    def waiting_confirmation(self, user_id: str, task_id: str, reason: str, preview: str = "") -> None:
        message = (
            f"[MiniClaw][{task_id}] Waiting for confirmation.\n"
            f"reason: {reason}"
        )
        if preview.strip():
            message += f"\npreview:\n{preview.strip()}"
        message += "\nReply with: confirm or /confirm <task_id>"
        self.gateway.send_message(user_id, message)

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

    def action_output(self, user_id: str, task_id: str, action_type: str, output: str, max_chars: int = 3000) -> None:
        text = output.strip()
        if not text:
            return
        truncated = len(text) > max_chars
        preview = text[:max_chars]
        suffix = "\n...[truncated]" if truncated else ""
        self.gateway.send_message(
            user_id,
            (
                f"[MiniClaw][{task_id}] Action output ({action_type}):\n"
                f"{preview}{suffix}"
            ),
        )

    def progress_update(self, user_id: str, snapshot: ProgressSnapshot) -> ProgressSnapshot:
        text = build_progress_message(snapshot)
        message_id = snapshot.progress_message_id or self._progress_message_ids.get(snapshot.task_id)
        response = None
        if message_id:
            try:
                response = self.gateway.edit_message(user_id, int(message_id), text)
            except Exception as exc:  # pragma: no cover - adapter fallback path
                logger.warning("Failed to edit progress message for %s: %s", snapshot.task_id, exc)
                response = None
        if response is None:
            response = self.gateway.send_message(user_id, text)

        extracted = self._extract_message_id(response)
        if extracted is not None:
            self._progress_message_ids[snapshot.task_id] = extracted
            snapshot.progress_message_id = extracted
        return snapshot

    def task_failed(self, user_id: str, task_id: str, error: str) -> None:
        self._progress_message_ids.pop(task_id, None)
        self.gateway.send_message(
            user_id,
            f"[MiniClaw] Task {task_id} failed.\nerror: {error}",
        )

    def task_completed(self, user_id: str, task_id: str, summary: str) -> None:
        self._progress_message_ids.pop(task_id, None)
        self.gateway.send_message(
            user_id,
            f"[MiniClaw] Final answer for task {task_id}:\n{summary}",
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
        if not path.exists() or not path.is_file():
            return
        if path.stat().st_size == 0:
            logger.info("Skip sending empty artifact file: %s", path)
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
            f"denied_actions: {counts.get('denied', 0)}",
            f"skipped_actions: {counts.get('skipped', 0)}",
        ]
        if suggested_next_steps.strip():
            lines.append(f"suggested_next_steps: {suggested_next_steps.strip()}")
        return "\n".join(lines)

    @staticmethod
    def _extract_message_id(response: object) -> Optional[int]:
        if isinstance(response, dict):
            message_id = response.get("message_id")
            if isinstance(message_id, int):
                return message_id
            nested = response.get("result")
            if isinstance(nested, dict) and isinstance(nested.get("message_id"), int):
                return int(nested["message_id"])
        return None
