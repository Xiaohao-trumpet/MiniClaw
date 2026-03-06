"""Telegram adapter interface and implementations."""

from __future__ import annotations

import json
import mimetypes
import os
import uuid
from abc import ABC, abstractmethod
from typing import Any, Callable, Dict, List, Optional
from urllib import error, request

from raida.utils.logger import get_logger

logger = get_logger(__name__)

TELEGRAM_TEXT_LIMIT = 4096


def to_user_id(chat_id: str) -> str:
    return f"tg_{chat_id}"


def to_chat_id(user_id: str) -> str:
    if user_id.startswith("tg_"):
        return user_id[3:]
    return user_id


class TelegramAdapter(ABC):
    """Abstraction layer for Telegram messaging providers."""

    @abstractmethod
    def start_listening(self, handler: Callable[[str, str], None]) -> None:
        """Register callback used by the gateway."""

    @abstractmethod
    def handle_update(self, update: Dict[str, Any]) -> bool:
        """Handle one Telegram update payload."""

    @abstractmethod
    def send_message(self, user_id: str, text: str) -> None:
        """Send text message to user."""

    @abstractmethod
    def send_image(self, user_id: str, image_path: str) -> None:
        """Send image to user."""

    @abstractmethod
    def send_file(self, user_id: str, file_path: str) -> None:
        """Send file to user."""


class MockTelegramAdapter(TelegramAdapter):
    """Local adapter for development without Telegram network calls."""

    def __init__(self) -> None:
        self._handler: Optional[Callable[[str, str], None]] = None

    def start_listening(self, handler: Callable[[str, str], None]) -> None:
        self._handler = handler
        logger.info("MockTelegramAdapter is active.")

    def push_message(self, user_id: str, message: str) -> None:
        if not self._handler:
            raise RuntimeError("No handler registered for MockTelegramAdapter.")
        self._handler(user_id, message)

    def handle_update(self, update: Dict[str, Any]) -> bool:
        if "user_id" in update and "message" in update:
            self.push_message(str(update["user_id"]), str(update["message"]))
            return True

        message = update.get("message")
        if isinstance(message, dict):
            text = message.get("text")
            chat = message.get("chat") or {}
            chat_id = chat.get("id")
            if text and chat_id is not None:
                self.push_message(to_user_id(str(chat_id)), str(text))
                return True
        return False

    def send_message(self, user_id: str, text: str) -> None:
        logger.info("[MockTelegram->%s] %s", user_id, text)

    def send_image(self, user_id: str, image_path: str) -> None:
        logger.info("[MockTelegram->%s] [image] %s", user_id, image_path)

    def send_file(self, user_id: str, file_path: str) -> None:
        logger.info("[MockTelegram->%s] [file] %s", user_id, file_path)


