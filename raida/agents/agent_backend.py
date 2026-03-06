"""Abstract backend contract for model providers."""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Callable, Optional

from raida.utils.command_runner import CommandResult


class AgentBackend(ABC):
    """
    Standard contract for AI backends.

    Future integrations (Claude, Qwen, Kimi, Minimax) should implement this
    interface so the orchestration layer remains model-agnostic.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable backend name."""

    @abstractmethod
    def execute_instruction(
        self,
        instruction: str,
        cwd: Path | None = None,
        on_output: Optional[Callable[[str], None]] = None,
    ) -> CommandResult:
        """Execute one natural language instruction and return command-style output."""

