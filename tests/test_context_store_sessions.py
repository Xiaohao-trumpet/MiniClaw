from src.orchestrator.context_store import ContextStore


def test_context_store_reads_recent_session_conversation(tmp_path) -> None:  # noqa: ANN001
    store = ContextStore(tmp_path / "tasks", tmp_path / "sessions")
    store.append_session_conversation("session-1", "user", "first", task_id="task-1")
    store.append_session_conversation("session-1", "assistant", "answer", task_id="task-1", message_type="final_answer")
    store.append_session_conversation("session-1", "user", "second", task_id="task-2")

    recent = store.load_recent_session_conversation("session-1", limit=5)
    filtered = store.load_recent_session_conversation("session-1", limit=5, exclude_task_id="task-2")

    assert len(recent) == 3
    assert recent[-1]["content"] == "second"
    assert len(filtered) == 2
    assert all(item["task_id"] != "task-2" for item in filtered)