class TelegramBotApiAdapter(TelegramAdapter):
    """Telegram Bot API adapter (webhook mode)."""

    def __init__(self, bot_token: str, timeout_seconds: int = 30) -> None:
        self._bot_token = bot_token.strip()
        self._timeout_seconds = timeout_seconds
        self._handler: Optional[Callable[[str, str], None]] = None

    def start_listening(self, handler: Callable[[str, str], None]) -> None:
        self._handler = handler
        logger.info("TelegramBotApiAdapter is active.")

    def handle_update(self, update: Dict[str, Any]) -> bool:
        if not self._handler:
            raise RuntimeError("No handler registered for TelegramBotApiAdapter.")

        message = update.get("message")
        if isinstance(message, dict):
            text = message.get("text")
            chat = message.get("chat") or {}
            chat_id = chat.get("id")
            if isinstance(text, str) and chat_id is not None:
                self._handler(to_user_id(str(chat_id)), text)
                return True

        callback_query = update.get("callback_query")
        if isinstance(callback_query, dict):
            data = callback_query.get("data")
            cb_message = callback_query.get("message") or {}
            chat = cb_message.get("chat") or {}
            chat_id = chat.get("id")
            cb_id = callback_query.get("id")
            if cb_id:
                self._answer_callback_query(str(cb_id))
            if isinstance(data, str) and chat_id is not None:
                self._handler(to_user_id(str(chat_id)), data)
                return True

        return False

    def send_message(self, user_id: str, text: str) -> None:
        chat_id = to_chat_id(user_id)
        for chunk in _split_text(text, TELEGRAM_TEXT_LIMIT):
            self._post_json(
                "sendMessage",
                {
                    "chat_id": chat_id,
                    "text": chunk,
                },
            )

    def send_image(self, user_id: str, image_path: str) -> None:
        chat_id = to_chat_id(user_id)
        self._post_multipart(
            "sendPhoto",
            fields={"chat_id": chat_id},
            file_field="photo",
            file_path=image_path,
        )

    def send_file(self, user_id: str, file_path: str) -> None:
        chat_id = to_chat_id(user_id)
        self._post_multipart(
            "sendDocument",
            fields={"chat_id": chat_id},
            file_field="document",
            file_path=file_path,
        )

    def _answer_callback_query(self, callback_query_id: str) -> None:
        try:
            self._post_json("answerCallbackQuery", {"callback_query_id": callback_query_id})
        except Exception as exc:  # pragma: no cover - best effort
            logger.warning("answerCallbackQuery failed: %s", exc)

    def _post_json(self, method: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = request.Request(
            self._build_url(method),
            data=raw,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        return self._execute_request(req)

    def _post_multipart(self, method: str, fields: Dict[str, str], file_field: str, file_path: str) -> Dict[str, Any]:
        if not os.path.isfile(file_path):
            raise FileNotFoundError(f"File not found: {file_path}")

        boundary = f"----raida-{uuid.uuid4().hex}"
        body = bytearray()
        for key, value in fields.items():
            body.extend(f"--{boundary}\r\n".encode("utf-8"))
            body.extend(f'Content-Disposition: form-data; name="{key}"\r\n\r\n'.encode("utf-8"))
            body.extend(str(value).encode("utf-8"))
            body.extend(b"\r\n")

        filename = os.path.basename(file_path)
        mime_type = mimetypes.guess_type(file_path)[0] or "application/octet-stream"
        with open(file_path, "rb") as f:
            content = f.read()

        body.extend(f"--{boundary}\r\n".encode("utf-8"))
        body.extend(
            f'Content-Disposition: form-data; name="{file_field}"; filename="{filename}"\r\n'.encode("utf-8")
        )
        body.extend(f"Content-Type: {mime_type}\r\n\r\n".encode("utf-8"))
        body.extend(content)
        body.extend(b"\r\n")
        body.extend(f"--{boundary}--\r\n".encode("utf-8"))

        req = request.Request(
            self._build_url(method),
            data=bytes(body),
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
            method="POST",
        )
        return self._execute_request(req)

    def _execute_request(self, req: request.Request) -> Dict[str, Any]:
        try:
            with request.urlopen(req, timeout=self._timeout_seconds) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
        except error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="ignore")
            raise RuntimeError(f"Telegram API HTTP error: {exc.code} {detail}") from exc
        except error.URLError as exc:
            raise RuntimeError(f"Telegram API network error: {exc.reason}") from exc

        if not payload.get("ok", False):
            raise RuntimeError(f"Telegram API failed: {payload}")
        return payload

    def _build_url(self, method: str) -> str:
        return f"https://api.telegram.org/bot{self._bot_token}/{method}"


def _split_text(text: str, chunk_size: int) -> List[str]:
    raw = text or ""
    if len(raw) <= chunk_size:
        return [raw]

    chunks: List[str] = []
    start = 0
    while start < len(raw):
        end = min(start + chunk_size, len(raw))
        chunks.append(raw[start:end])
        start = end
    return chunks
