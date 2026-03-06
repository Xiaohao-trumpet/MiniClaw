"""Unified message gateway."""

from __future__ import annotations

from typing import Callable, Optional

from raida.gateway.telegram_adapter import TelegramAdapter


class MessageGateway:
    """Application-facing message gateway that hides provider details."""

    def __init__(self, adapter: TelegramAdapter) -> None:
        self.adapter = adapter
        self._handler: Optional[Callable[[str, str], None]] = None

    def start(self) -> None:
        self.adapter.start_listening(self.receive_message)

    def stop(self) -> None:
        self.adapter.stop()

    def set_message_handler(self, handler: Callable[[str, str], None]) -> None:
        self._handler = handler

    def receive_message(self, user_id: str, message: str) -> None:
        if self._handler is None:
            raise RuntimeError("Message handler is not configured.")
        self._handler(user_id, message)

    def send_message(self, user_id: str, text: str) -> None:
        self.adapter.send_message(user_id, text)

    def send_image(self, user_id: str, image_path: str) -> None:
        self.adapter.send_image(user_id, image_path)

    def send_file(self, user_id: str, file_path: str) -> None:
        self.adapter.send_file(user_id, file_path)
