import json
from types import SimpleNamespace
from typing import Any, Dict, List

from src.config import Settings
from src.orchestrator.context_store import ContextStore
from src.orchestrator.reporter import Reporter
from src.orchestrator.task_manager import TaskManager
from src.orchestrator.task_scheduler import TaskScheduler
from src.planner.action_models import ActionPlan
from src.safety.safety_guard import SafetyGuard
from src.utils.command_runner import CommandResult


class DummyGateway:
    def __init__(self) -> None:
        self.messages: List[str] = []

    def send_message(self, user_id: str, text: str) -> None:  # noqa: ARG002
        self.messages.append(text)

    def send_image(self, user_id: str, image_path: str) -> None:  # noqa: ARG002
        return

    def send_file(self, user_id: str, file_path: str) -> None:  # noqa: ARG002
        return


class FakePlanner:
    def __init__(self, plan: ActionPlan) -> None:
        self.plan_payload = plan

    def plan(
        self,
        task_id: str,
        instruction: str,
        working_directory: str = "",
        recent_conversation=None,
        session_summary=None,
        project_memory_snippets=None,
    ):  # noqa: ANN001, ARG002
        return SimpleNamespace(
            plan=self.plan_payload,
            raw_output=json.dumps(self.plan_payload.model_dump(), ensure_ascii=False),
            cleaned_output=json.dumps(self.plan_payload.model_dump(), ensure_ascii=False),
            parsed_json=self.plan_payload.model_dump(),
            cleanup_applied=False,
            schema_like_detected=False,
            schema_like_signals=[],
            model_response=SimpleNamespace(provider="codex_cli", model="codex"),
        )


class FakeExecutorRouter:
    def __init__(self) -> None:
        self.calls = 0

    def execute_action(self, action: Dict[str, Any], working_directory, task_dir, on_output=None):  # noqa: ANN001, ARG002
        self.calls += 1
        if on_output:
            on_output(f"executed {action.get('action_type')}")
        return {
            "success": True,
            "status": "executed",
            "summary": "ok",
            "output": "ok",
            "artifacts": [],
            "metadata": {},
        }


def test_scheduler_denies_hard_blocked_actions(tmp_path) -> None:  # noqa: ANN001
    plan = ActionPlan.model_validate(
        {
            "task_id": "t-deny",
            "goal": "dangerous command",
            "actions": [
                {
                    "action_type": "run_command",
                    "args": {"command": "rm -rf /"},
                    "reason": "dangerous",
                    "risk_level": "critical",
                    "requires_confirmation": True,
                }
            ],
            "final_response_style": "concise",
            "planner_notes": "",
        }
    )

    settings = Settings(
        database_path=tmp_path / "src.db",
        task_data_dir=tmp_path / "tasks",
        allowed_workdirs=[tmp_path],
    )
    task_manager = TaskManager(settings.database_path)
    context_store = ContextStore(settings.task_data_dir)
    executor_router = FakeExecutorRouter()
    reporter = Reporter(DummyGateway())
    scheduler = TaskScheduler(
        task_manager,
        context_store,
        FakePlanner(plan),
        executor_router,
        SafetyGuard(settings=settings),
        reporter,
    )

    task = task_manager.create_task("tg_1", "dangerous", working_directory=str(tmp_path))
    scheduler._execute_task(task["task_id"])

    updated = task_manager.get_task(task["task_id"])
    assert updated is not None
    assert updated["status"] == "failed"
    assert executor_router.calls == 0

    execution_log = context_store.load_json_artifact(task["task_id"], "execution_log.json", default=[])
    assert execution_log[0]["status"] == "denied"
    assert execution_log[0]["safety_decision"] == "deny"
