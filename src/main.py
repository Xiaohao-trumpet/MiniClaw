"""MiniClaw FastAPI service entrypoint."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Optional, Tuple

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from src.config import get_settings, validate_settings
from src.executors.desktop_executor import DesktopExecutor
from src.executors.executor_router import ExecutorRouter
from src.executors.system_executor import SystemExecutor
from src.gateway.message_gateway import MessageGateway
from src.gateway.telegram_adapter import (
    MockTelegramAdapter,
    TelegramAdapter,
    TelegramBotApiAdapter,
)
from src.models.factory import build_model_adapter
from src.orchestrator.context_store import ContextStore
from src.orchestrator.reporter import Reporter
from src.orchestrator.session_service import SessionService
from src.orchestrator.task_manager import TaskManager
from src.orchestrator.task_scheduler import TaskScheduler
from src.planner.codex_planner import ActionPlanner
from src.safety.safety_guard import SafetyGuard
from src.utils.command_runner import CommandRunner
from src.utils.logger import get_logger, setup_logging

settings = get_settings()
setup_logging(settings.log_level)
logger = get_logger(__name__)

_TELEGRAM_OFFSET_KEY = "telegram_next_update_offset"

command_runner = CommandRunner(shell_executable=settings.shell_executable)
task_manager = TaskManager(settings.database_path)


def _load_telegram_offset() -> Optional[int]:
    return task_manager.get_runtime_state_int(_TELEGRAM_OFFSET_KEY)


def _save_telegram_offset(offset: int) -> None:
    task_manager.set_runtime_state(_TELEGRAM_OFFSET_KEY, str(offset))


def _build_adapter() -> TelegramAdapter:
    if settings.telegram_bot_token.strip():
        return TelegramBotApiAdapter(
            settings.telegram_bot_token,
            request_timeout_seconds=30,
            poll_timeout_seconds=settings.telegram_poll_timeout_seconds,
            poll_retry_seconds=settings.telegram_poll_retry_seconds,
            initial_update_offset=_load_telegram_offset(),
            offset_commit=_save_telegram_offset,
        )
    logger.warning("SRC_TELEGRAM_BOT_TOKEN is empty. Falling back to MockTelegramAdapter.")
    return MockTelegramAdapter()


telegram_adapter = _build_adapter()
gateway = MessageGateway(telegram_adapter)
context_store = ContextStore(settings.task_data_dir, settings.session_data_dir)
session_service = SessionService(
    task_manager,
    context_store,
    auto_create_on_run=settings.auto_create_session_on_run,
)
model_adapter = build_model_adapter(settings, command_runner=command_runner)
planner = ActionPlanner(
    model_adapter=model_adapter,
    prompt_file=settings.planner_prompt_file,
    temperature=settings.model.temperature,
)
system_executor = SystemExecutor(settings=settings, command_runner=command_runner)
desktop_executor = DesktopExecutor()
executor_router = ExecutorRouter(system_executor=system_executor, desktop_executor=desktop_executor)
safety_guard = SafetyGuard(settings=settings)
reporter = Reporter(gateway)
scheduler = TaskScheduler(
    task_manager,
    context_store,
    planner,
    executor_router,
    safety_guard,
    reporter,
    session_recent_turns=settings.session_recent_turns,
)

_allowed_user_ids = {
    f"tg_{chat_id}" if not chat_id.startswith("tg_") else chat_id
    for chat_id in settings.telegram_allowed_chat_ids
}


class CreateTaskRequest(BaseModel):
    user_id: str
    instruction: str
    working_directory: str = ""
    session_id: str = ""


class AppendInstructionRequest(BaseModel):
    instruction: str


class UserConfirmRequest(BaseModel):
    user_id: str
    message: str = "confirm"


class CreateSessionRequest(BaseModel):
    user_id: str
    title: str = ""
    working_directory: str = ""


class ActivateSessionRequest(BaseModel):
    user_id: str


class TelegramMockMessageRequest(BaseModel):
    user_id: str = Field(..., min_length=1)
    message: str = Field(..., min_length=1)


def _parse_command(raw: str) -> Tuple[str, str]:
    text = raw.strip()
    if not text.startswith("/"):
        return "", ""
    parts = text.split(maxsplit=1)
    command = parts[0][1:].split("@", maxsplit=1)[0].lower()
    args = parts[1].strip() if len(parts) > 1 else ""
    return command, args


def _help_text() -> str:
    register_usage = "/register <invite_code>" if settings.telegram_invite_code.strip() else "/register"
    return (
        "[MiniClaw] Telegram commands:\n"
        "/start - show onboarding\n"
        f"{register_usage} - activate account\n"
        "/run <instruction> - create a task\n"
        "/sessions - list your sessions\n"
        "/session - show current session\n"
        "/session new [title] - create and switch to a new session\n"
        "/session use <session_id> - switch active session\n"
        "/session show [session_id] - show session detail\n"
        "/details <task_id> - send full planning/execution artifacts\n"
        "/pause <task_id> | /resume <task_id> | /cancel <task_id>\n"
        "/append <task_id> <instruction>\n"
        "/tasks - list your latest tasks\n"
        "/task <task_id> - show task status\n"
        "confirm or /confirm <task_id> - confirm risky action"
    )


def _resolve_task_working_directory(working_directory: str) -> str:
    candidate = working_directory.strip()
    if candidate:
        return candidate
    if settings.allowed_workdirs:
        return str(settings.allowed_workdirs[0].resolve())
    return str(Path.cwd())


def _welcome_text(user_id: str) -> str:
    status = task_manager.ensure_user(user_id).get("status", "pending")
    reg_tip = (
        ("send /register <invite_code>" if settings.telegram_invite_code.strip() else "send /register")
        if settings.telegram_require_registration
        else "registration not required"
    )
    return (
        "[MiniClaw] Welcome.\n"
        f"Current status: {status}.\n"
        f"To activate: {reg_tip}.\n"
        "Then send: /run inspect the current project and summarize its entrypoints"
    )


def _is_user_allowed(user_id: str) -> bool:
    if not _allowed_user_ids:
        return True
    return user_id in _allowed_user_ids


def _handle_register(user_id: str, args: str) -> dict:
    code = args.strip()
    expected = settings.telegram_invite_code.strip()

    if expected:
        if not code:
            msg = "register usage: /register <invite_code>"
            gateway.send_message(user_id, f"[MiniClaw] {msg}")
            return {"ok": False, "detail": msg}
        if code != expected:
            msg = "invalid invite code"
            gateway.send_message(user_id, f"[MiniClaw] {msg}")
            return {"ok": False, "detail": msg}

    task_manager.activate_user(user_id, invite_code_used=code if code else None)
    msg = "registration completed"
    gateway.send_message(user_id, f"[MiniClaw] {msg}. You can now use /run <instruction>.")
    return {"ok": True, "detail": msg}


def _ensure_active_user(user_id: str) -> Tuple[bool, str]:
    user = task_manager.ensure_user(user_id)
    status = str(user.get("status", "pending"))

    if status == "blocked":
        return False, "user is blocked"

    if status == "active":
        task_manager.touch_user(user_id)
        return True, "active"

    if not settings.telegram_require_registration:
        task_manager.activate_user(user_id)
        task_manager.touch_user(user_id)
        return True, "auto-activated"

    return False, (
        "user not registered; send /register <invite_code>"
        if settings.telegram_invite_code.strip()
        else "user not registered; send /register"
    )


def _list_user_tasks(user_id: str, limit: int = 10) -> dict:
    tasks = task_manager.list_tasks(user_id=user_id, limit=limit)
    if not tasks:
        gateway.send_message(user_id, "[MiniClaw] no tasks yet.")
        return {"ok": True, "detail": "no tasks"}

    lines = ["[MiniClaw] latest tasks:"]
    for item in tasks[:limit]:
        lines.append(
            f"- {item['task_id']} | {item['status']} | {item['current_step']} | session={item.get('session_id', '')}"
        )
    gateway.send_message(user_id, "\n".join(lines))
    return {"ok": True, "detail": "tasks listed"}


def _get_user_task(user_id: str, task_id: str) -> dict:
    task = task_manager.get_task(task_id)
    if task is None or str(task.get("user_id")) != user_id:
        msg = "task not found"
        gateway.send_message(user_id, f"[MiniClaw] {msg}: {task_id}")
        return {"ok": False, "detail": msg, "task_id": task_id}

    gateway.send_message(
        user_id,
        (
            f"[MiniClaw] task_id: {task['task_id']}\n"
            f"session_id: {task.get('session_id', '')}\n"
            f"status: {task['status']}\n"
            f"current_step: {task['current_step']}\n"
            f"instruction: {task['instruction']}"
        ),
    )
    return {"ok": True, "detail": "task shown", "task_id": task_id}


def _list_user_sessions(user_id: str, limit: int = 20) -> dict:
    sessions = session_service.list_sessions(user_id, limit=limit)
    active = session_service.get_active_session(user_id)
    active_id = str(active.get("session_id", "") if active else "")
    if not sessions:
        gateway.send_message(user_id, "[MiniClaw] no sessions yet.")
        return {"ok": True, "detail": "no sessions"}

    lines = ["[MiniClaw] sessions:"]
    for item in sessions:
        marker = "*" if str(item["session_id"]) == active_id else " "
        lines.append(
            f"{marker} {item['session_id']} | {item['title']} | {item['status']} | last_task={item.get('last_task_id', '')}"
        )
    gateway.send_message(user_id, "\n".join(lines))
    return {"ok": True, "detail": "sessions listed"}


def _show_session(user_id: str, session_id: str = "") -> dict:
    session = session_service.get_session(session_id) if session_id else session_service.get_active_session(user_id)
    if session is None or str(session.get("user_id")) != user_id:
        gateway.send_message(user_id, "[MiniClaw] session not found.")
        return {"ok": False, "detail": "session not found"}

    gateway.send_message(
        user_id,
        (
            f"[MiniClaw] session_id: {session['session_id']}\n"
            f"title: {session['title']}\n"
            f"status: {session['status']}\n"
            f"working_directory: {session.get('working_directory', '')}\n"
            f"last_task_id: {session.get('last_task_id', '')}"
        ),
    )
    return {"ok": True, "detail": "session shown", "session_id": session["session_id"]}


def _send_task_details(user_id: str, task_id: str) -> dict:
    task = task_manager.get_task(task_id)
    if task is None or str(task.get("user_id")) != user_id:
        gateway.send_message(user_id, f"[MiniClaw] task not found: {task_id}")
        return {"ok": False, "detail": "task not found", "task_id": task_id}

    details = [
        context_store.artifact_path(task_id, "progress_details.txt"),
        context_store.artifact_path(task_id, "planner_cleaned.txt"),
        context_store.artifact_path(task_id, "execution_plan.json"),
        context_store.artifact_path(task_id, "execution_log.json"),
    ]
    if context_store.artifact_path(task_id, "final_response.txt").exists():
        details.append(context_store.artifact_path(task_id, "final_response.txt"))
    sent = 0
    for path in details:
        reporter.maybe_send_path(user_id, path)
        if path.exists():
            sent += 1
    gateway.send_message(user_id, f"[MiniClaw] sent {sent} detail artifacts for task {task_id}.")
    return {"ok": True, "detail": "task details sent", "task_id": task_id}


def _handle_user_message(user_id: str, message: str, working_directory: str = "") -> dict:
    """Converts inbound Telegram text to task operations."""

    raw = message.strip()
    if not raw:
        return {"ok": False, "detail": "empty message"}

    if not _is_user_allowed(user_id):
        detail = "chat is not allowed"
        gateway.send_message(user_id, f"[MiniClaw] {detail}")
        return {"ok": False, "detail": detail}

    command, args = _parse_command(raw)

    if command in {"start", "help"}:
        msg = _welcome_text(user_id) if command == "start" else _help_text()
        gateway.send_message(user_id, msg)
        return {"ok": True, "detail": command}

    if command == "register":
        return _handle_register(user_id, args)

    ok, detail = _ensure_active_user(user_id)
    if not ok:
        gateway.send_message(user_id, f"[MiniClaw] {detail}")
        return {"ok": False, "detail": detail}

    if command == "run":
        raw = args.strip()
        if not raw:
            msg = "run usage: /run <instruction>"
            gateway.send_message(user_id, f"[MiniClaw] {msg}")
            return {"ok": False, "detail": msg}
    elif command == "sessions":
        return _list_user_sessions(user_id)
    elif command == "details":
        task_id = args.strip()
        if not task_id:
            msg = "details usage: /details <task_id>"
            gateway.send_message(user_id, f"[MiniClaw] {msg}")
            return {"ok": False, "detail": msg}
        return _send_task_details(user_id, task_id)
    elif command == "session":
        parts = args.strip().split(maxsplit=1) if args.strip() else []
        action = parts[0].lower() if parts else "show"
        remainder = parts[1].strip() if len(parts) > 1 else ""
        if action == "new":
            effective_working_directory = _resolve_task_working_directory(working_directory)
            session = session_service.create_session(
                user_id,
                title=remainder or "New session",
                working_directory=effective_working_directory,
                activate=True,
            )
            gateway.send_message(
                user_id,
                f"[MiniClaw] active session set to {session['session_id']} ({session['title']}).",
            )
            return {"ok": True, "detail": "session created", "session_id": session["session_id"]}
        if action == "use":
            if not remainder:
                msg = "session use usage: /session use <session_id>"
                gateway.send_message(user_id, f"[MiniClaw] {msg}")
                return {"ok": False, "detail": msg}
            session = session_service.use_session(user_id, remainder)
            if session is None:
                gateway.send_message(user_id, f"[MiniClaw] session not found: {remainder}")
                return {"ok": False, "detail": "session not found"}
            gateway.send_message(
                user_id,
                f"[MiniClaw] active session set to {session['session_id']} ({session['title']}).",
            )
            return {"ok": True, "detail": "session switched", "session_id": session["session_id"]}
        if action == "show":
            return _show_session(user_id, remainder)
        if parts:
            return _show_session(user_id, " ".join(parts))
        return _show_session(user_id)
    elif command == "confirm":
        raw = f"/confirm {args}".strip() if args.strip() else "confirm"
    elif command == "pause":
        raw = f"pause {args}".strip()
    elif command == "resume":
        raw = f"resume {args}".strip()
    elif command == "cancel":
        raw = f"cancel {args}".strip()
    elif command == "append":
        raw = f"append {args}".strip()
    elif command == "tasks":
        return _list_user_tasks(user_id)
    elif command == "task":
        if not args.strip():
            msg = "task usage: /task <task_id>"
            gateway.send_message(user_id, f"[MiniClaw] {msg}")
            return {"ok": False, "detail": msg}
        return _get_user_task(user_id, args.strip())
    elif command:
        gateway.send_message(user_id, _help_text())
        return {"ok": False, "detail": f"unsupported command: /{command}"}

    lowered = raw.lower()

    if lowered == "confirm" or lowered.startswith("/confirm"):
        ok, detail = scheduler.confirm_latest_waiting(user_id, raw)
        gateway.send_message(user_id, f"[MiniClaw] {detail}")
        return {"ok": ok, "detail": detail}

    if lowered.startswith("pause "):
        task_id = raw.split(maxsplit=1)[1].strip()
        ok = scheduler.pause_task(task_id)
        detail = "pause requested" if ok else "task not found"
        gateway.send_message(user_id, f"[MiniClaw] {detail}: {task_id}")
        return {"ok": ok, "detail": detail, "task_id": task_id}

    if lowered.startswith("resume "):
        task_id = raw.split(maxsplit=1)[1].strip()
        ok = scheduler.resume_task(task_id)
        detail = "resume requested" if ok else "task not found"
        gateway.send_message(user_id, f"[MiniClaw] {detail}: {task_id}")
        return {"ok": ok, "detail": detail, "task_id": task_id}

    if lowered.startswith("cancel "):
        task_id = raw.split(maxsplit=1)[1].strip()
        ok = scheduler.cancel_task(task_id)
        detail = "cancel requested" if ok else "task not found"
        gateway.send_message(user_id, f"[MiniClaw] {detail}: {task_id}")
        return {"ok": ok, "detail": detail, "task_id": task_id}

    if lowered.startswith("append "):
        parts = raw.split(maxsplit=2)
        if len(parts) < 3:
            msg = "append usage: /append <task_id> <instruction>"
            gateway.send_message(user_id, f"[MiniClaw] {msg}")
            return {"ok": False, "detail": msg}
        task_id = parts[1]
        instruction = parts[2]
        ok, detail = scheduler.append_instruction(task_id, instruction)
        gateway.send_message(user_id, f"[MiniClaw] {detail}")
        return {"ok": ok, "detail": detail, "task_id": task_id}

    effective_working_directory = _resolve_task_working_directory(working_directory)
    session = session_service.ensure_active_session(
        user_id,
        working_directory=effective_working_directory,
        title_hint=raw,
    )
    if session is None:
        msg = "no active session; create one with /session new <title>"
        gateway.send_message(user_id, f"[MiniClaw] {msg}")
        return {"ok": False, "detail": msg}
    task = task_manager.create_task(
        user_id,
        raw,
        working_directory=effective_working_directory,
        session_id=str(session["session_id"]),
    )
    context_store.append_conversation(task["task_id"], "user", raw)
    session_service.record_user_turn(str(task["session_id"]), task["task_id"], raw)
    reporter.task_created(
        user_id,
        task["task_id"],
        raw,
        session_id=str(task.get("session_id", "")),
        session_title=str(session.get("title", "")),
    )
    scheduler.submit_task(task["task_id"])
    return {
        "ok": True,
        "detail": "task created",
        "task_id": task["task_id"],
        "session_id": task.get("session_id", ""),
    }


app = FastAPI(title=settings.app_name, version="1.0.0")


@app.on_event("startup")
async def _startup() -> None:
    validate_settings(settings, warn=lambda message: logger.warning(message))
    gateway.set_message_handler(lambda uid, msg: _handle_user_message(uid, msg, ""))
    gateway.start()
    scheduler.start()
    logger.info(
        "MiniClaw started on %s:%s with provider=%s model=%s",
        settings.host,
        settings.port,
        model_adapter.provider_name,
        model_adapter.model_name,
    )


@app.on_event("shutdown")
async def _shutdown() -> None:
    gateway.stop()
    scheduler.stop()


@app.get("/healthz")
async def healthz() -> dict:
    return {"status": "ok"}


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


@app.post("/messages/telegram/mock")
async def telegram_mock_message(payload: TelegramMockMessageRequest) -> dict:
    return await asyncio.to_thread(
        _handle_user_message,
        payload.user_id,
        payload.message,
        "",
    )


@app.post("/tasks")
async def create_task(payload: CreateTaskRequest) -> dict:
    if payload.session_id.strip():
        session = session_service.use_session(payload.user_id, payload.session_id.strip())
        if session is None:
            raise HTTPException(status_code=404, detail="session not found")
    return await asyncio.to_thread(
        _handle_user_message,
        payload.user_id,
        payload.instruction,
        payload.working_directory,
    )


@app.get("/tasks")
async def list_tasks(user_id: Optional[str] = None, session_id: str = "", limit: int = 50) -> dict:
    return {"tasks": task_manager.list_tasks(user_id=user_id, session_id=session_id, limit=limit)}


@app.get("/tasks/{task_id}")
async def get_task(task_id: str) -> dict:
    task = task_manager.get_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="task not found")
    return {"task": task}


@app.post("/tasks/{task_id}/pause")
async def pause_task(task_id: str) -> dict:
    ok = await asyncio.to_thread(scheduler.pause_task, task_id)
    if not ok:
        raise HTTPException(status_code=404, detail="task not found")
    return {"ok": True, "task_id": task_id}


@app.post("/tasks/{task_id}/resume")
async def resume_task(task_id: str) -> dict:
    ok = await asyncio.to_thread(scheduler.resume_task, task_id)
    if not ok:
        raise HTTPException(status_code=404, detail="task not found")
    return {"ok": True, "task_id": task_id}


@app.post("/tasks/{task_id}/cancel")
async def cancel_task(task_id: str) -> dict:
    ok = await asyncio.to_thread(scheduler.cancel_task, task_id)
    if not ok:
        raise HTTPException(status_code=404, detail="task not found")
    return {"ok": True, "task_id": task_id}


@app.post("/tasks/{task_id}/append")
async def append_task_instruction(task_id: str, payload: AppendInstructionRequest) -> dict:
    ok, detail = await asyncio.to_thread(scheduler.append_instruction, task_id, payload.instruction)
    if not ok:
        raise HTTPException(status_code=404, detail=detail)
    return {"ok": True, "detail": detail, "task_id": task_id}


@app.post("/tasks/confirm")
async def confirm_latest(payload: UserConfirmRequest) -> dict:
    ok, detail = await asyncio.to_thread(scheduler.confirm_latest_waiting, payload.user_id, payload.message)
    if not ok:
        raise HTTPException(status_code=400, detail=detail)
    return {"ok": True, "detail": detail}


@app.get("/users")
async def list_users(limit: int = 100) -> dict:
    return {"users": task_manager.list_users(limit=limit)}


@app.post("/sessions")
async def create_session(payload: CreateSessionRequest) -> dict:
    session = await asyncio.to_thread(
        session_service.create_session,
        payload.user_id,
        title=payload.title,
        working_directory=_resolve_task_working_directory(payload.working_directory),
        activate=True,
    )
    return {"session": session}


@app.get("/sessions")
async def list_sessions(user_id: str, limit: int = 50) -> dict:
    return {"sessions": task_manager.list_sessions(user_id=user_id, limit=limit)}


@app.get("/sessions/{session_id}")
async def get_session(session_id: str) -> dict:
    session = task_manager.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="session not found")
    return {"session": session}


@app.post("/sessions/{session_id}/activate")
async def activate_session(session_id: str, payload: ActivateSessionRequest) -> dict:
    session = await asyncio.to_thread(session_service.use_session, payload.user_id, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="session not found")
    return {"ok": True, "session": session}
