from pydantic import ValidationError

from src.planner.action_models import ActionPlan


def test_action_plan_accepts_structured_tool_actions() -> None:
    plan = ActionPlan.model_validate(
        {
            "task_id": "t1",
            "goal": "Inspect project",
            "actions": [
                {
                    "action_type": "find_files",
                    "args": {"path": ".", "pattern": "*.py"},
                    "reason": "Gather context.",
                    "risk_level": "low",
                    "requires_confirmation": False,
                }
            ],
            "final_response_style": "concise",
            "planner_notes": "",
        }
    )
    assert plan.task_id == "t1"
    assert len(plan.actions) == 1
    assert plan.actions[0].action_type == "find_files"


def test_action_plan_rejects_missing_required_args() -> None:
    try:
        ActionPlan.model_validate(
            {
                "task_id": "t2",
                "goal": "Run command",
                "actions": [
                    {
                        "action_type": "run_command",
                        "args": {},
                        "reason": "Do work.",
                        "risk_level": "low",
                        "requires_confirmation": False,
                    }
                ],
            }
        )
    except ValidationError:
        return
    raise AssertionError("Expected schema validation to fail for missing command arg.")


def test_action_plan_requires_paths_for_read_multiple_files() -> None:
    try:
        ActionPlan.model_validate(
            {
                "task_id": "t3",
                "goal": "Read files",
                "actions": [
                    {
                        "action_type": "read_multiple_files",
                        "args": {},
                        "reason": "Read files.",
                        "risk_level": "low",
                        "requires_confirmation": False,
                    }
                ],
            }
        )
    except ValidationError:
        return
    raise AssertionError("Expected schema validation to fail for missing paths arg.")
