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
context_store = ContextStore(settings.task_data_dir)
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
scheduler = TaskScheduler(task_manager, context_store, planner, executor_router, safety_guard, reporter)

_allowed_user_ids = {
    f"tg_{chat_id}" if not chat_id.startswith("tg_") else chat_id
    for chat_id in settings.telegram_allowed_chat_ids
}


class CreateTaskRequest(BaseModel):
    user_id: str
    instruction: str
    working_directory: str = ""


class AppendInstructionRequest(BaseModel):
    instruction: str


class UserConfirmRequest(BaseModel):
    user_id: str
    message: str = "confirm"


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
        lines.append(f"- {item['task_id']} | {item['status']} | {item['current_step']}")
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
            f"status: {task['status']}\n"
            f"current_step: {task['current_step']}\n"
            f"instruction: {task['instruction']}"
        ),
    )
    return {"ok": True, "detail": "task shown", "task_id": task_id}


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
    task = task_manager.create_task(user_id, raw, working_directory=effective_working_directory)
    context_store.append_conversation(task["task_id"], "user", raw)
    reporter.task_created(user_id, task["task_id"], raw)
    scheduler.submit_task(task["task_id"])
    return {"ok": True, "detail": "task created", "task_id": task["task_id"]}


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
    return await asyncio.to_thread(
        _handle_user_message,
        payload.user_id,
        payload.instruction,
        payload.working_directory,
    )


@app.get("/tasks")
async def list_tasks(user_id: Optional[str] = None, limit: int = 50) -> dict:
    return {"tasks": task_manager.list_tasks(user_id=user_id, limit=limit)}


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
