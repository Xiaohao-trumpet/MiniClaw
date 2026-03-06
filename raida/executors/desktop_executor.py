"""Executor for deterministic desktop automation actions."""

from __future__ import annotations

import subprocess
import tempfile
import time
import webbrowser
from pathlib import Path
from typing import Dict

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

    def execute(self, action: Dict[str, object]) -> Dict[str, object]:
        action_type = str(action.get("type", ""))
        try:
            if action_type == "open_application":
                return self.open_application(str(action["name"]))
            if action_type == "open_url":
                return self.open_url(str(action["url"]))
            if action_type == "take_screenshot":
                return self.take_screenshot()
            if action_type == "focus_window":
                return self.focus_window(str(action["title"]))
            if action_type == "type_text":
                return self.type_text(str(action["text"]))
            if action_type == "press_key":
                return self.press_key(str(action["key"]))
            if action_type == "mouse_click":
                return self.mouse_click(int(action["x"]), int(action["y"]))
            if action_type == "browser_open_playwright":
                return self.browser_open_playwright(str(action["url"]))
            return {"success": False, "summary": f"Unsupported desktop action: {action_type}", "output": "", "artifacts": []}
        except Exception as exc:  # pragma: no cover
            logger.exception("Desktop action failed: %s", exc)
            return {"success": False, "summary": f"Desktop action failed: {exc}", "output": "", "artifacts": []}

    def open_application(self, name: str) -> Dict[str, object]:
        # Uses shell-start to let OS resolve registered applications.
        subprocess.Popen(["cmd", "/c", "start", "", name], shell=False)
        return {"success": True, "summary": f"Opened application: {name}", "output": "", "artifacts": []}

    def open_url(self, url: str) -> Dict[str, object]:
        webbrowser.open(url, new=2)
        return {"success": True, "summary": f"Opened URL: {url}", "output": "", "artifacts": []}

    def take_screenshot(self) -> Dict[str, object]:
        output_dir = Path(tempfile.gettempdir()) / "raida"
        output_dir.mkdir(parents=True, exist_ok=True)
        image_path = output_dir / f"screenshot_{int(time.time())}.png"
        take_screenshot(image_path)
        return {
            "success": True,
            "summary": "Screenshot captured.",
            "output": str(image_path),
            "artifacts": [str(image_path)],
        }

    def focus_window(self, title: str) -> Dict[str, object]:
        if pygetwindow is None:
            return {"success": False, "summary": "pygetwindow is not installed.", "output": "", "artifacts": []}
        windows = pygetwindow.getWindowsWithTitle(title)
        if not windows:
            return {"success": False, "summary": f"No window found for title: {title}", "output": "", "artifacts": []}
        windows[0].activate()
        return {"success": True, "summary": f"Focused window: {title}", "output": "", "artifacts": []}

    def type_text(self, text: str) -> Dict[str, object]:
        if pyautogui is None:
            return {"success": False, "summary": "pyautogui is not installed.", "output": "", "artifacts": []}
        pyautogui.write(text)
        return {"success": True, "summary": "Text typed.", "output": text, "artifacts": []}

    def press_key(self, key: str) -> Dict[str, object]:
        if pyautogui is None:
            return {"success": False, "summary": "pyautogui is not installed.", "output": "", "artifacts": []}
        pyautogui.press(key)
        return {"success": True, "summary": f"Pressed key: {key}", "output": "", "artifacts": []}

    def mouse_click(self, x: int, y: int) -> Dict[str, object]:
        if pyautogui is None:
            return {"success": False, "summary": "pyautogui is not installed.", "output": "", "artifacts": []}
        pyautogui.click(x=x, y=y)
        return {"success": True, "summary": f"Clicked at ({x}, {y}).", "output": "", "artifacts": []}

    def browser_open_playwright(self, url: str) -> Dict[str, object]:
        if sync_playwright is None:
            return {"success": False, "summary": "playwright is not installed.", "output": "", "artifacts": []}
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=False)
            page = browser.new_page()
            page.goto(url)
            page.wait_for_timeout(1500)
            browser.close()
        return {"success": True, "summary": f"Opened in Playwright: {url}", "output": "", "artifacts": []}

