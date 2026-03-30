"""Telegram adapter interface and implementations."""

from __future__ import annotations

import json
import mimetypes
import os
import threading
import time
import uuid
from abc import ABC, abstractmethod
from typing import Any, Callable, Dict, List, Optional
from urllib import error, request

from src.utils.logger import get_logger

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
    def stop(self) -> None:
        """Stop background adapter workers."""

    @abstractmethod
    def handle_update(self, update: Dict[str, Any]) -> bool:
        """Handle one Telegram update payload."""

    @abstractmethod
    def send_message(self, user_id: str, text: str) -> Dict[str, Any] | None:
        """Send text message to user."""

    @abstractmethod
    def edit_message(self, user_id: str, message_id: int, text: str) -> Dict[str, Any] | None:
        """Edit a previously sent text message when supported."""

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
        self._next_message_id = 1

    def start_listening(self, handler: Callable[[str, str], None]) -> None:
        self._handler = handler
        logger.info("MockTelegramAdapter is active.")

    def stop(self) -> None:
        return

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

    def send_message(self, user_id: str, text: str) -> Dict[str, Any]:
        message_id = self._next_message_id
        self._next_message_id += 1
        logger.info("[MockTelegram->%s] %s", user_id, text)
        return {"message_id": message_id, "text": text}

    def edit_message(self, user_id: str, message_id: int, text: str) -> Dict[str, Any]:
        logger.info("[MockTelegram->%s][edit:%s] %s", user_id, message_id, text)
        return {"message_id": message_id, "text": text}

    def send_image(self, user_id: str, image_path: str) -> None:
        logger.info("[MockTelegram->%s] [image] %s", user_id, image_path)

    def send_file(self, user_id: str, file_path: str) -> None:
        logger.info("[MockTelegram->%s] [file] %s", user_id, file_path)


class TelegramBotApiAdapter(TelegramAdapter):
    """Telegram Bot API adapter (long polling mode)."""

    def __init__(
        self,
        bot_token: str,
        request_timeout_seconds: int = 30,
        poll_timeout_seconds: int = 30,
        poll_retry_seconds: int = 3,
        initial_update_offset: Optional[int] = None,
        offset_commit: Optional[Callable[[int], None]] = None,
    ) -> None:
        self._bot_token = bot_token.strip()
        self._request_timeout_seconds = request_timeout_seconds
        self._poll_timeout_seconds = max(1, poll_timeout_seconds)
        self._poll_retry_seconds = max(1, poll_retry_seconds)
        self._handler: Optional[Callable[[str, str], None]] = None
        self._next_update_offset: Optional[int] = initial_update_offset if (initial_update_offset and initial_update_offset > 0) else None
        self._offset_commit = offset_commit
        self._stop_event = threading.Event()
        self._poll_thread: Optional[threading.Thread] = None

    def start_listening(self, handler: Callable[[str, str], None]) -> None:
        self._handler = handler
        self._stop_event.clear()
        self._disable_webhook_if_possible()
        if self._poll_thread and self._poll_thread.is_alive():
            logger.info("Telegram polling thread already running.")
            return
        self._poll_thread = threading.Thread(target=self._poll_loop, name="telegram-polling", daemon=True)
        self._poll_thread.start()
        logger.info("TelegramBotApiAdapter started long polling.")

    def stop(self) -> None:
        self._stop_event.set()
        if self._poll_thread and self._poll_thread.is_alive():
            self._poll_thread.join(timeout=5)
        self._poll_thread = None

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

    def send_message(self, user_id: str, text: str) -> Dict[str, Any] | None:
        chat_id = to_chat_id(user_id)
        last_result: Dict[str, Any] | None = None
        for chunk in _split_text(text, TELEGRAM_TEXT_LIMIT):
            response = self._post_json(
                "sendMessage",
                {
                    "chat_id": chat_id,
                    "text": chunk,
                },
            )
            result = response.get("result")
            last_result = result if isinstance(result, dict) else response
        return last_result

    def edit_message(self, user_id: str, message_id: int, text: str) -> Dict[str, Any] | None:
        chat_id = to_chat_id(user_id)
        payload = {
            "chat_id": chat_id,
            "message_id": int(message_id),
            "text": text[:TELEGRAM_TEXT_LIMIT],
        }
        response = self._post_json("editMessageText", payload)
        result = response.get("result")
        return result if isinstance(result, dict) else response

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

    def _poll_loop(self) -> None:
        consecutive_failures = 0
        while not self._stop_event.is_set():
            try:
                payload: Dict[str, Any] = {
                    "timeout": self._poll_timeout_seconds,
                    "allowed_updates": ["message", "callback_query"],
                }
                if self._next_update_offset is not None:
                    payload["offset"] = self._next_update_offset

                response = self._post_json(
                    "getUpdates",
                    payload,
                    timeout_seconds=self._poll_timeout_seconds + 15,
                )
                updates = response.get("result", [])
                if not isinstance(updates, list):
                    raise RuntimeError(f"Unexpected getUpdates payload: {response}")

                max_update_id: Optional[int] = None
                for item in updates:
                    if not isinstance(item, dict):
                        continue
                    update_id = item.get("update_id")
                    if isinstance(update_id, int):
                        max_update_id = update_id if max_update_id is None else max(max_update_id, update_id)

                    try:
                        self.handle_update(item)
                    except Exception as exc:  # pragma: no cover - handler side effects
                        logger.exception("Failed to process Telegram update: %s", exc)

                if max_update_id is not None:
                    self._next_update_offset = max_update_id + 1
                    self._commit_offset(self._next_update_offset)

                consecutive_failures = 0
            except Exception as exc:
                consecutive_failures += 1
                wait_seconds = min(30, self._poll_retry_seconds * max(1, consecutive_failures))
                logger.warning("Telegram polling failed (%s). Retry in %ss.", exc, wait_seconds)
                if self._stop_event.wait(timeout=wait_seconds):
                    break

    def _disable_webhook_if_possible(self) -> None:
        try:
            self._post_json("deleteWebhook", {"drop_pending_updates": False})
        except Exception as exc:  # pragma: no cover - best effort
            logger.warning("Failed to delete Telegram webhook before polling: %s", exc)

    def _commit_offset(self, offset: int) -> None:
        if not self._offset_commit:
            return
        try:
            self._offset_commit(offset)
        except Exception as exc:  # pragma: no cover
            logger.warning("Failed to persist Telegram offset %s: %s", offset, exc)

    def _answer_callback_query(self, callback_query_id: str) -> None:
        try:
            self._post_json("answerCallbackQuery", {"callback_query_id": callback_query_id})
        except Exception as exc:  # pragma: no cover - best effort
            logger.warning("answerCallbackQuery failed: %s", exc)

    def _post_json(
        self,
        method: str,
        payload: Dict[str, Any],
        timeout_seconds: Optional[int] = None,
    ) -> Dict[str, Any]:
        raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = request.Request(
            self._build_url(method),
            data=raw,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        return self._execute_request(req, timeout_seconds=timeout_seconds)

    def _post_multipart(self, method: str, fields: Dict[str, str], file_field: str, file_path: str) -> Dict[str, Any]:
        if not os.path.isfile(file_path):
            raise FileNotFoundError(f"File not found: {file_path}")

        boundary = f"----src-{uuid.uuid4().hex}"
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

    def _execute_request(self, req: request.Request, timeout_seconds: Optional[int] = None) -> Dict[str, Any]:
        timeout = timeout_seconds if timeout_seconds is not None else self._request_timeout_seconds
        try:
            with request.urlopen(req, timeout=timeout) as resp:
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
