"""Codex-backed planner that returns strict structured action plans."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from raida.agents.agent_backend import AgentBackend
from raida.planner.action_models import ActionPlan
from raida.planner.plan_parser import PlanParseError, parse_action_plan_output
from raida.utils.command_runner import CommandResult
from raida.utils.logger import get_logger

logger = get_logger(__name__)


class PlannerExecutionError(RuntimeError):
    """Raised when planner backend invocation fails."""

    def __init__(
        self,
        message: str,
        raw_output: str = "",
        *,
        cleaned_output: str = "",
        parsed_json: Dict[str, Any] | None = None,
        error_kind: str = "unknown",
        cleanup_applied: bool = False,
        schema_like_detected: bool = False,
        schema_like_signals: Optional[List[str]] = None,
    ) -> None:
        super().__init__(message)
        self.raw_output = raw_output
        self.cleaned_output = cleaned_output
        self.parsed_json = parsed_json
        self.error_kind = error_kind
        self.cleanup_applied = cleanup_applied
        self.schema_like_detected = schema_like_detected
        self.schema_like_signals = schema_like_signals or []


@dataclass
class PlannerResult:
    """Planner call result with raw backend output for artifacting."""

    plan: ActionPlan
    raw_output: str
    cleaned_output: str
    parsed_json: Dict[str, Any]
    cleanup_applied: bool
    schema_like_detected: bool
    schema_like_signals: List[str]
    backend_result: CommandResult


class CodexPlanner:
    """Asks Codex for strict JSON plans and validates them."""

    def __init__(self, agent_backend: AgentBackend, prompt_file: Path) -> None:
        self._agent_backend = agent_backend
        self._prompt_file = prompt_file
        self._prompt_template = self._load_prompt_template(prompt_file)

    @staticmethod
    def _load_prompt_template(prompt_file: Path) -> str:
        if not prompt_file.exists():
            raise FileNotFoundError(f"Planner prompt file not found: {prompt_file}")
        return prompt_file.read_text(encoding="utf-8")

    def build_prompt(
        self,
        task_id: str,
        instruction: str,
        working_directory: str = "",
        recent_conversation: Optional[List[dict]] = None,
    ) -> str:
        payload = {
            "task_id": task_id,
            "instruction": instruction,
            "working_directory": working_directory,
            "recent_conversation": recent_conversation or [],
        }
        return (
            f"{self._prompt_template}\n\n"
            "## TaskInput\n"
            f"{json.dumps(payload, ensure_ascii=False, indent=2)}\n"
        )

    def plan(
        self,
        task_id: str,
        instruction: str,
        working_directory: str = "",
        recent_conversation: Optional[List[dict]] = None,
    ) -> PlannerResult:
        logger.info(
            "event=planner_request task_id=%s prompt_file=%s working_directory=%s instruction=%s",
            task_id,
            str(self._prompt_file),
            working_directory,
            instruction,
        )
        prompt = self.build_prompt(
            task_id=task_id,
            instruction=instruction,
            working_directory=working_directory,
            recent_conversation=recent_conversation,
        )
        cwd = Path(working_directory).resolve() if working_directory else None
        result = self._agent_backend.execute_instruction(prompt, cwd=cwd)
        raw_output = (result.stdout or result.stderr or "").strip()
        logger.info(
            "event=planner_raw_output task_id=%s returncode=%s timed_out=%s raw=%s",
            task_id,
            result.returncode,
            result.timed_out,
            raw_output[:4000],
        )
        if not raw_output:
            raise PlannerExecutionError("Planner backend returned empty output.", raw_output="")
        if not result.success:
            logger.warning(
                "planner_backend_nonzero_exit task_id=%s returncode=%s timed_out=%s",
                task_id,
                result.returncode,
                result.timed_out,
            )
        try:
            parse_result = parse_action_plan_output(raw_output, task_id=task_id)
        except PlanParseError as exc:
            logger.warning(
                "event=planner_parse_failed task_id=%s kind=%s cleanup_applied=%s schema_like_detected=%s signals=%s",
                task_id,
                exc.kind,
                exc.cleanup_applied,
                exc.schema_like_detected,
                "; ".join(exc.schema_like_signals[:6]),
            )
            raise PlannerExecutionError(
                str(exc),
                raw_output=raw_output,
                cleaned_output=exc.cleaned_output,
                parsed_json=exc.parsed_json,
                error_kind=exc.kind,
                cleanup_applied=exc.cleanup_applied,
                schema_like_detected=exc.schema_like_detected,
                schema_like_signals=exc.schema_like_signals,
            ) from exc
        logger.info(
            "event=planner_parsed task_id=%s actions=%s cleanup_applied=%s schema_like_detected=%s",
            task_id,
            len(parse_result.plan.actions),
            parse_result.cleanup_applied,
            parse_result.schema_like_detected,
        )
        return PlannerResult(
            plan=parse_result.plan,
            raw_output=raw_output,
            cleaned_output=parse_result.cleaned_output,
            parsed_json=parse_result.parsed_json,
            cleanup_applied=parse_result.cleanup_applied,
            schema_like_detected=parse_result.schema_like_detected,
            schema_like_signals=parse_result.schema_like_signals,
            backend_result=result,
        )
