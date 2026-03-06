from pathlib import Path

from raida.config import Settings
from raida.safety.safety_guard import SafetyGuard


def _guard(tmp_path: Path) -> SafetyGuard:
    settings = Settings(allowed_workdirs=[tmp_path])
    return SafetyGuard(settings=settings)


def test_risky_command_requires_confirmation(tmp_path: Path) -> None:
    guard = _guard(tmp_path)
    action = {
        "action_type": "run_command",
        "args": {"command": "git push origin main"},
        "risk_level": "low",
        "requires_confirmation": False,
    }
    assert guard.require_confirmation(action) is True


def test_safe_command_does_not_require_confirmation(tmp_path: Path) -> None:
    guard = _guard(tmp_path)
    action = {
        "action_type": "run_command",
        "args": {"command": "python --version"},
        "risk_level": "low",
        "requires_confirmation": False,
    }
    assert guard.require_confirmation(action) is False


def test_important_overwrite_requires_confirmation(tmp_path: Path) -> None:
    guard = _guard(tmp_path)
    action = {
        "action_type": "write_file",
        "args": {"path": "README.md", "content": "x", "overwrite": True},
        "risk_level": "medium",
        "requires_confirmation": False,
    }
    assert guard.require_confirmation(action) is True

