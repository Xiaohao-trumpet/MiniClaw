from __future__ import annotations

import json
from pathlib import Path

from src.models.model_adapter import ModelAdapter, ModelRequest, ModelResponse
from src.planner.codex_planner import ActionPlanner


class RecordingAdapter(ModelAdapter):
    def __init__(self, responses: list[str]) -> None:
        self._responses = responses
        self.calls: list[ModelRequest] = []

    @property
    def provider_name(self) -> str:
        return "test_provider"

    @property
    def model_name(self) -> str:
        return "test_model"

    def generate(self, request: ModelRequest, on_output=None) -> ModelResponse:  # noqa: ANN001, ARG002
        self.calls.append(request)
        text = self._responses[min(len(self.calls) - 1, len(self._responses) - 1)]
        return ModelResponse(
            text=text,
            raw_payload={"text": text},
            usage=None,
            finish_reason="stop",
            provider=self.provider_name,
            model=self.model_name,
        )


def test_action_planner_repairs_validation_error_once(tmp_path: Path) -> None:
    prompt_file = tmp_path / "prompt.md"
    prompt_file.write_text("Return JSON only.", encoding="utf-8")

    invalid_plan = json.dumps(
        {
            "task_id": "ignored",
            "goal": "Inspect workspace.",
            "actions": [
                {
                    "action_type": "list_directory",
                    "args": {"path": "."},
                    "risk_level": "low",
                    "requires_confirmation": False,
                }
            ],
            "final_response_style": "concise",
            "planner_notes": "",
        },
        ensure_ascii=False,
    )
    repaired_plan = json.dumps(
        {
            "task_id": "ignored",
            "goal": "Inspect workspace.",
            "actions": [
                {
                    "action_type": "list_directory",
                    "args": {"path": "."},
                    "reason": "Inspect the workspace safely.",
                    "risk_level": "low",
                    "requires_confirmation": False,
                }
            ],
            "final_response_style": "concise",
            "planner_notes": "",
        },
        ensure_ascii=False,
    )

    adapter = RecordingAdapter([invalid_plan, repaired_plan])
    planner = ActionPlanner(model_adapter=adapter, prompt_file=prompt_file)

    result = planner.plan(task_id="task-1", instruction="show files", working_directory=str(tmp_path))

    assert result.plan.actions[0].reason == "Inspect the workspace safely."
    assert result.repair_applied is True
    assert len(adapter.calls) == 2
    assert "validation_error" in adapter.calls[1].prompt


def test_action_planner_includes_memory_context_in_task_input(tmp_path: Path) -> None:
    prompt_file = tmp_path / "prompt.md"
    prompt_file.write_text("Return JSON only.", encoding="utf-8")

    valid_plan = json.dumps(
        {
            "task_id": "task-2",
            "goal": "Inspect workspace.",
            "actions": [
                {
                    "action_type": "respond_only",
                    "args": {"message": "ok"},
                    "reason": "Respond safely.",
                    "risk_level": "low",
                    "requires_confirmation": False,
                }
            ],
            "final_response_style": "concise",
            "planner_notes": "",
        },
        ensure_ascii=False,
    )

    adapter = RecordingAdapter([valid_plan])
    planner = ActionPlanner(model_adapter=adapter, prompt_file=prompt_file)
    planner.plan(
        task_id="task-2",
        instruction="summarize repo",
        working_directory=str(tmp_path),
        session_summary={"goal": "understand repo"},
        project_memory_snippets=[{"source": "MEMORY.md", "text": "- repo is MiniClaw"}],
    )

    payload = json.loads(adapter.calls[0].prompt.split("\n", 1)[1])
    assert payload["session_summary"]["goal"] == "understand repo"
    assert payload["project_memory_snippets"][0]["source"] == "MEMORY.md"
