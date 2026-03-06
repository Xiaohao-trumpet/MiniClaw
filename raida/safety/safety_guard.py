"""Safety policy enforcement for high-risk actions."""

from __future__ import annotations

from typing import Dict

from raida.config import Settings


class SafetyGuard:
    """Validates actions and marks risky operations requiring confirmation."""

    RISKY_COMMAND_PATTERNS = (
        "git push",
        "pip install",
        "npm install",
        "winget install",
        "choco install",
        "apt install",
        "yum install",
        "curl ",
        "wget ",
        "invoke-restmethod",
        "invoke-webrequest",
        "scp ",
        "rm ",
        "del ",
        "format ",
        "rmdir ",
        "remove-item ",
        "kill ",
        "taskkill",
        "stop-process",
        "shutdown",
        "restart-computer",
    )

    HIGH_RISK_ACTIONS = {
        "request_confirmation",
    }

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def require_confirmation(self, action: Dict[str, object]) -> bool:
        """Return True if action should be blocked pending user confirmation."""
        action_type = str(action.get("action_type", ""))
        risk_level = str(action.get("risk_level", "low")).lower()

        if action.get("requires_confirmation"):
            return True
        if risk_level in {"high", "critical"}:
            return True
        if action_type in self.HIGH_RISK_ACTIONS:
            return True

        args = action.get("args", {})
        if not isinstance(args, dict):
            return True

        if action_type == "run_command":
            command = str(args.get("command", "")).lower()
            return any(pattern in command for pattern in self.RISKY_COMMAND_PATTERNS)

        if action_type == "write_file":
            path = str(args.get("path", "")).lower()
            overwrite = bool(args.get("overwrite", True))
            if overwrite and self._settings.require_confirmation_for_overwrite:
                important = (".env", "pyproject.toml", "requirements.txt", "readme.md")
                if any(path.endswith(item) for item in important):
                    return True

        if action_type == "open_url" and self._settings.require_confirmation_for_network:
            return True

        return False

    def reason_for_confirmation(self, action: Dict[str, object]) -> str:
        action_type = str(action.get("action_type", "unknown"))
        args = action.get("args", {})
        if not isinstance(args, dict):
            return f"action flagged as risky: {action_type}"
        if action_type == "run_command":
            return f"command flagged as risky: {args.get('command', '')}"
        if action_type == "write_file":
            return f"file overwrite requires confirmation: {args.get('path', '')}"
        if action_type == "open_url":
            return f"network action requires confirmation: {args.get('url', '')}"
        return f"action flagged as risky: {action_type}"

    @staticmethod
    def is_confirm_text(message: str) -> bool:
        text = message.strip().lower()
        return text == "confirm" or text.startswith("/confirm")
