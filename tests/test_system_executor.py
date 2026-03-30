from pathlib import Path

from src.config import Settings
from src.executors.system_executor import SystemExecutor
from src.utils.command_runner import CommandRunner


def _executor(tmp_path: Path) -> SystemExecutor:
    settings = Settings(
        allowed_workdirs=[tmp_path],
        task_data_dir=tmp_path / "tasks",
    )
    return SystemExecutor(settings=settings, command_runner=CommandRunner())


def test_find_files_returns_matching_files(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("print('a')", encoding="utf-8")
    (tmp_path / "b.txt").write_text("b", encoding="utf-8")
    executor = _executor(tmp_path)

    result = executor.execute(
        {"action_type": "find_files", "args": {"path": ".", "pattern": "*.py"}},
        working_directory=tmp_path,
        task_dir=tmp_path / "task",
    )

    assert result["success"] is True
    assert "a.py" in str(result["output"])
    assert "b.txt" not in str(result["output"])


def test_search_text_returns_matches(tmp_path: Path) -> None:
    (tmp_path / "main.py").write_text("raise PlannerExecutionError\n", encoding="utf-8")
    executor = _executor(tmp_path)

    result = executor.execute(
        {"action_type": "search_text", "args": {"path": ".", "query": "PlannerExecutionError"}},
        working_directory=tmp_path,
        task_dir=tmp_path / "task",
    )

    assert result["success"] is True
    assert "main.py:1:" in str(result["output"])


def test_read_multiple_files_concatenates_sections(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("alpha", encoding="utf-8")
    (tmp_path / "b.txt").write_text("beta", encoding="utf-8")
    executor = _executor(tmp_path)

    result = executor.execute(
        {"action_type": "read_multiple_files", "args": {"paths": ["a.txt", "b.txt"]}},
        working_directory=tmp_path,
        task_dir=tmp_path / "task",
    )

    assert result["success"] is True
    output = str(result["output"])
    assert "==>" in output
    assert "alpha" in output
    assert "beta" in output
