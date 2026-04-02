from pathlib import Path

import src.main as main_module
from src.orchestrator.context_store import ContextStore
from src.orchestrator.session_service import SessionService
from src.orchestrator.task_manager import TaskManager


class DummyGateway:
    def __init__(self) -> None:
        self.messages: list[str] = []

    def send_message(self, user_id: str, text: str) -> None:  # noqa: ARG002
        self.messages.append(text)


def _install_runtime(tmp_path: Path, monkeypatch) -> DummyGateway:  # noqa: ANN001
    gateway = DummyGateway()
    task_manager = TaskManager(tmp_path / "src.db")
    context_store = ContextStore(tmp_path / "tasks", tmp_path / "sessions", tmp_path / "projects")
    session_service = SessionService(task_manager, context_store, auto_create_on_run=True)

    monkeypatch.setattr(main_module, "gateway", gateway)
    monkeypatch.setattr(main_module, "task_manager", task_manager)
    monkeypatch.setattr(main_module, "context_store", context_store)
    monkeypatch.setattr(main_module, "session_service", session_service)
    monkeypatch.setattr(main_module, "_allowed_user_ids", set())
    monkeypatch.setattr(main_module.settings, "telegram_require_registration", False)
    monkeypatch.setattr(main_module.settings, "allowed_workdirs", [tmp_path])
    return gateway


def test_handle_user_message_supports_create_switch_and_where(tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    gateway = _install_runtime(tmp_path, monkeypatch)

    created = main_module._handle_user_message("tg_1", "/create alpha", "")
    assert created["ok"] is True

    second = main_module._handle_user_message("tg_1", "/create beta", "")
    assert second["ok"] is True

    switched = main_module._handle_user_message("tg_1", "/switch alpha", "")
    assert switched["ok"] is True

    where = main_module._handle_user_message("tg_1", "/where", "")
    assert where["ok"] is True
    assert any("session: alpha" in message for message in gateway.messages)
    assert any("project:" in message for message in gateway.messages)
