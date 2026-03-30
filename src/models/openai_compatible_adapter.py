"""OpenAI-compatible HTTP provider implementation."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any, Callable, Dict, Mapping, Optional

from src.models.model_adapter import GenerationOptions, ModelAdapter, ModelRequest, ModelResponse, ModelUsage

JsonTransport = Callable[[str, bytes, Mapping[str, str], int], Mapping[str, Any]]


class OpenAICompatibleModelAdapter(ModelAdapter):
    """Calls a chat-completions compatible HTTP endpoint."""

    def __init__(
        self,
        *,
        api_base: str,
        api_key: str = "",
        model_name: str,
        timeout_seconds: int = 1800,
        temperature: float = 0.0,
        transport: JsonTransport | None = None,
    ) -> None:
        if not api_base.strip():
            raise ValueError("api_base is required for openai_compatible provider")
        self._api_base = api_base.rstrip("/")
        self._api_key = api_key
        self._configured_model_name = model_name
        self._timeout_seconds = timeout_seconds
        self._temperature = temperature
        self._transport = transport or self._default_transport

    @property
    def provider_name(self) -> str:
        return "openai_compatible"

    @property
    def model_name(self) -> str:
        return self._configured_model_name

    def generate(
        self,
        request: ModelRequest,
        on_output: Optional[Callable[[str], None]] = None,
    ) -> ModelResponse:
        del on_output
        payload = self._build_payload(request)
        body = json.dumps(payload).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if self._api_key.strip():
            headers["Authorization"] = f"Bearer {self._api_key}"

        timeout_seconds = request.options.timeout_seconds or self._timeout_seconds
        raw_payload = self._transport(
            f"{self._api_base}/chat/completions",
            body,
            headers,
            timeout_seconds,
        )
        choice = self._first_choice(raw_payload)
        model_name = str(raw_payload.get("model") or self.model_name)
        usage_payload = raw_payload.get("usage", {})
        usage = ModelUsage(
            input_tokens=self._maybe_int(usage_payload, "prompt_tokens"),
            output_tokens=self._maybe_int(usage_payload, "completion_tokens"),
            total_tokens=self._maybe_int(usage_payload, "total_tokens"),
        )
        return ModelResponse(
            text=self._extract_text(choice),
            raw_payload=raw_payload,
            usage=usage,
            finish_reason=str(choice.get("finish_reason") or "stop"),
            provider=self.provider_name,
            model=model_name,
        )

    def _build_payload(self, request: ModelRequest) -> Dict[str, Any]:
        messages = []
        if request.system_prompt.strip():
            messages.append({"role": "system", "content": request.system_prompt})
        messages.append({"role": "user", "content": request.prompt})

        options = request.options if isinstance(request.options, GenerationOptions) else GenerationOptions()
        payload: Dict[str, Any] = {
            "model": self.model_name,
            "messages": messages,
            "temperature": options.temperature if options.temperature is not None else self._temperature,
        }
        if options.max_output_tokens is not None:
            payload["max_tokens"] = options.max_output_tokens
        return payload

    @staticmethod
    def _default_transport(url: str, body: bytes, headers: Mapping[str, str], timeout_seconds: int) -> Mapping[str, Any]:
        request = urllib.request.Request(url, data=body, headers=dict(headers), method="POST")
        try:
            with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:  # pragma: no cover - network integration
            details = exc.read().decode("utf-8", errors="ignore")
            raise RuntimeError(f"OpenAI-compatible provider returned HTTP {exc.code}: {details}") from exc
        except urllib.error.URLError as exc:  # pragma: no cover - network integration
            raise RuntimeError(f"OpenAI-compatible provider request failed: {exc}") from exc

    @staticmethod
    def _first_choice(raw_payload: Mapping[str, Any]) -> Mapping[str, Any]:
        choices = raw_payload.get("choices", [])
        if not isinstance(choices, list) or not choices:
            raise RuntimeError("OpenAI-compatible provider returned no choices")
        first = choices[0]
        if not isinstance(first, dict):
            raise RuntimeError("OpenAI-compatible provider returned malformed choice payload")
        return first

    @staticmethod
    def _extract_text(choice: Mapping[str, Any]) -> str:
        message = choice.get("message", {})
        if not isinstance(message, dict):
            return ""
        content = message.get("content", "")
        if isinstance(content, str):
            return content.strip()
        if isinstance(content, list):
            parts = []
            for item in content:
                if isinstance(item, dict):
                    text = item.get("text")
                    if isinstance(text, str):
                        parts.append(text)
            return "\n".join(part.strip() for part in parts if part.strip()).strip()
        return ""

    @staticmethod
    def _maybe_int(payload: object, key: str) -> int | None:
        if not isinstance(payload, dict):
            return None
        value = payload.get(key)
        if value is None:
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None
