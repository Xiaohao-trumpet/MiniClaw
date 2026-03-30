"""Background task scheduler and execution loop."""

from __future__ import annotations

import queue
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from src.executors.executor_router import ExecutorRouter
from src.orchestrator.context_store import ContextStore
from src.orchestrator.reporter import Reporter
from src.orchestrator.task_manager import TaskManager
from src.planner.action_models import ActionPlan
from src.planner.codex_planner import CodexPlanner, PlannerExecutionError
from src.safety.safety_guard import SafetyDecision, SafetyGuard
from src.utils.execution_logging import build_execution_record
from src.utils.logger import get_logger

logger = get_logger(__name__)


class TaskScheduler:
    """Single-worker task scheduler with planner/executor split."""

    OUTPUT_ACTIONS = {
        "list_directory",
        "read_file",
        "run_command",
        "find_files",
        "search_text",
        "read_multiple_files",
        "get_system_info",
    }

    def __init__(
        self,
        task_manager: TaskManager,
        context_store: ContextStore,
        planner: CodexPlanner,
        executor_router: ExecutorRouter,
        safety_guard: SafetyGuard,
        reporter: Reporter,
    ) -> None:
        self.task_manager = task_manager
        self.context_store = context_store
        self.planner = planner
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
        self._worker = threading.Thread(target=self._worker_loop, daemon=True, name="miniclaw-task-worker")
        self._worker.start()
        logger.info("event=scheduler_started")

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
        pending_instructions = state.get("pending_instructions", [])
        if not isinstance(pending_instructions, list):
            pending_instructions = []
        pending_instructions.append(instruction)
        state["pending_instructions"] = pending_instructions
        self.context_store.save_state(task_id, state)

        self.task_manager.append_history(
            task_id,
            {"type": "instruction", "role": "user", "content": instruction},
        )
        self.context_store.append_conversation(task_id, "user", instruction)

        if task["status"] in {"completed", "failed", "cancelled"}:
            self.task_manager.set_status(task_id, "pending", current_step="appended new instruction")
        self.submit_task(task_id)
        return True, "instruction appended for planning"

    def confirm_latest_waiting(self, user_id: str, message: str) -> Tuple[bool, str]:
        if not self.safety_guard.is_confirm_text(message):
            return False, "confirmation rejected: reply with confirm or /confirm <task_id>"

        explicit_task_id = self._extract_confirm_task_id(message)
        task = (
            self.task_manager.get_waiting_confirmation_task(user_id, explicit_task_id)
            if explicit_task_id
            else self.task_manager.get_latest_waiting_confirmation_task(user_id)
        )
        if not task:
            return False, "no task is waiting for confirmation"

        task_id = str(task["task_id"])
        state = self.context_store.load_state(task_id)
        state["confirmation_granted_for_cursor"] = int(state.get("cursor", 0))
        self.context_store.save_state(task_id, state)
        self.task_manager.clear_pending_confirmation(task_id)
        self.task_manager.set_status(task_id, "pending", current_step="confirmation received")
        self.task_manager.append_history(task_id, {"type": "control", "content": "confirmation received"})
        self.submit_task(task_id)
        return True, f"confirmation accepted for task {task_id}"

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
                logger.exception("event=task_crashed task_id=%s error=%s", task_id, exc)
                task = self.task_manager.get_task(task_id)
                if task:
                    self.task_manager.set_status(task_id, "failed", current_step="execution crashed")
                    self.task_manager.append_history(task_id, {"type": "error", "content": str(exc)})
                    self.reporter.task_failed(str(task["user_id"]), task_id, str(exc))

    def _execute_task(self, task_id: str) -> None:
        task = self.task_manager.get_task(task_id)
        if not task:
            logger.warning("event=task_not_found task_id=%s", task_id)
            return
        if task["status"] == "cancelled":
            return

        task_id = str(task["task_id"])
        user_id = str(task["user_id"])
        task_dir = self.context_store.init_task_context(task_id)

        state = self.context_store.load_state(task_id)
        if bool(state.get("cancel_requested")):
            self.task_manager.set_status(task_id, "cancelled", current_step="cancelled by user")
            self.reporter.action_result(user_id, task_id, "cancelled", "Task cancelled by user.")
            return
        if bool(state.get("pause_requested")):
            self.task_manager.set_status(task_id, "pending", current_step="paused by user")
            self.reporter.action_result(user_id, task_id, "paused", "Task paused.")
            return

        if not self._ensure_plan_ready(task, state):
            return

        while True:
            task = self.task_manager.get_task(task_id)
            if not task:
                return
            state = self.context_store.load_state(task_id)
            actions = state.get("actions", [])
            if not isinstance(actions, list):
                actions = []
            cursor = int(state.get("cursor", 0))

            if cursor >= len(actions):
                break
            if bool(state.get("cancel_requested")):
                self.task_manager.set_status(task_id, "cancelled", current_step="cancelled by user")
                self.reporter.action_result(user_id, task_id, "cancelled", "Task cancelled by user.")
                return
            if bool(state.get("pause_requested")):
                self.task_manager.set_status(task_id, "pending", current_step="paused by user")
                self.reporter.action_result(user_id, task_id, "paused", "Task paused.")
                return

            action = actions[cursor]
            action_type = str(action.get("action_type", "unknown"))
            self.task_manager.set_status(task_id, "running", current_step=f"action[{cursor}] {action_type}")
            self.reporter.action_started(user_id, task_id, cursor + 1, len(actions), action_type)
            logger.info(
                "event=action_started task_id=%s index=%s action_type=%s",
                task_id,
                cursor,
                action_type,
            )

            current_cwd = self._resolve_task_working_directory(task, state)
            safety_decision = self.safety_guard.evaluate_action(action, working_directory=current_cwd)
            self.task_manager.append_history(
                task_id,
                {
                    "type": "safety_decision",
                    "action": action,
                    "decision": safety_decision.decision,
                    "reason": safety_decision.reason,
                    "preview": safety_decision.preview,
                    "category": safety_decision.category,
                },
            )

            if safety_decision.decision == "deny":
                self._handle_denied_action(task_id, user_id, cursor, action, safety_decision)
                return

            if safety_decision.decision == "confirm":
                granted_cursor = state.get("confirmation_granted_for_cursor")
                if granted_cursor != cursor:
                    self.task_manager.set_pending_confirmation(
                        task_id,
                        action,
                        f"{safety_decision.reason}\n{safety_decision.preview}".strip(),
                    )
                    self._record_action(
                        task_id,
                        cursor,
                        action,
                        status="blocked",
                        summary=safety_decision.reason,
                        success=False,
                        safety_decision=safety_decision,
                    )
                    self.reporter.waiting_confirmation(user_id, task_id, safety_decision.reason, safety_decision.preview)
                    logger.info(
                        "event=awaiting_confirmation task_id=%s index=%s reason=%s",
                        task_id,
                        cursor,
                        safety_decision.reason,
                    )
                    return
                state["confirmation_granted_for_cursor"] = None
                self.context_store.save_state(task_id, state)
                if action_type == "request_confirmation":
                    summary = "Confirmation checkpoint acknowledged."
                    self._record_action(
                        task_id,
                        cursor,
                        action,
                        status="skipped",
                        summary=summary,
                        success=True,
                        safety_decision=safety_decision,
                    )
                    self.reporter.action_result(user_id, task_id, "skipped", summary)
                    state = self.context_store.load_state(task_id)
                    state["cursor"] = cursor + 1
                    self.context_store.save_state(task_id, state)
                    continue

            success, result = self._execute_action(task, action, cursor, task_dir, safety_decision=safety_decision)
            self.task_manager.append_history(
                task_id,
                {
                    "type": "action_result",
                    "action": action,
                    "success": success,
                    "status": result.get("status", ""),
                    "summary": result.get("summary", ""),
                },
            )

            if not success:
                self.task_manager.set_status(task_id, "failed", current_step="action failed")
                self.reporter.task_failed(user_id, task_id, str(result.get("summary", "unknown error")))
                self._write_final_summary(task_id, success=False)
                return

            state = self.context_store.load_state(task_id)
            state["cursor"] = cursor + 1
            self.context_store.save_state(task_id, state)

        self.task_manager.set_status(task_id, "completed", current_step="done")
        summary = self._write_final_summary(task_id, success=True)
        final_response = self._build_final_response(task)
        self.reporter.task_completed(user_id, task_id, final_response or summary)

    def _ensure_plan_ready(self, task: Dict[str, Any], state: Dict[str, Any]) -> bool:
        task_id = str(task["task_id"])
        user_id = str(task["user_id"])
        instruction = str(task["instruction"])
        working_directory = str(state.get("working_directory") or task.get("working_directory") or "")

        actions = state.get("actions", [])
        pending_instructions = state.get("pending_instructions", [])
        if not isinstance(actions, list):
            actions = []
        if not isinstance(pending_instructions, list):
            pending_instructions = []

        planning_inputs: List[str] = []
        if not actions:
            planning_inputs.append(instruction)
        planning_inputs.extend(str(item) for item in pending_instructions if str(item).strip())

        if not planning_inputs:
            return True

        state["pending_instructions"] = []
        self.context_store.save_state(task_id, state)

        for plan_input in planning_inputs:
            self.task_manager.set_status(task_id, "planning", current_step="planning actions")
            self.reporter.planning_started(user_id, task_id)
            logger.info("event=planning_started task_id=%s input=%s", task_id, plan_input)
            try:
                planner_result = self.planner.plan(
                    task_id=task_id,
                    instruction=plan_input,
                    working_directory=working_directory,
                )
            except PlannerExecutionError as exc:
                self.task_manager.set_status(task_id, "failed", current_step="planning failed")
                self.task_manager.append_history(task_id, {"type": "planning_error", "content": str(exc)})
                raw_output = exc.raw_output if hasattr(exc, "raw_output") else ""
                cleaned_output = exc.cleaned_output if hasattr(exc, "cleaned_output") else ""
                parsed_json = exc.parsed_json if hasattr(exc, "parsed_json") else None
                error_kind = exc.error_kind if hasattr(exc, "error_kind") else "unknown"
                schema_signals = exc.schema_like_signals if hasattr(exc, "schema_like_signals") else []

                self.context_store.write_text_artifact(task_id, "planner_raw.txt", raw_output or str(exc))
                self.context_store.write_text_artifact(task_id, "planner_raw_output.txt", raw_output or str(exc))
                self.context_store.write_text_artifact(task_id, "planner_cleaned.txt", cleaned_output or "")
                if isinstance(parsed_json, dict):
                    self.context_store.write_json_artifact(task_id, "plan.json", parsed_json)
                error_text = (
                    f"kind: {error_kind}\n"
                    f"message: {str(exc)}\n"
                    f"schema_like_detected: {bool(getattr(exc, 'schema_like_detected', False))}\n"
                    f"schema_signals: {'; '.join(schema_signals[:8])}\n"
                )
                self.context_store.write_text_artifact(task_id, "planner_error.txt", error_text)
                self.reporter.task_failed(user_id, task_id, f"Planning failed: {exc}")
                logger.warning(
                    "event=planning_failed task_id=%s kind=%s cleanup_applied=%s schema_like_detected=%s error=%s",
                    task_id,
                    error_kind,
                    bool(getattr(exc, "cleanup_applied", False)),
                    bool(getattr(exc, "schema_like_detected", False)),
                    exc,
                )
                return False

            plan = planner_result.plan
            self._append_plan(task_id, plan)
            self.context_store.write_text_artifact(task_id, "planner_raw.txt", planner_result.raw_output)
            self.context_store.write_text_artifact(task_id, "planner_raw_output.txt", planner_result.raw_output)
            self.context_store.write_text_artifact(task_id, "planner_cleaned.txt", planner_result.cleaned_output)
            self.context_store.write_json_artifact(task_id, "plan.json", planner_result.parsed_json)
            if getattr(planner_result, "repair_applied", False):
                self.context_store.write_text_artifact(task_id, "planner_repaired_output.txt", planner_result.cleaned_output)
            normalization_notes = getattr(planner_result, "normalization_notes", [])
            if isinstance(normalization_notes, list) and normalization_notes:
                self.context_store.write_text_artifact(
                    task_id,
                    "planner_normalization_notes.txt",
                    "\n".join(str(item) for item in normalization_notes),
                )
            self.reporter.plan_accepted(user_id, task_id, plan)
            model_response = getattr(planner_result, "model_response", None)
            provider = getattr(model_response, "provider", "")
            model = getattr(model_response, "model", "")
            logger.info(
                "event=plan_accepted task_id=%s actions=%s cleanup_applied=%s schema_like_detected=%s normalization_applied=%s repair_applied=%s provider=%s model=%s",
                task_id,
                len(plan.actions),
                planner_result.cleanup_applied,
                planner_result.schema_like_detected,
                getattr(planner_result, "normalization_applied", False),
                getattr(planner_result, "repair_applied", False),
                provider,
                model,
            )
        return True

    def _append_plan(self, task_id: str, plan: ActionPlan) -> None:
        state = self.context_store.load_state(task_id)
        actions = state.get("actions", [])
        if not isinstance(actions, list):
            actions = []
        for item in plan.actions:
            actions.append(item.model_dump())
        state["actions"] = actions
        state.setdefault("cursor", 0)
        state.setdefault("cancel_requested", False)
        state.setdefault("pause_requested", False)
        self.context_store.save_state(task_id, state)

        artifact = {
            "task_id": plan.task_id,
            "goal": plan.goal,
            "actions": actions,
            "final_response_style": plan.final_response_style,
            "planner_notes": plan.planner_notes,
        }
        self.context_store.write_json_artifact(task_id, "execution_plan.json", artifact)

    def _execute_action(
        self,
        task: Dict[str, Any],
        action: Dict[str, Any],
        cursor: int,
        task_dir: Path,
        *,
        safety_decision: SafetyDecision,
    ) -> Tuple[bool, Dict[str, Any]]:
        task_id = str(task["task_id"])
        user_id = str(task["user_id"])

        state = self.context_store.load_state(task_id)
        cwd = self._resolve_task_working_directory(task, state)

        def on_output(line: str) -> None:
            self.context_store.append_log(task_id, "execution.log", line)

        result = self.executor_router.execute_action(
            action=action,
            working_directory=cwd,
            task_dir=task_dir,
            on_output=on_output,
        )

        output = str(result.get("output", "")).strip()
        if output:
            self.context_store.append_log(task_id, "execution.log", output)

        summary = str(result.get("summary", ""))
        status = str(result.get("status", "executed"))
        success = bool(result.get("success", False))
        logger.info(
            "event=action_result task_id=%s index=%s action_type=%s status=%s success=%s",
            task_id,
            cursor,
            str(action.get("action_type", "")),
            status,
            success,
        )
        self._record_action(
            task_id,
            cursor,
            action,
            status=status,
            summary=summary,
            success=success,
            result=result,
            safety_decision=safety_decision,
        )
        self.reporter.action_result(user_id, task_id, status, summary)
        action_type = str(action.get("action_type", ""))
        if output and action_type in self.OUTPUT_ACTIONS:
            self.reporter.action_output(user_id, task_id, action_type, output)

        artifacts = result.get("artifacts", [])
        if isinstance(artifacts, list):
            for artifact in artifacts:
                path = Path(str(artifact))
                if path.exists():
                    self.reporter.maybe_send_path(user_id, path)

        self.context_store.append_conversation(task_id, "assistant", summary)
        return success, result

    def _handle_denied_action(
        self,
        task_id: str,
        user_id: str,
        cursor: int,
        action: Dict[str, Any],
        safety_decision: SafetyDecision,
    ) -> None:
        summary = f"{safety_decision.reason} Preview: {safety_decision.preview}".strip()
        self._record_action(
            task_id,
            cursor,
            action,
            status="denied",
            summary=safety_decision.reason,
            success=False,
            safety_decision=safety_decision,
        )
        self.task_manager.set_status(task_id, "failed", current_step="action denied")
        self.task_manager.append_history(
            task_id,
            {
                "type": "action_denied",
                "action": action,
                "reason": safety_decision.reason,
                "preview": safety_decision.preview,
            },
        )
        self.reporter.action_result(user_id, task_id, "denied", summary)
        self.reporter.task_failed(user_id, task_id, safety_decision.reason)
        self._write_final_summary(task_id, success=False)

    def _record_action(
        self,
        task_id: str,
        cursor: int,
        action: Dict[str, Any],
        status: str,
        summary: str,
        success: bool,
        result: Optional[Dict[str, Any]] = None,
        safety_decision: Optional[SafetyDecision] = None,
    ) -> None:
        record = build_execution_record(
            index=cursor,
            action=action,
            status=status,
            summary=summary,
            success=success,
            metadata=(result or {}).get("metadata", {}) if result else {},
            safety_decision=safety_decision,
        )
        self.context_store.append_execution_record(task_id, record)

    def _write_final_summary(self, task_id: str, success: bool) -> str:
        execution_log = self.context_store.load_json_artifact(task_id, "execution_log.json", default=[])
        records = execution_log if isinstance(execution_log, list) else []
        counts = {
            "planned": len(self.context_store.load_state(task_id).get("actions", [])),
            "executed": 0,
            "successful": 0,
            "failed": 0,
            "blocked": 0,
            "denied": 0,
            "skipped": 0,
        }
        for item in records:
            if not isinstance(item, dict):
                continue
            status = str(item.get("status", ""))
            if status == "executed":
                counts["executed"] += 1
                if bool(item.get("success")):
                    counts["successful"] += 1
            elif status == "failed":
                counts["failed"] += 1
            elif status == "blocked":
                counts["blocked"] += 1
            elif status == "denied":
                counts["denied"] += 1
            elif status == "skipped":
                counts["skipped"] += 1

        if not success and counts["failed"] == 0 and counts["denied"] == 0:
            counts["failed"] = 1

        summary = Reporter.build_final_summary(counts=counts, suggested_next_steps="")
        self.context_store.write_text_artifact(task_id, "summary.txt", summary)
        return summary

    def _build_final_response(self, task: Dict[str, Any]) -> str:
        task_id = str(task["task_id"])
        state = self.context_store.load_state(task_id)
        working_directory = str(state.get("working_directory") or task.get("working_directory") or "")
        plan_artifact = self.context_store.load_json_artifact(task_id, "execution_plan.json", default={})
        final_response_style = "concise"
        if isinstance(plan_artifact, dict):
            final_response_style = str(plan_artifact.get("final_response_style", "concise") or "concise")

        execution_log_path = self.context_store.task_dir(task_id) / "logs" / "execution.log"
        execution_log_text = ""
        if execution_log_path.exists():
            execution_log_text = execution_log_path.read_text(encoding="utf-8", errors="ignore").strip()
        execution_records = self.context_store.load_json_artifact(task_id, "execution_log.json", default=[])
        final_summary_path = self.context_store.task_dir(task_id) / "summary.txt"
        final_summary = ""
        if final_summary_path.exists():
            final_summary = final_summary_path.read_text(encoding="utf-8", errors="ignore").strip()

        summarize_execution = getattr(self.planner, "summarize_execution", None)
        if callable(summarize_execution) and (execution_log_text or isinstance(execution_records, list)):
            try:
                response = str(
                    summarize_execution(
                        task_id=task_id,
                        instruction=str(task.get("instruction", "")),
                        execution_log=execution_log_text,
                        execution_records=execution_records if isinstance(execution_records, list) else [],
                        final_summary=final_summary,
                        working_directory=working_directory,
                        final_response_style=final_response_style,
                    )
                ).strip()
            except Exception as exc:  # pragma: no cover - fallback path
                logger.warning("event=final_response_failed task_id=%s error=%s", task_id, exc)
            else:
                if response:
                    self.context_store.write_text_artifact(task_id, "final_response.txt", response)
                    return response

        if isinstance(execution_records, list):
            for item in reversed(execution_records):
                if not isinstance(item, dict):
                    continue
                if str(item.get("action_type", "")) == "respond_only" and bool(item.get("success")):
                    response = str(item.get("summary", "")).strip()
                    if response:
                        self.context_store.write_text_artifact(task_id, "final_response.txt", response)
                        return response

        return ""

    @staticmethod
    def _extract_confirm_task_id(message: str) -> str:
        text = message.strip()
        if not text.lower().startswith("/confirm"):
            return ""
        parts = text.split(maxsplit=1)
        if len(parts) < 2:
            return ""
        return parts[1].strip()

    @staticmethod
    def _resolve_task_working_directory(task: Dict[str, Any], state: Dict[str, Any]) -> Path | None:
        raw_cwd = str(state.get("working_directory") or task.get("working_directory") or "")
        return Path(raw_cwd).resolve() if raw_cwd else None
