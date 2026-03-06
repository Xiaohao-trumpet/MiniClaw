"""Executor for deterministic desktop automation actions."""

from __future__ import annotations

import subprocess
import tempfile
import time
import webbrowser
from pathlib import Path
from typing import Dict, Optional

from raida.utils.logger import get_logger
from raida.utils.screenshot import take_screenshot

logger = get_logger(__name__)

try:  # pragma: no cover - optional runtime dependencies
    import pyautogui
except Exception:  # pragma: no cover
    pyautogui = None

try:  # pragma: no cover
    import pygetwindow
except Exception:  # pragma: no cover
    pygetwindow = None

try:  # pragma: no cover
    from playwright.sync_api import sync_playwright
except Exception:  # pragma: no cover
    sync_playwright = None


class DesktopExecutor:
    """Performs GUI actions with deterministic automation libraries."""

    def execute(self, action: Dict[str, object], task_dir: Optional[Path] = None) -> Dict[str, object]:
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
            if action_type == "open_url":
                return self.open_url(str(args.get("url", "")))
            if action_type == "take_screenshot":
                return self.take_screenshot(task_dir=task_dir)
            if action_type == "focus_window":
                return self.focus_window(str(args.get("title", "")))
            if action_type == "type_text":
                return self.type_text(str(args.get("text", "")))
            if action_type == "press_key":
                return self.press_key(str(args.get("key", "")))
            if action_type == "mouse_click":
                return self.mouse_click(int(args.get("x", 0)), int(args.get("y", 0)))
            if action_type == "browser_open_playwright":
                return self.browser_open_playwright(str(args.get("url", "")))
            return self._error(f"Unsupported desktop action: {action_type}")
        except Exception as exc:  # pragma: no cover
            logger.exception("Desktop action failed: %s", exc)
            return self._error(f"Desktop action failed: {exc}")

    def open_application(self, name: str, target_dir: str = "") -> Dict[str, object]:
        name_normalized = name.strip().lower()
        if not name_normalized:
            return self._error("Missing application name.")

        if name_normalized in {"vscode", "code"}:
            start_target = target_dir.strip() or "."
            subprocess.Popen(["cmd", "/c", "start", "", "code", start_target], shell=False)
            return self._ok(f"Opened VS Code: {start_target}")

        if name_normalized in {"browser", "default_browser"}:
            subprocess.Popen(["cmd", "/c", "start", "", "msedge"], shell=False)
            return self._ok("Opened browser: msedge")

        if name_normalized in {"powershell", "pwsh"}:
            subprocess.Popen(["cmd", "/c", "start", "", "powershell"], shell=False)
            return self._ok("Opened PowerShell")

        if name_normalized in {"explorer", "file_explorer"}:
            target = target_dir.strip() or "."
            subprocess.Popen(["cmd", "/c", "start", "", "explorer", target], shell=False)
            return self._ok(f"Opened Explorer: {target}")

        subprocess.Popen(["cmd", "/c", "start", "", name], shell=False)
        return self._ok(f"Opened application: {name}")

    def open_url(self, url: str) -> Dict[str, object]:
        if not url.strip():
            return self._error("Missing URL.")
        webbrowser.open(url, new=2)
        return self._ok(f"Opened URL: {url}")

    def take_screenshot(self, task_dir: Optional[Path]) -> Dict[str, object]:
        output_dir = (task_dir / "screenshots") if task_dir else (Path(tempfile.gettempdir()) / "raida")
        output_dir.mkdir(parents=True, exist_ok=True)
        image_path = output_dir / f"screenshot_{int(time.time())}.png"
        take_screenshot(image_path)
        return {
            "success": True,
            "status": "executed",
            "summary": "Screenshot captured.",
            "output": str(image_path),
            "artifacts": [str(image_path)],
            "metadata": {},
        }

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

    def browser_open_playwright(self, url: str) -> Dict[str, object]:
        if sync_playwright is None:
            return self._error("playwright is not installed.")
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=False)
            page = browser.new_page()
            page.goto(url)
            page.wait_for_timeout(1500)
            browser.close()
        return self._ok(f"Opened in Playwright: {url}")

    @staticmethod
    def _ok(summary: str) -> Dict[str, object]:
        return {
            "success": True,
            "status": "executed",
            "summary": summary,
            "output": "",
            "artifacts": [],
            "metadata": {},
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
