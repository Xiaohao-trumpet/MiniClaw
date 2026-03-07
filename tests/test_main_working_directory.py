from pathlib import Path

import raida.main as main_module


def test_resolve_task_working_directory_uses_input_when_provided(tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.setattr(main_module.settings, "allowed_workdirs", [tmp_path])
    assert main_module._resolve_task_working_directory(str(tmp_path / "custom")) == str(tmp_path / "custom")


def test_resolve_task_working_directory_defaults_to_first_allowed(tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    allowed = tmp_path / "workspace"
    allowed.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(main_module.settings, "allowed_workdirs", [allowed])
    assert main_module._resolve_task_working_directory("") == str(allowed.resolve())
