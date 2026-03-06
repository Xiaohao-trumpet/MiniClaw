import json
from types import SimpleNamespace
from typing import Any, Dict, List

from raida.config import Settings
from raida.orchestrator.context_store import ContextStore
from raida.orchestrator.reporter import Reporter
from raida.orchestrator.task_manager import TaskManager
from raida.orchestrator.task_scheduler import TaskScheduler
from raida.planner.action_models import ActionPlan
from raida.safety.safety_guard import SafetyGuard
from raida.utils.command_runner import CommandResult


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
    def __init__(self, plans: List[ActionPlan]) -> None:
        self._plans = plans
        self.calls = 0

    def plan(self, task_id: str, instruction: str, working_directory: str = "", recent_conversation=None):  # noqa: ANN001, ARG002
        plan = self._plans[min(self.calls, len(self._plans) - 1)]
        self.calls += 1
        return SimpleNamespace(
            plan=plan,
            raw_output=json.dumps(plan.model_dump(), ensure_ascii=False),
            backend_result=CommandResult(
                command="codex exec",
                returncode=0,
                stdout="",
                stderr="",
                duration_seconds=0.1,
                timed_out=False,
            ),
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


def _build_scheduler(tmp_path, plan: ActionPlan) -> tuple[TaskScheduler, TaskManager, ContextStore, FakeExecutorRouter]:  # noqa: ANN001
    settings = Settings(
        database_path=tmp_path / "raida.db",
        task_data_dir=tmp_path / "tasks",
        allowed_workdirs=[tmp_path],
    )
    task_manager = TaskManager(settings.database_path)
    context_store = ContextStore(settings.task_data_dir)
    planner = FakePlanner([plan])
    executor_router = FakeExecutorRouter()
    safety_guard = SafetyGuard(settings=settings)
    reporter = Reporter(DummyGateway())
    scheduler = TaskScheduler(task_manager, context_store, planner, executor_router, safety_guard, reporter)
    return scheduler, task_manager, context_store, executor_router


def test_task_transitions_to_completed(tmp_path) -> None:  # noqa: ANN001
    plan = ActionPlan.model_validate(
        {
            "task_id": "t1",
            "goal": "Respond only",
            "actions": [
                {
                    "action_type": "respond_only",
                    "args": {"message": "analysis"},
                    "reason": "User asked for analysis.",
                    "risk_level": "low",
                    "requires_confirmation": False,
                }
            ],
            "final_response_style": "concise",
            "planner_notes": "",
        }
    )
    scheduler, task_manager, context_store, executor_router = _build_scheduler(tmp_path, plan)
    task = task_manager.create_task("tg_1", "inspect project", working_directory=str(tmp_path))
    scheduler._execute_task(task["task_id"])

    updated = task_manager.get_task(task["task_id"])
    assert updated is not None
    assert updated["status"] == "completed"
    assert executor_router.calls == 1
    assert context_store.artifact_path(task["task_id"], "plan.json").exists()
    assert context_store.artifact_path(task["task_id"], "execution_log.json").exists()
    assert context_store.artifact_path(task["task_id"], "summary.txt").exists()


def test_task_waits_for_confirmation_then_resumes(tmp_path) -> None:  # noqa: ANN001
    plan = ActionPlan.model_validate(
        {
            "task_id": "t2",
            "goal": "Push changes",
            "actions": [
                {
                    "action_type": "run_command",
                    "args": {"command": "git push origin main"},
                    "reason": "User requested push.",
                    "risk_level": "medium",
                    "requires_confirmation": False,
                }
            ],
            "final_response_style": "concise",
            "planner_notes": "",
        }
    )
    scheduler, task_manager, _, executor_router = _build_scheduler(tmp_path, plan)
    task = task_manager.create_task("tg_2", "push changes", working_directory=str(tmp_path))
    scheduler._execute_task(task["task_id"])

    waiting = task_manager.get_task(task["task_id"])
    assert waiting is not None
    assert waiting["status"] == "awaiting_confirmation"
    assert executor_router.calls == 0

    ok, _ = scheduler.confirm_latest_waiting("tg_2", "confirm")
    assert ok is True
    scheduler._execute_task(task["task_id"])

    done = task_manager.get_task(task["task_id"])
    assert done is not None
    assert done["status"] == "completed"
    assert executor_router.calls == 1

