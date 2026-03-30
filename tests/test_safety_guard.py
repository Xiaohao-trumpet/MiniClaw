from pathlib import Path

from src.config import Settings
from src.safety.safety_guard import SafetyGuard


def _guard(tmp_path: Path) -> SafetyGuard:
    settings = Settings(allowed_workdirs=[tmp_path])
    return SafetyGuard(settings=settings)


def test_risky_command_requires_confirmation(tmp_path: Path) -> None:
    guard = _guard(tmp_path)
    decision = guard.evaluate_action(
        {
            "action_type": "run_command",
            "args": {"command": "git push origin main"},
            "risk_level": "low",
            "requires_confirmation": False,
        },
        working_directory=tmp_path,
    )
    assert decision.decision == "confirm"


def test_safe_command_is_allowed(tmp_path: Path) -> None:
    guard = _guard(tmp_path)
    decision = guard.evaluate_action(
        {
            "action_type": "run_command",
            "args": {"command": "python --version"},
            "risk_level": "low",
            "requires_confirmation": False,
        },
        working_directory=tmp_path,
    )
    assert decision.decision == "allow"


def test_destructive_command_is_denied(tmp_path: Path) -> None:
    guard = _guard(tmp_path)
    decision = guard.evaluate_action(
        {
            "action_type": "run_command",
            "args": {"command": "rm -rf /"},
            "risk_level": "critical",
            "requires_confirmation": True,
        },
        working_directory=tmp_path,
    )
    assert decision.decision == "deny"


def test_important_overwrite_requires_confirmation(tmp_path: Path) -> None:
    guard = _guard(tmp_path)
    readme = tmp_path / "README.md"
    readme.write_text("hello", encoding="utf-8")
    decision = guard.evaluate_action(
        {
            "action_type": "write_file",
            "args": {"path": "README.md", "content": "x", "overwrite": True},
            "risk_level": "medium",
            "requires_confirmation": False,
        },
        working_directory=tmp_path,
    )
    assert decision.decision == "confirm"


def test_sensitive_path_write_is_denied(tmp_path: Path) -> None:
    guard = _guard(tmp_path)
    decision = guard.evaluate_action(
        {
            "action_type": "write_file",
            "args": {"path": ".ssh/id_rsa", "content": "secret", "overwrite": True},
            "risk_level": "medium",
            "requires_confirmation": False,
        },
        working_directory=tmp_path,
    )
    assert decision.decision == "deny"
