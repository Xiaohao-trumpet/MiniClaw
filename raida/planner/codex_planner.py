"""Codex-backed planner that returns strict structured action plans."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from raida.agents.agent_backend import AgentBackend
from raida.planner.action_models import ActionPlan
from raida.planner.plan_parser import PlanParseError, parse_action_plan
from raida.utils.command_runner import CommandResult
from raida.utils.logger import get_logger

logger = get_logger(__name__)


class PlannerExecutionError(RuntimeError):
    """Raised when planner backend invocation fails."""

    def __init__(self, message: str, raw_output: str = "") -> None:
        super().__init__(message)
        self.raw_output = raw_output


@dataclass
class PlannerResult:
    """Planner call result with raw backend output for artifacting."""

    plan: ActionPlan
    raw_output: str
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
            "event=planner_request task_id=%s working_directory=%s instruction=%s",
            task_id,
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
            plan = parse_action_plan(raw_output, task_id=task_id)
        except PlanParseError as exc:
            raise PlannerExecutionError(str(exc), raw_output=raw_output) from exc
        logger.info("event=planner_parsed task_id=%s actions=%s", task_id, len(plan.actions))
        return PlannerResult(plan=plan, raw_output=raw_output, backend_result=result)
