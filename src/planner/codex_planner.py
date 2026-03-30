"""Provider-agnostic planner that returns strict structured action plans."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.models.model_adapter import GenerationOptions, ModelAdapter, ModelRequest, ModelResponse
from src.planner.action_models import ActionPlan
from src.planner.plan_parser import PlanParseError, parse_action_plan_output
from src.utils.logger import get_logger

logger = get_logger(__name__)


class PlannerExecutionError(RuntimeError):
    """Raised when planner model invocation fails."""

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
    """Planner call result with raw model output for artifacting."""

    plan: ActionPlan
    raw_output: str
    cleaned_output: str
    parsed_json: Dict[str, Any]
    cleanup_applied: bool
    schema_like_detected: bool
    schema_like_signals: List[str]
    normalization_applied: bool
    normalization_notes: List[str]
    repair_applied: bool
    model_response: ModelResponse


class ActionPlanner:
    """Asks a model provider for strict JSON plans and validates them."""

    def __init__(self, model_adapter: ModelAdapter, prompt_file: Path, *, temperature: float = 0.0) -> None:
        self._model_adapter = model_adapter
        self._prompt_file = prompt_file
        self._prompt_template = self._load_prompt_template(prompt_file)
        self._temperature = temperature

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
        return "## TaskInput\n" f"{json.dumps(payload, ensure_ascii=False, indent=2)}\n"

    def plan(
        self,
        task_id: str,
        instruction: str,
        working_directory: str = "",
        recent_conversation: Optional[List[dict]] = None,
    ) -> PlannerResult:
        logger.info(
            "event=planner_request task_id=%s provider=%s model=%s prompt_file=%s working_directory=%s instruction=%s",
            task_id,
            self._model_adapter.provider_name,
            self._model_adapter.model_name,
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
        request = ModelRequest(
            prompt=prompt,
            system_prompt=self._prompt_template,
            options=GenerationOptions(temperature=self._temperature),
            metadata={"working_directory": str(cwd) if cwd else ""},
        )
        response = self._model_adapter.generate(request)
        raw_output = response.text.strip()
        logger.info(
            "event=planner_raw_output task_id=%s provider=%s model=%s finish_reason=%s raw=%s",
            task_id,
            response.provider,
            response.model,
            response.finish_reason,
            raw_output[:4000],
        )
        if not raw_output:
            raise PlannerExecutionError("Planner model returned empty output.", raw_output="")
        try:
            parse_result, repaired_output = self._parse_with_repair(raw_output=raw_output, task_id=task_id)
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
            "event=planner_parsed task_id=%s provider=%s model=%s actions=%s cleanup_applied=%s schema_like_detected=%s normalization_applied=%s repair_applied=%s",
            task_id,
            response.provider,
            response.model,
            len(parse_result.plan.actions),
            parse_result.cleanup_applied,
            parse_result.schema_like_detected,
            parse_result.normalization_applied,
            bool(repaired_output),
        )
        return PlannerResult(
            plan=parse_result.plan,
            raw_output=raw_output,
            cleaned_output=repaired_output or parse_result.cleaned_output,
            parsed_json=parse_result.parsed_json,
            cleanup_applied=parse_result.cleanup_applied,
            schema_like_detected=parse_result.schema_like_detected,
            schema_like_signals=parse_result.schema_like_signals,
            normalization_applied=parse_result.normalization_applied,
            normalization_notes=parse_result.normalization_notes,
            repair_applied=bool(repaired_output),
            model_response=response,
        )

    def _parse_with_repair(self, *, raw_output: str, task_id: str) -> tuple[Any, str]:
        try:
            return parse_action_plan_output(raw_output, task_id=task_id), ""
        except PlanParseError as exc:
            if exc.kind not in {"missing_fields", "wrong_field_types", "validation_error"}:
                raise
            repaired_output = self._repair_plan_output(task_id=task_id, raw_output=raw_output, parse_error=exc)
            try:
                parse_result = parse_action_plan_output(repaired_output, task_id=task_id)
            except PlanParseError as repair_exc:
                logger.warning(
                    "event=planner_repair_failed task_id=%s original_kind=%s repair_kind=%s error=%s",
                    task_id,
                    exc.kind,
                    repair_exc.kind,
                    repair_exc,
                )
                raise exc
            logger.info(
                "event=planner_repair_succeeded task_id=%s original_kind=%s",
                task_id,
                exc.kind,
            )
            return parse_result, repaired_output

    def _repair_plan_output(self, *, task_id: str, raw_output: str, parse_error: PlanParseError) -> str:
        logger.info("event=planner_repair_requested task_id=%s kind=%s", task_id, parse_error.kind)
        request = ModelRequest(
            prompt=(
                "## PlanRepairInput\n"
                f"{json.dumps({'task_id': task_id, 'validation_error': str(parse_error), 'previous_output': raw_output}, ensure_ascii=False, indent=2)}\n"
            ),
            system_prompt=(
                "You repair MiniClaw ActionPlan JSON.\n"
                "Return exactly one corrected JSON object and nothing else.\n"
                "Preserve the original intent and as many actions as possible.\n"
                "Fix only runtime validation issues.\n"
                "Use canonical runtime fields, for example request_confirmation.args.prompt.\n"
                "Do not emit markdown or explanations."
            ),
            options=GenerationOptions(temperature=0.0),
        )
        response = self._model_adapter.generate(request)
        repaired_output = response.text.strip()
        if not repaired_output:
            raise PlanParseError(
                "Planner repair response was empty.",
                kind="repair_empty",
                cleaned_output="",
                cleanup_applied=False,
            )
        return repaired_output

    def summarize_execution(
        self,
        *,
        task_id: str,
        instruction: str,
        execution_log: str,
        execution_records: Optional[List[dict]] = None,
        final_summary: str = "",
        working_directory: str = "",
        final_response_style: str = "concise",
    ) -> str:
        """Generate the final user-facing answer from execution evidence."""

        logger.info(
            "event=final_response_request task_id=%s provider=%s model=%s working_directory=%s",
            task_id,
            self._model_adapter.provider_name,
            self._model_adapter.model_name,
            working_directory,
        )
        prompt_payload = {
            "task_id": task_id,
            "instruction": instruction,
            "working_directory": working_directory,
            "final_response_style": final_response_style,
            "execution_log": execution_log[-24000:],
            "execution_records": execution_records or [],
            "final_summary": final_summary,
        }
        system_prompt = (
            "You are writing the final user-facing response for MiniClaw.\n"
            "Use only the execution evidence provided.\n"
            "Do not mention planning or say what you will do.\n"
            "Do not invent facts beyond the evidence.\n"
            "If the evidence is incomplete, say what was observed and what remains uncertain.\n"
            "Return plain text only."
        )
        request = ModelRequest(
            prompt="## ExecutionResultInput\n" f"{json.dumps(prompt_payload, ensure_ascii=False, indent=2)}\n",
            system_prompt=system_prompt,
            options=GenerationOptions(temperature=0.0),
            metadata={"working_directory": working_directory},
        )
        response = self._model_adapter.generate(request)
        text = response.text.strip()
        logger.info(
            "event=final_response_generated task_id=%s provider=%s model=%s finish_reason=%s chars=%s",
            task_id,
            response.provider,
            response.model,
            response.finish_reason,
            len(text),
        )
        if not text:
            raise PlannerExecutionError("Final response model returned empty output.")
        return text


CodexPlanner = ActionPlanner
