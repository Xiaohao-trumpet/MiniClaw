"""Executor for optional desktop automation actions."""

from __future__ import annotations

import platform
import shutil
import subprocess
import webbrowser
from pathlib import Path
from typing import Dict, Optional

from src.utils.logger import get_logger

logger = get_logger(__name__)

try:  # pragma: no cover - optional runtime dependencies
    import pyautogui
except Exception:  # pragma: no cover
    pyautogui = None

try:  # pragma: no cover
    import pygetwindow
except Exception:  # pragma: no cover
    pygetwindow = None


class DesktopExecutor:
    """Performs GUI actions when the optional desktop stack is available."""

    def execute(self, action: Dict[str, object], task_dir: Optional[Path] = None) -> Dict[str, object]:
        del task_dir
        action_type = str(action.get("action_type", ""))
        args = action.get("args", {})
        if not isinstance(args, dict):
            return self._error(f"Invalid action args for {action_type}.")
        try:
            if action_type == "open_application":
                return self.open_application(
                    name=str(args.get("name", "")),
                    target_dir=str(args.get("target_dir", "")),
                )
            if action_type == "focus_window":
                return self.focus_window(str(args.get("title", "")))
            if action_type == "type_text":
                return self.type_text(str(args.get("text", "")))
            if action_type == "press_key":
                return self.press_key(str(args.get("key", "")))
            if action_type == "mouse_click":
                return self.mouse_click(int(args.get("x", 0)), int(args.get("y", 0)))
            return self._error(f"Unsupported desktop action: {action_type}")
        except Exception as exc:  # pragma: no cover
            logger.exception("Desktop action failed: %s", exc)
            return self._error(f"Desktop action failed: {exc}")

    def open_application(self, name: str, target_dir: str = "") -> Dict[str, object]:
        name_normalized = name.strip().lower()
        if not name_normalized:
            return self._error("Missing application name.")

        target = str(Path(target_dir).resolve()) if target_dir.strip() else ""
        system = platform.system().lower()

        if name_normalized in {"vscode", "code"}:
            for candidate in ("code", "code-insiders"):
                executable = shutil.which(candidate)
                if executable:
                    command = [executable]
                    if target:
                        command.append(target)
                    subprocess.Popen(command, shell=False)
                    return self._ok(f"Opened VS Code: {target or '.'}", metadata={"command": command})
            return self._error("VS Code executable not found in PATH.")

        if name_normalized in {"browser", "default_browser"}:
            webbrowser.open("about:blank", new=2)
            return self._ok("Opened default browser.")

        if name_normalized in {"explorer", "file_explorer"}:
            if system == "windows":
                command = ["explorer", target or "."]
            elif system == "darwin":
                command = ["open", target or "."]
            else:
                command = [shutil.which("xdg-open") or "xdg-open", target or "."]
            subprocess.Popen(command, shell=False)
            return self._ok(f"Opened file explorer: {target or '.'}", metadata={"command": command})

        if name_normalized in {"terminal", "shell", "powershell", "pwsh"}:
            command = self._terminal_command(system, target)
            if not command:
                return self._error("No supported terminal application found on this platform.")
            subprocess.Popen(command, shell=False)
            return self._ok(f"Opened terminal: {command[0]}", metadata={"command": command})

        if system == "windows":
            command = ["cmd", "/c", "start", "", name]
        elif system == "darwin":
            command = ["open", "-a", name]
        else:
            executable = shutil.which(name)
            if executable is None:
                return self._error(f"Application not found in PATH: {name}")
            command = [executable]
        subprocess.Popen(command, shell=False)
        return self._ok(f"Opened application: {name}", metadata={"command": command})

    def focus_window(self, title: str) -> Dict[str, object]:
        if pygetwindow is None:
            return self._error("pygetwindow is not installed.")
        windows = pygetwindow.getWindowsWithTitle(title)
        if not windows:
            return self._error(f"No window found for title: {title}")
        windows[0].activate()
        return self._ok(f"Focused window: {title}")

    def type_text(self, text: str) -> Dict[str, object]:
        if pyautogui is None:
            return self._error("pyautogui is not installed.")
        pyautogui.write(text)
        return {
            "success": True,
            "status": "executed",
            "summary": "Text typed.",
            "output": text,
            "artifacts": [],
            "metadata": {},
        }

    def press_key(self, key: str) -> Dict[str, object]:
        if pyautogui is None:
            return self._error("pyautogui is not installed.")
        pyautogui.press(key)
        return self._ok(f"Pressed key: {key}")

    def mouse_click(self, x: int, y: int) -> Dict[str, object]:
        if pyautogui is None:
            return self._error("pyautogui is not installed.")
        pyautogui.click(x=x, y=y)
        return self._ok(f"Clicked at ({x}, {y}).")

    @staticmethod
    def _terminal_command(system: str, target: str) -> list[str]:
        if system == "windows":
            return [shutil.which("pwsh") or "powershell"]
        if system == "darwin":
            return ["open", "-a", "Terminal", target] if target else ["open", "-a", "Terminal"]
        for candidate in ("x-terminal-emulator", "gnome-terminal", "konsole", "xfce4-terminal", "mate-terminal", "xterm"):
            executable = shutil.which(candidate)
            if executable:
                return [executable]
        return []

    @staticmethod
    def _ok(summary: str, metadata: Optional[Dict[str, object]] = None) -> Dict[str, object]:
        return {
            "success": True,
            "status": "executed",
            "summary": summary,
            "output": "",
            "artifacts": [],
            "metadata": metadata or {},
        }

    @staticmethod
    def _error(summary: str) -> Dict[str, object]:
        return {
            "success": False,
            "status": "failed",
            "summary": summary,
            "output": "",
            "artifacts": [],
            "metadata": {},
        }
