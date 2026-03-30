"""Provider-agnostic model request and response contracts."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Optional


@dataclass(frozen=True)
class GenerationOptions:
    """Common generation options shared by all providers."""

    temperature: float = 0.0
    timeout_seconds: int | None = None
    max_output_tokens: int | None = None


@dataclass(frozen=True)
class ModelRequest:
    """Unified model input payload."""

    prompt: str
    system_prompt: str = ""
    options: GenerationOptions = field(default_factory=GenerationOptions)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ModelUsage:
    """Normalized token usage information."""

    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None


@dataclass(frozen=True)
class ModelResponse:
    """Unified model response returned by all providers."""

    text: str
    raw_payload: Any
    usage: ModelUsage | None
    finish_reason: str
    provider: str
    model: str


class ModelAdapter(ABC):
    """Provider interface for all model backends."""

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Stable provider identifier."""

    @property
    @abstractmethod
    def model_name(self) -> str:
        """Configured model name."""

    @abstractmethod
    def generate(
        self,
        request: ModelRequest,
        on_output: Optional[Callable[[str], None]] = None,
    ) -> ModelResponse:
        """Generate a normalized response from the provider."""
