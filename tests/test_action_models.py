from pydantic import ValidationError

from raida.planner.action_models import ActionPlan


def test_action_plan_accepts_valid_actions() -> None:
    plan = ActionPlan.model_validate(
        {
            "task_id": "t1",
            "goal": "List files",
            "actions": [
                {
                    "action_type": "list_directory",
                    "args": {"path": "."},
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

