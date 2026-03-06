"""Outbound reporting to messaging clients."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from raida.gateway.message_gateway import MessageGateway
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
                f"[RAIDA] Task created\n"
                f"task_id: {task_id}\n"
                f"instruction: {instruction}\n"
                f"status: pending"
            ),
        )

    def task_started(self, user_id: str, task_id: str) -> None:
        self.gateway.send_message(user_id, f"[RAIDA] Task {task_id} started.")

    def waiting_confirmation(self, user_id: str, task_id: str, reason: str) -> None:
        self.gateway.send_message(
            user_id,
            (
                f"[RAIDA] Task {task_id} requires confirmation.\n"
                f"reason: {reason}\n"
                "Reply with: confirm"
            ),
        )

    def task_update(self, user_id: str, task_id: str, text: str) -> None:
        self.gateway.send_message(user_id, f"[RAIDA][{task_id}] {text}")

    def task_failed(self, user_id: str, task_id: str, error: str) -> None:
        self.gateway.send_message(
            user_id,
            f"[RAIDA] Task {task_id} failed.\nerror: {error}",
        )

    def task_completed(self, user_id: str, task_id: str, summary: str) -> None:
        self.gateway.send_message(
            user_id,
            f"[RAIDA] Task {task_id} completed.\nsummary:\n{summary}",
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

