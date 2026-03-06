import pytest

from raida.planner.plan_parser import PlanParseError, parse_action_plan


def test_parse_action_plan_from_fenced_json() -> None:
    raw = """
```json
{
  "task_id": "ignored",
  "goal": "Show files",
  "actions": [
    {
      "action_type": "list_directory",
      "args": {"path": "."},
      "reason": "Inspect workspace.",
      "risk_level": "low",
      "requires_confirmation": false
    }
  ],
  "final_response_style": "concise",
  "planner_notes": ""
}
```
"""
    plan = parse_action_plan(raw, task_id="task-123")
    assert plan.task_id == "task-123"
    assert plan.actions[0].action_type == "list_directory"


def test_parse_action_plan_invalid_payload() -> None:
    with pytest.raises(PlanParseError):
        parse_action_plan("not json at all", task_id="task-1")

