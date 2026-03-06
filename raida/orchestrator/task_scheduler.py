"""Background task scheduler and execution loop."""

from __future__ import annotations

import json
import queue
import threading
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from raida.executors.executor_router import ExecutorRouter
from raida.orchestrator.context_store import ContextStore
from raida.orchestrator.reporter import Reporter
from raida.orchestrator.task_manager import TaskManager
from raida.safety.safety_guard import SafetyGuard
from raida.utils.logger import get_logger

logger = get_logger(__name__)


class TaskScheduler:
    """
    Cooperative scheduler for task execution.

    Architecture decision:
    - A single worker thread simplifies ordering and safety confirmation handling.
    - Task state is persisted in SQLite + file context so execution can be resumed.
    """

    def __init__(
        self,
        task_manager: TaskManager,
        context_store: ContextStore,
        executor_router: ExecutorRouter,
        safety_guard: SafetyGuard,
        reporter: Reporter,
    ) -> None:
        self.task_manager = task_manager
        self.context_store = context_store
        self.executor_router = executor_router
        self.safety_guard = safety_guard
        self.reporter = reporter

        self._queue: queue.Queue[str] = queue.Queue()
        self._queue_lock = threading.Lock()
        self._queued: set[str] = set()
        self._stop_event = threading.Event()
        self._worker: Optional[threading.Thread] = None

    def start(self) -> None:
        if self._worker and self._worker.is_alive():
            return
        self._stop_event.clear()
        self._worker = threading.Thread(target=self._worker_loop, daemon=True, name="raida-task-worker")
        self._worker.start()
        logger.info("TaskScheduler started.")

    def stop(self) -> None:
        self._stop_event.set()
        if self._worker:
            self._worker.join(timeout=3)

    def submit_task(self, task_id: str) -> None:
        with self._queue_lock:
            if task_id in self._queued:
                return
            self._queued.add(task_id)
            self._queue.put(task_id)

    def pause_task(self, task_id: str) -> bool:
        task = self.task_manager.get_task(task_id)
        if not task:
            return False
        state = self.context_store.load_state(task_id)
        state["pause_requested"] = True
        self.context_store.save_state(task_id, state)
        self.task_manager.set_status(task_id, "pending", current_step="paused by user")
        self.task_manager.append_history(task_id, {"type": "control", "content": "pause requested"})
        return True

    def resume_task(self, task_id: str) -> bool:
        task = self.task_manager.get_task(task_id)
        if not task:
            return False
        state = self.context_store.load_state(task_id)
        state["pause_requested"] = False
        self.context_store.save_state(task_id, state)
        self.task_manager.set_status(task_id, "pending", current_step="resume requested")
        self.task_manager.append_history(task_id, {"type": "control", "content": "resume requested"})
        self.submit_task(task_id)
        return True

    def cancel_task(self, task_id: str) -> bool:
        task = self.task_manager.get_task(task_id)
        if not task:
            return False
        state = self.context_store.load_state(task_id)
        state["cancel_requested"] = True
        self.context_store.save_state(task_id, state)
        self.task_manager.set_status(task_id, "cancelled", current_step="cancelled by user")
        self.task_manager.append_history(task_id, {"type": "control", "content": "cancel requested"})
        return True

    def append_instruction(self, task_id: str, instruction: str) -> Tuple[bool, str]:
        task = self.task_manager.get_task(task_id)
        if not task:
            return False, "task not found"

        state = self.context_store.load_state(task_id)
        planned = self.executor_router.plan_actions(instruction)
        state["actions"].extend(planned)
        self.context_store.save_state(task_id, state)

        self.task_manager.append_history(
            task_id,
            {
                "type": "instruction",
                "role": "user",
                "content": instruction,
            },
        )
        self.context_store.append_conversation(task_id, "user", instruction)

        if task["status"] in {"completed", "failed", "cancelled"}:
            self.task_manager.set_status(task_id, "pending", current_step="appended new instruction")
        self.submit_task(task_id)
        return True, f"appended {len(planned)} action(s)"

    def confirm_latest_waiting(self, user_id: str, message: str) -> Tuple[bool, str]:
        if not self.safety_guard.is_confirm_text(message):
            return False, "confirmation rejected: reply must be exactly 'confirm'"

        task = self.task_manager.get_latest_waiting_confirmation_task(user_id)
        if not task:
            return False, "no task is waiting for confirmation"

        state = self.context_store.load_state(task["task_id"])
        state["confirmation_granted_for_cursor"] = state.get("cursor", 0)
        self.context_store.save_state(task["task_id"], state)
        self.task_manager.clear_pending_confirmation(task["task_id"])
        self.task_manager.set_status(task["task_id"], "pending", current_step="confirmation received")
        self.task_manager.append_history(task["task_id"], {"type": "control", "content": "confirmation received"})
        self.submit_task(task["task_id"])
        return True, f"confirmation accepted for task {task['task_id']}"

    def _worker_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                task_id = self._queue.get(timeout=0.5)
            except queue.Empty:
                continue

            with self._queue_lock:
                self._queued.discard(task_id)

            try:
                self._execute_task(task_id)
            except Exception as exc:  # pragma: no cover
                logger.exception("Task execution crashed for %s: %s", task_id, exc)
                task = self.task_manager.get_task(task_id)
                if task:
                    self.task_manager.set_status(task_id, "failed", current_step="execution crashed")
                    self.task_manager.append_history(task_id, {"type": "error", "content": str(exc)})
                    self.reporter.task_failed(task["user_id"], task_id, str(exc))

    def _execute_task(self, task_id: str) -> None:
        task = self.task_manager.get_task(task_id)
        if not task:
            logger.warning("Task %s was not found.", task_id)
            return

        if task["status"] == "cancelled":
            return

        self.context_store.init_task_context(task_id)
        self._ensure_task_plan(task)

        self.task_manager.set_status(task_id, "running", current_step="executing")
        self.reporter.task_started(task["user_id"], task_id)

        while True:
            task = self.task_manager.get_task(task_id)
            if not task:
                return

            state = self.context_store.load_state(task_id)
            actions: List[Dict[str, object]] = state.get("actions", [])
            cursor = int(state.get("cursor", 0))

            if state.get("cancel_requested"):
                self.task_manager.set_status(task_id, "cancelled", current_step="cancelled by user")
                self.reporter.task_update(task["user_id"], task_id, "Task cancelled.")
                return

            if state.get("pause_requested"):
                self.task_manager.set_status(task_id, "pending", current_step="paused by user")
                self.reporter.task_update(task["user_id"], task_id, "Task paused.")
                return

            if cursor >= len(actions):
                break

            action = actions[cursor]
            self.task_manager.update_current_step(task_id, f"action[{cursor}] {action.get('type', 'unknown')}")

            if self.safety_guard.require_confirmation(action):
                granted_cursor = state.get("confirmation_granted_for_cursor")
                if granted_cursor != cursor:
                    reason = self.safety_guard.reason_for_confirmation(action)
                    self.task_manager.set_pending_confirmation(task_id, action, reason)
                    self.task_manager.append_history(
                        task_id,
                        {"type": "safety", "content": "waiting confirmation", "reason": reason, "action": action},
                    )
                    self.reporter.waiting_confirmation(task["user_id"], task_id, reason)
                    return
                state["confirmation_granted_for_cursor"] = None
                self.context_store.save_state(task_id, state)

            success, result = self._execute_action(task, action)
            self.task_manager.append_history(
                task_id,
                {
                    "type": "action_result",
                    "action": action,
                    "success": success,
                    "summary": result.get("summary", ""),
                },
            )

            if not success:
                self.task_manager.set_status(task_id, "failed", current_step="action failed")
                self.reporter.task_failed(task["user_id"], task_id, str(result.get("summary", "unknown error")))
                return

            cursor += 1
            state = self.context_store.load_state(task_id)
            state["cursor"] = cursor
            self.context_store.save_state(task_id, state)

        summary = self._build_summary(task_id)
        self.task_manager.set_status(task_id, "completed", current_step="done")
        self.reporter.task_completed(task["user_id"], task_id, summary)

    def _ensure_task_plan(self, task: Dict[str, object]) -> None:
        task_id = str(task["task_id"])
        state = self.context_store.load_state(task_id)
        if state.get("actions"):
            return
        actions = self.executor_router.plan_actions(str(task["instruction"]))
        state["actions"] = actions
        state["cursor"] = 0
        state["cancel_requested"] = False
        state["pause_requested"] = False
        if task.get("working_directory"):
            state["working_directory"] = task["working_directory"]
        self.context_store.save_state(task_id, state)

    def _execute_action(self, task: Dict[str, object], action: Dict[str, object]) -> Tuple[bool, Dict[str, object]]:
        task_id = str(task["task_id"])
        user_id = str(task["user_id"])

        state = self.context_store.load_state(task_id)
        raw_cwd = str(state.get("working_directory") or task.get("working_directory") or "")
        cwd = Path(raw_cwd).resolve() if raw_cwd else None

        log_file_name = "execution.log"

        def on_output(line: str) -> None:
            self.context_store.append_log(task_id, log_file_name, line)

        result = self.executor_router.execute_action(action, working_directory=cwd, on_output=on_output)
        result_output = str(result.get("output", "")).strip()
        if result_output:
            self.context_store.append_log(task_id, log_file_name, result_output)

        summary = str(result.get("summary", ""))
        self.reporter.task_update(user_id, task_id, summary)

        artifacts = result.get("artifacts", [])
        for artifact in artifacts if isinstance(artifacts, list) else []:
            path = Path(str(artifact))
            if path.exists():
                self.reporter.maybe_send_path(user_id, path)

        self.context_store.append_conversation(task_id, "assistant", summary)
        return bool(result.get("success", False)), result

    def _build_summary(self, task_id: str) -> str:
        log_path = self.context_store.task_dir(task_id) / "logs" / "execution.log"
        if not log_path.exists():
            return "Task completed successfully."
        lines = log_path.read_text(encoding="utf-8", errors="ignore").splitlines()
        tail = lines[-20:] if len(lines) > 20 else lines
        if not tail:
            return "Task completed successfully."
        return "\n".join(tail)

