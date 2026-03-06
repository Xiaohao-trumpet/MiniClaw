"""Safety policy enforcement for high-risk actions."""

from __future__ import annotations

from typing import Dict, Optional


class SafetyGuard:
    """Validates actions and marks risky operations requiring confirmation."""

    RISKY_COMMAND_PATTERNS = (
        "git push",
        "curl ",
        "wget ",
        "invoke-webrequest",
        "scp ",
        "rm ",
        "del ",
        "rmdir ",
        "remove-item ",
        "kill ",
        "taskkill",
        "stop-process",
    )

    HIGH_RISK_ACTIONS = {
        "delete_file",
        "overwrite_file",
        "kill_process",
        "external_network_call",
    }

    def require_confirmation(self, action: Dict[str, object]) -> bool:
        """Return True if action should be blocked pending user confirmation."""
        if action.get("type") in self.HIGH_RISK_ACTIONS:
            return True

        if action.get("type") == "run_command":
            command = str(action.get("command", "")).lower()
            return any(pattern in command for pattern in self.RISKY_COMMAND_PATTERNS)

        if action.get("type") == "git_push":
            return True
        return False

    def reason_for_confirmation(self, action: Dict[str, object]) -> str:
        action_type = str(action.get("type", "unknown"))
        if action_type == "run_command":
            return f"command flagged as risky: {action.get('command', '')}"
        return f"action flagged as risky: {action_type}"

    @staticmethod
    def is_confirm_text(message: str) -> bool:
        return message.strip().lower() == "confirm"

