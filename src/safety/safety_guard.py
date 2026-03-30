"""Safety policy enforcement for runtime actions."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict
from urllib.parse import urlparse

from src.config import Settings
from src.utils.path_utils import is_within_roots, resolve_path


@dataclass(frozen=True)
class SafetyDecision:
    """Structured result of evaluating an action against runtime policy."""

    decision: str
    reason: str
    preview: str
    category: str
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def requires_confirmation(self) -> bool:
        return self.decision == "confirm"


class SafetyGuard:
    """Classifies each runtime action as allow, confirm, or deny."""

    DENY_COMMAND_PATTERNS = (
        re.compile(r"\brm\s+-rf\s+/($|\s)"),
        re.compile(r"\bsudo\s+rm\s+-rf\b"),
        re.compile(r"\bmkfs(?:\.[a-z0-9]+)?\b"),
        re.compile(r"\b(fdisk|parted|sfdisk)\b"),
        re.compile(r"\bdd\b[^\n]*\bof=/dev/"),
        re.compile(r"\b(format|diskpart)\b"),
        re.compile(r"\b(shutdown|poweroff|reboot|halt)\b"),
        re.compile(r"\binit\s+0\b"),
        re.compile(r"\bremove-item\b[^\n]*\b(recurse|force)\b", re.IGNORECASE),
        re.compile(r"\bdel\b[^\n]*\bc:\\", re.IGNORECASE),
        re.compile(r"\brd\s+/s\b", re.IGNORECASE),
    )

    CONFIRM_COMMAND_PATTERNS = (
        re.compile(r"\b(rm|del|rmdir|remove-item)\b", re.IGNORECASE),
        re.compile(r"\b(pip|pip3|python\s+-m\s+pip|uv\s+pip)\s+install\b", re.IGNORECASE),
        re.compile(r"\b(npm|pnpm|yarn|bun)\s+(install|add)\b", re.IGNORECASE),
        re.compile(r"\b(apt|apt-get|yum|dnf|brew|winget|choco|cargo)\s+install\b", re.IGNORECASE),
        re.compile(r"\b(curl|wget|scp|ssh|rsync)\b", re.IGNORECASE),
        re.compile(r"\bgit\s+(push|pull|fetch|clone)\b", re.IGNORECASE),
        re.compile(
            r"\b(kill|pkill|killall|taskkill|stop-process|systemctl\s+(stop|restart)|service\s+[^\s]+\s+(stop|restart))\b",
            re.IGNORECASE,
        ),
    )

    SENSITIVE_WRITE_PREFIXES = (
        Path("/etc"),
        Path("/usr"),
        Path("/bin"),
        Path("/sbin"),
        Path("/boot"),
        Path("/dev"),
        Path("/proc"),
        Path("/sys"),
        Path("/var/lib"),
        Path("/var/run"),
        Path("/root"),
        Path("C:/Windows"),
        Path("C:/Program Files"),
    )

    SENSITIVE_PATH_PARTS = {".ssh", ".gnupg"}
    SENSITIVE_FILENAMES = {"authorized_keys", "known_hosts", "id_rsa", "id_ed25519"}
    IMPORTANT_FILENAMES = {
        ".env",
        ".env.local",
        "readme.md",
        "pyproject.toml",
        "requirements.txt",
        "package.json",
        "dockerfile",
        "compose.yml",
        "compose.yaml",
        ".gitignore",
    }

    GUI_CONFIRM_ACTIONS = {
        "open_application",
        "focus_window",
        "type_text",
        "press_key",
        "mouse_click",
    }

    SAFE_ACTIONS = {
        "list_directory",
        "read_file",
        "find_files",
        "search_text",
        "read_multiple_files",
        "get_system_info",
        "take_screenshot",
        "respond_only",
    }

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def evaluate_action(self, action: Dict[str, object], working_directory: Path | None = None) -> SafetyDecision:
        """Return a structured safety decision for the given action."""

        action_type = str(action.get("action_type", "")).strip()
        risk_level = str(action.get("risk_level", "low")).lower()
        requires_confirmation = bool(action.get("requires_confirmation", False))
        args = action.get("args", {})

        if not isinstance(args, dict):
            return self._decision(
                "deny",
                "Action arguments are malformed.",
                f"action: {action_type or 'unknown'}",
                category="invalid_action",
            )

        if action_type == "run_command":
            decision = self._evaluate_run_command(args, working_directory)
        elif action_type == "write_file":
            decision = self._evaluate_write_file(args, working_directory)
        elif action_type == "open_url":
            decision = self._evaluate_open_url(args)
        elif action_type == "request_confirmation":
            prompt = str(args.get("prompt", "Action requires confirmation.")).strip() or "Action requires confirmation."
            decision = self._decision(
                "confirm",
                "Planner inserted a confirmation checkpoint.",
                f"prompt: {prompt}",
                category="planner_checkpoint",
                metadata={"prompt": prompt},
            )
        elif action_type in self.GUI_CONFIRM_ACTIONS:
            decision = self._decision(
                "confirm",
                "GUI control is treated as a high-risk desktop action.",
                self._preview_for_gui_action(action_type, args),
                category="desktop_control",
                metadata={"action_type": action_type},
            )
        elif action_type in self.SAFE_ACTIONS:
            decision = self._decision(
                "allow",
                "Structured local action is allowed.",
                self._preview_for_safe_action(action_type, args),
                category="structured_tool",
            )
        else:
            decision = self._decision(
                "confirm",
                "Unknown action type requires manual confirmation.",
                f"action: {action_type or 'unknown'}",
                category="unknown_action",
            )

        if decision.decision == "allow" and (requires_confirmation or risk_level in {"high", "critical"}):
            return self._decision(
                "confirm",
                "Planner marked the action as high risk.",
                decision.preview,
                category="planner_escalation",
                metadata=decision.metadata,
            )
        return decision

    def require_confirmation(self, action: Dict[str, object], working_directory: Path | None = None) -> bool:
        """Backward-compatible helper for callers that only need a boolean."""

        return self.evaluate_action(action, working_directory=working_directory).requires_confirmation

    def reason_for_confirmation(self, action: Dict[str, object], working_directory: Path | None = None) -> str:
        decision = self.evaluate_action(action, working_directory=working_directory)
        return decision.reason

    def _evaluate_run_command(self, args: Dict[str, object], working_directory: Path | None) -> SafetyDecision:
        command = str(args.get("command", "")).strip()
        if not command:
            return self._decision("deny", "Missing command for run_command.", "command: <empty>", category="invalid_command")

        preview = f"command: {self._summarize(command, 220)}"
        if working_directory is not None:
            preview = f"working_directory: {working_directory}\n{preview}"

        if self._matches_any(command, self.DENY_COMMAND_PATTERNS):
            return self._decision(
                "deny",
                "Command matches the hard-deny destructive command policy.",
                preview,
                category="destructive_command",
                metadata={"command": command},
            )
        if self._matches_any(command, self.CONFIRM_COMMAND_PATTERNS):
            return self._decision(
                "confirm",
                "Command changes the environment, reaches the network, or manages processes.",
                preview,
                category="elevated_command",
                metadata={"command": command},
            )
        return self._decision(
            "allow",
            "Command stays within the default low-risk shell policy.",
            preview,
            category="command",
            metadata={"command": command},
        )

    def _evaluate_write_file(self, args: Dict[str, object], working_directory: Path | None) -> SafetyDecision:
        path_raw = str(args.get("path", "")).strip()
        if not path_raw:
            return self._decision("deny", "Missing path for write_file.", "path: <empty>", category="invalid_write")

        content = str(args.get("content", ""))
        overwrite = bool(args.get("overwrite", True))
        resolved_path = resolve_path(Path(path_raw), working_directory)
        preview = (
            f"path: {resolved_path}\n"
            f"overwrite: {overwrite}\n"
            f"content_preview: {self._summarize(content, 160)}"
        )

        if not is_within_roots(resolved_path, self._settings.allowed_workdirs):
            return self._decision(
                "deny",
                "Write target is outside the allowed workspace roots.",
                preview,
                category="path_outside_workspace",
                metadata={"path": str(resolved_path)},
            )
        if self._is_sensitive_write_path(resolved_path):
            return self._decision(
                "deny",
                "Write target is a sensitive system or credential path.",
                preview,
                category="sensitive_path_write",
                metadata={"path": str(resolved_path)},
            )
        if overwrite and resolved_path.exists() and self._settings.require_confirmation_for_overwrite:
            filename = resolved_path.name.lower()
            reason = (
                "Important file overwrite requires confirmation."
                if filename in self.IMPORTANT_FILENAMES
                else "Existing file overwrite requires confirmation."
            )
            return self._decision(
                "confirm",
                reason,
                preview,
                category="file_overwrite",
                metadata={"path": str(resolved_path)},
            )
        return self._decision(
            "allow",
            "Workspace file write is allowed.",
            preview,
            category="file_write",
            metadata={"path": str(resolved_path)},
        )

    def _evaluate_open_url(self, args: Dict[str, object]) -> SafetyDecision:
        url = str(args.get("url", "")).strip()
        if not url:
            return self._decision("deny", "Missing URL for open_url.", "url: <empty>", category="invalid_url")

        parsed = urlparse(url)
        preview = f"url: {url}"
        if parsed.scheme in {"javascript", "data", "file"}:
            return self._decision(
                "deny",
                "Unsupported or unsafe URL scheme.",
                preview,
                category="unsafe_url_scheme",
                metadata={"url": url},
            )
        if parsed.scheme not in {"http", "https", "about"}:
            return self._decision(
                "confirm",
                "Non-standard URL scheme requires confirmation.",
                preview,
                category="nonstandard_url_scheme",
                metadata={"url": url},
            )
        if parsed.scheme == "about":
            return self._decision("allow", "Local browser page is allowed.", preview, category="local_browser_page")
        if self._settings.require_confirmation_for_network:
            return self._decision(
                "confirm",
                "Opening a network URL requires confirmation.",
                preview,
                category="network_access",
                metadata={"url": url},
            )
        return self._decision("allow", "Network confirmation is disabled by settings.", preview, category="network_access")

    def _preview_for_gui_action(self, action_type: str, args: Dict[str, object]) -> str:
        if action_type == "open_application":
            return f"application: {args.get('name', '')}\ntarget_dir: {args.get('target_dir', '')}"
        if action_type == "focus_window":
            return f"window_title: {args.get('title', '')}"
        if action_type == "type_text":
            return f"text_preview: {self._summarize(str(args.get('text', '')), 120)}"
        if action_type == "press_key":
            return f"key: {args.get('key', '')}"
        if action_type == "mouse_click":
            return f"coordinates: ({args.get('x', '')}, {args.get('y', '')})"
        return f"action: {action_type}"

    def _preview_for_safe_action(self, action_type: str, args: Dict[str, object]) -> str:
        if action_type in {"list_directory", "read_file", "find_files", "search_text"}:
            return f"path: {args.get('path', '.')}"
        if action_type == "read_multiple_files":
            return f"paths: {args.get('paths', [])}"
        if action_type == "get_system_info":
            return "scope: local runtime environment"
        if action_type == "take_screenshot":
            return "scope: current display"
        if action_type == "respond_only":
            return f"message: {self._summarize(str(args.get('message', '')), 120)}"
        return f"action: {action_type}"

    def _is_sensitive_write_path(self, path: Path) -> bool:
        normalized_parts = {part.lower() for part in path.parts}
        if normalized_parts.intersection(self.SENSITIVE_PATH_PARTS):
            return True
        if path.name.lower() in self.SENSITIVE_FILENAMES:
            return True
        for prefix in self.SENSITIVE_WRITE_PREFIXES:
            try:
                path.relative_to(prefix)
                return True
            except ValueError:
                continue
        return False

    @staticmethod
    def _decision(
        decision: str,
        reason: str,
        preview: str,
        *,
        category: str,
        metadata: Dict[str, Any] | None = None,
    ) -> SafetyDecision:
        return SafetyDecision(
            decision=decision,
            reason=reason,
            preview=preview.strip(),
            category=category,
            metadata=metadata or {},
        )

    @staticmethod
    def _matches_any(command: str, patterns: tuple[re.Pattern[str], ...]) -> bool:
        return any(pattern.search(command) for pattern in patterns)

    @staticmethod
    def _summarize(text: str, limit: int) -> str:
        compact = " ".join(text.strip().split())
        if not compact:
            return "<empty>"
        return compact if len(compact) <= limit else f"{compact[:limit - 3]}..."

    @staticmethod
    def is_confirm_text(message: str) -> bool:
        text = message.strip().lower()
        return text == "confirm" or text.startswith("/confirm")
