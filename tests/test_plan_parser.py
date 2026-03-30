import json

import pytest

from src.planner.plan_parser import PlanParseError, parse_action_plan, parse_action_plan_output


def _valid_plan_payload() -> dict:
    return {
        "task_id": "ignored",
        "goal": "Show files in the workspace.",
        "actions": [
            {
                "action_type": "list_directory",
                "args": {"path": "."},
                "reason": "Inspect workspace.",
                "risk_level": "low",
                "requires_confirmation": False,
            }
        ],
        "final_response_style": "concise",
        "planner_notes": "",
    }


def test_valid_action_plan_json_passes() -> None:
    raw = json.dumps(_valid_plan_payload(), ensure_ascii=False)
    plan = parse_action_plan(raw, task_id="task-123")
    assert plan.task_id == "task-123"
    assert plan.goal == "Show files in the workspace."
    assert plan.actions[0].action_type == "list_directory"


def test_schema_style_json_is_rejected() -> None:
    raw = json.dumps(
        {
            "task_id": "ignored",
            "goal": {"type": "string"},
            "actions": {"type": "array"},
            "properties": {"goal": {"type": "string"}},
            "required": ["goal", "actions"],
        }
    )
    with pytest.raises(PlanParseError) as exc_info:
        parse_action_plan(raw, task_id="task-1")
    assert exc_info.value.kind == "schema_like_output"
    assert "schema/contract" in str(exc_info.value)


def test_code_fenced_json_is_recovered() -> None:
    raw = f"""```json
{json.dumps(_valid_plan_payload(), ensure_ascii=False, indent=2)}
```"""
    parse_result = parse_action_plan_output(raw, task_id="task-123")
    assert parse_result.plan.task_id == "task-123"
    assert parse_result.cleanup_applied is True


def test_prose_around_json_is_recovered_when_unambiguous() -> None:
    payload = json.dumps(_valid_plan_payload(), ensure_ascii=False)
    raw = f"I will return a runtime plan now.\\n{payload}\\nDone."
    parse_result = parse_action_plan_output(raw, task_id="task-234")
    assert parse_result.plan.task_id == "task-234"
    assert parse_result.extracted_json.startswith("{")


def test_missing_actions_fails_with_clear_message() -> None:
    payload = _valid_plan_payload()
    payload.pop("actions")
    with pytest.raises(PlanParseError) as exc_info:
        parse_action_plan(json.dumps(payload), task_id="task-2")
    assert exc_info.value.kind == "missing_fields"
    assert "actions" in str(exc_info.value)


def test_goal_as_dict_fails_with_clear_message() -> None:
    payload = _valid_plan_payload()
    payload["goal"] = {"text": "Show files"}  # wrong runtime type
    with pytest.raises(PlanParseError) as exc_info:
        parse_action_plan(json.dumps(payload), task_id="task-3")
    assert exc_info.value.kind == "wrong_field_types"
    assert "goal" in str(exc_info.value)


def test_invalid_json_fails_clearly() -> None:
    with pytest.raises(PlanParseError) as exc_info:
        parse_action_plan("not json at all", task_id="task-4")
    assert exc_info.value.kind == "invalid_json"
