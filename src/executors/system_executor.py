"""System-level executor for local filesystem, browser, and shell actions."""

from __future__ import annotations

import fnmatch
import json
import platform
import tempfile
import time
import webbrowser
from pathlib import Path
from typing import Callable, Dict, Iterable, Optional

from src.config import Settings
from src.utils.command_runner import CommandResult, CommandRunner
from src.utils.logger import get_logger
from src.utils.path_utils import ensure_within_roots, resolve_path
from src.utils.screenshot import take_screenshot

logger = get_logger(__name__)

try:  # pragma: no cover - optional runtime dependency
    import psutil
except Exception:  # pragma: no cover
    psutil = None


class SystemExecutor:
    """Executes core local actions on the host machine."""

    OUTPUT_ACTIONS = {
        "run_command",
        "list_directory",
        "read_file",
        "find_files",
        "search_text",
        "read_multiple_files",
        "get_system_info",
    }

    def __init__(self, settings: Settings, command_runner: CommandRunner) -> None:
        self.settings = settings
        self.command_runner = command_runner

    def execute(
        self,
        action: Dict[str, object],
        working_directory: Path | None,
        task_dir: Path,
        on_output: Optional[Callable[[str], None]] = None,
    ) -> Dict[str, object]:
        action_type = str(action.get("action_type", ""))
        args = action.get("args", {})
        if not isinstance(args, dict):
            return self._error(f"Invalid action args for {action_type}.")

        try:
            if action_type == "run_command":
                return self._run_command(args=args, working_directory=working_directory, task_dir=task_dir, on_output=on_output)
            if action_type == "open_url":
                return self._open_url(args=args)
            if action_type == "list_directory":
                return self._list_directory(args=args, working_directory=working_directory)
            if action_type == "read_file":
                return self._read_file(args=args, working_directory=working_directory)
            if action_type == "write_file":
                return self._write_file(args=args, working_directory=working_directory)
            if action_type == "take_screenshot":
                return self._take_screenshot(task_dir=task_dir)
            if action_type == "find_files":
                return self._find_files(args=args, working_directory=working_directory)
            if action_type == "search_text":
                return self._search_text(args=args, working_directory=working_directory)
            if action_type == "read_multiple_files":
                return self._read_multiple_files(args=args, working_directory=working_directory)
            if action_type == "get_system_info":
                return self._get_system_info(working_directory=working_directory)
            if action_type == "request_confirmation":
                return {
                    "success": False,
                    "status": "blocked",
                    "summary": str(args.get("prompt", "Action requires confirmation.")),
                    "output": "",
                    "artifacts": [],
                    "metadata": {},
                }
            if action_type == "respond_only":
                return self._respond_only(args=args, task_dir=task_dir)
        except Exception as exc:  # pragma: no cover - defensive for external I/O
            logger.exception("system_executor_failed action_type=%s error=%s", action_type, exc)
            return self._error(f"System action failed: {exc}")

        return self._error(f"Unsupported system action: {action_type}")

    def _run_command(
        self,
        args: Dict[str, object],
        working_directory: Path | None,
        task_dir: Path,
        on_output: Optional[Callable[[str], None]],
    ) -> Dict[str, object]:
        command = str(args.get("command", "")).strip()
        if not command:
            return self._error("Missing command for run_command.")

        requested_cwd = str(args.get("working_directory", "")).strip()
        base_cwd = Path(requested_cwd).resolve() if requested_cwd else working_directory
        safe_cwd = self._sanitize_working_directory(base_cwd)

        timeout_seconds = int(args.get("timeout_seconds", self.settings.command_timeout_seconds))
        result = self.command_runner.run(
            command=command,
            cwd=safe_cwd,
            timeout_seconds=timeout_seconds,
            on_output=on_output,
        )

        self._append_task_output(task_dir=task_dir, result=result)
        artifact_paths = []
        for artifact in (task_dir / "stdout.txt", task_dir / "stderr.txt"):
            if artifact.exists() and artifact.stat().st_size > 0:
                artifact_paths.append(str(artifact))
        output = result.stdout.strip() or result.stderr.strip()
        summary = (
            f"Command succeeded (exit={result.returncode}): {command}"
            if result.success
            else f"Command failed (exit={result.returncode}): {command}"
        )
        return {
            "success": result.success,
            "status": "executed" if result.success else "failed",
            "summary": summary,
            "output": output,
            "artifacts": artifact_paths,
            "metadata": {
                "command": command,
                "returncode": result.returncode,
                "duration_seconds": round(result.duration_seconds, 2),
                "timed_out": result.timed_out,
                "cwd": str(safe_cwd) if safe_cwd else "",
                "shell_executable": self.command_runner.shell_executable,
            },
        }

    def _open_url(self, args: Dict[str, object]) -> Dict[str, object]:
        url = str(args.get("url", "")).strip()
        if not url:
            return self._error("Missing URL.")
        webbrowser.open(url, new=2)
        return {
            "success": True,
            "status": "executed",
            "summary": f"Opened URL: {url}",
            "output": url,
            "artifacts": [],
            "metadata": {"url": url},
        }

    def _list_directory(self, args: Dict[str, object], working_directory: Path | None) -> Dict[str, object]:
        path_raw = str(args.get("path", "")).strip()
        base = Path(path_raw) if path_raw else (working_directory or Path.cwd())
        safe_path = self._sanitize_path(base, working_directory)
        if not safe_path.exists():
            return self._error(f"Directory not found: {safe_path}")
        if not safe_path.is_dir():
            return self._error(f"Path is not a directory: {safe_path}")

        lines = []
        for child in sorted(safe_path.iterdir(), key=lambda p: (p.is_file(), p.name.lower())):
            marker = "dir" if child.is_dir() else "file"
            lines.append(f"{marker}\t{child.name}")

        output = "\n".join(lines)
        return {
            "success": True,
            "status": "executed",
            "summary": f"Listed directory: {safe_path}",
            "output": output,
            "artifacts": [],
            "metadata": {"path": str(safe_path), "count": len(lines)},
        }

    def _read_file(self, args: Dict[str, object], working_directory: Path | None) -> Dict[str, object]:
        path_raw = str(args.get("path", "")).strip()
        if not path_raw:
            return self._error("Missing path for read_file.")
        safe_path = self._sanitize_path(Path(path_raw), working_directory)
        if not safe_path.exists():
            return self._error(f"File not found: {safe_path}")
        if not safe_path.is_file():
            return self._error(f"Path is not a file: {safe_path}")

        max_chars = int(args.get("max_chars", 12000))
        content = safe_path.read_text(encoding="utf-8", errors="ignore")
        trimmed = content[:max_chars]
        return {
            "success": True,
            "status": "executed",
            "summary": f"Read file: {safe_path}",
            "output": trimmed,
            "artifacts": [],
            "metadata": {"path": str(safe_path), "truncated": len(content) > len(trimmed)},
        }

    def _write_file(self, args: Dict[str, object], working_directory: Path | None) -> Dict[str, object]:
        path_raw = str(args.get("path", "")).strip()
        if not path_raw:
            return self._error("Missing path for write_file.")
        content = str(args.get("content", ""))
        overwrite = bool(args.get("overwrite", True))
        safe_path = self._sanitize_path(Path(path_raw), working_directory)
        if safe_path.exists() and not overwrite:
            return self._error(f"Refusing to overwrite existing file: {safe_path}")
        safe_path.parent.mkdir(parents=True, exist_ok=True)
        safe_path.write_text(content, encoding="utf-8")
        return {
            "success": True,
            "status": "executed",
            "summary": f"Wrote file: {safe_path}",
            "output": "",
            "artifacts": [str(safe_path)],
            "metadata": {"path": str(safe_path), "bytes": len(content.encode('utf-8'))},
        }

    def _take_screenshot(self, task_dir: Path) -> Dict[str, object]:
        output_dir = task_dir / "screenshots"
        output_dir.mkdir(parents=True, exist_ok=True)
        image_path = output_dir / f"screenshot_{int(time.time())}.png"
        take_screenshot(image_path)
        return {
            "success": True,
            "status": "executed",
            "summary": "Screenshot captured.",
            "output": str(image_path),
            "artifacts": [str(image_path)],
            "metadata": {"path": str(image_path)},
        }

    def _find_files(self, args: Dict[str, object], working_directory: Path | None) -> Dict[str, object]:
        pattern = str(args.get("pattern", "")).strip()
        if not pattern:
            return self._error("Missing pattern for find_files.")
        root_raw = str(args.get("path", ".")).strip() or "."
        safe_root = self._sanitize_path(Path(root_raw), working_directory)
        if not safe_root.is_dir():
            return self._error(f"Path is not a directory: {safe_root}")

        include_hidden = bool(args.get("include_hidden", False))
        max_results = max(1, min(int(args.get("max_results", 200)), 1000))
        matches = []
        total = 0
        for file_path in self._iter_files(safe_root, include_hidden=include_hidden):
            rel = str(file_path.relative_to(safe_root))
            if fnmatch.fnmatch(file_path.name, pattern) or fnmatch.fnmatch(rel, pattern):
                total += 1
                if len(matches) < max_results:
                    matches.append(rel)

        output = "\n".join(matches)
        summary = f"Found {total} file(s) matching '{pattern}' under {safe_root}"
        if total > len(matches):
            summary += f" (showing first {len(matches)})"
        return {
            "success": True,
            "status": "executed",
            "summary": summary,
            "output": output,
            "artifacts": [],
            "metadata": {
                "path": str(safe_root),
                "pattern": pattern,
                "match_count": total,
                "truncated": total > len(matches),
            },
        }

    def _search_text(self, args: Dict[str, object], working_directory: Path | None) -> Dict[str, object]:
        query = str(args.get("query", "")).strip()
        if not query:
            return self._error("Missing query for search_text.")
        root_raw = str(args.get("path", ".")).strip() or "."
        safe_root = self._sanitize_path(Path(root_raw), working_directory)
        if not safe_root.is_dir():
            return self._error(f"Path is not a directory: {safe_root}")

        glob_pattern = str(args.get("glob", "*")).strip() or "*"
        include_hidden = bool(args.get("include_hidden", False))
        case_sensitive = bool(args.get("case_sensitive", False))
        max_results = max(1, min(int(args.get("max_results", 100)), 1000))
        comparisons = 0
        matches = []
        needle = query if case_sensitive else query.lower()

        for file_path in self._iter_files(safe_root, include_hidden=include_hidden):
            rel = str(file_path.relative_to(safe_root))
            if not (fnmatch.fnmatch(file_path.name, glob_pattern) or fnmatch.fnmatch(rel, glob_pattern)):
                continue
            if file_path.stat().st_size > 1024 * 1024:
                continue
            content = file_path.read_text(encoding="utf-8", errors="ignore")
            comparisons += 1
            for line_no, line in enumerate(content.splitlines(), start=1):
                haystack = line if case_sensitive else line.lower()
                if needle in haystack:
                    matches.append(f"{rel}:{line_no}: {line.strip()[:180]}")
                    if len(matches) >= max_results:
                        break
            if len(matches) >= max_results:
                break

        return {
            "success": True,
            "status": "executed",
            "summary": f"Found {len(matches)} text match(es) for '{query}' under {safe_root}",
            "output": "\n".join(matches),
            "artifacts": [],
            "metadata": {
                "path": str(safe_root),
                "query": query,
                "glob": glob_pattern,
                "files_scanned": comparisons,
                "match_count": len(matches),
            },
        }

    def _read_multiple_files(self, args: Dict[str, object], working_directory: Path | None) -> Dict[str, object]:
        raw_paths = args.get("paths", [])
        if not isinstance(raw_paths, list) or not raw_paths:
            return self._error("Missing paths for read_multiple_files.")

        max_chars_per_file = max(1, min(int(args.get("max_chars_per_file", 4000)), 20000))
        sections = []
        truncated_files = []
        resolved_paths = []

        for item in raw_paths:
            safe_path = self._sanitize_path(Path(str(item)), working_directory)
            if not safe_path.exists() or not safe_path.is_file():
                return self._error(f"File not found: {safe_path}")
            content = safe_path.read_text(encoding="utf-8", errors="ignore")
            trimmed = content[:max_chars_per_file]
            if len(content) > len(trimmed):
                truncated_files.append(str(safe_path))
            sections.append(f"==> {safe_path} <==\n{trimmed}")
            resolved_paths.append(str(safe_path))

        return {
            "success": True,
            "status": "executed",
            "summary": f"Read {len(resolved_paths)} file(s).",
            "output": "\n\n".join(sections),
            "artifacts": [],
            "metadata": {
                "paths": resolved_paths,
                "truncated_files": truncated_files,
            },
        }

    def _get_system_info(self, working_directory: Path | None) -> Dict[str, object]:
        safe_cwd = self._sanitize_working_directory(working_directory)
        lines = [
            f"platform: {platform.system()}",
            f"platform_release: {platform.release()}",
            f"platform_version: {platform.version()}",
            f"python_version: {platform.python_version()}",
            f"working_directory: {safe_cwd if safe_cwd else ''}",
            f"shell_executable: {self.command_runner.shell_executable}",
            "allowed_workdirs:",
        ]
        for root in self.settings.allowed_workdirs:
            lines.append(f"- {root.resolve()}")
        if psutil is not None:
            memory = psutil.virtual_memory()
            lines.append(f"cpu_count: {psutil.cpu_count(logical=True)}")
            lines.append(f"memory_total_mb: {memory.total // (1024 * 1024)}")
            lines.append(f"memory_available_mb: {memory.available // (1024 * 1024)}")

        return {
            "success": True,
            "status": "executed",
            "summary": "Collected system information.",
            "output": "\n".join(lines),
            "artifacts": [],
            "metadata": {
                "platform": platform.system(),
                "working_directory": str(safe_cwd) if safe_cwd else "",
                "shell_executable": self.command_runner.shell_executable,
            },
        }

    def _respond_only(self, args: Dict[str, object], task_dir: Path) -> Dict[str, object]:
        message = str(args.get("message", "")).strip()
        analysis = str(args.get("analysis", "")).strip()
        proposed_patch = str(args.get("proposed_patch", "")).strip()
        next_action_plan = args.get("next_action_plan", [])

        details: Dict[str, object] = {"message": message}
        artifacts = []

        if analysis:
            details["analysis"] = analysis
        if isinstance(next_action_plan, list):
            details["next_action_plan"] = next_action_plan
        if proposed_patch:
            patches_dir = task_dir / "patches"
            patches_dir.mkdir(parents=True, exist_ok=True)
            patch_path = patches_dir / "proposed_patch.diff"
            patch_path.write_text(proposed_patch, encoding="utf-8")
            details["proposed_patch_path"] = str(patch_path)
            artifacts.append(str(patch_path))

        return {
            "success": True,
            "status": "executed",
            "summary": message or "Responded without local execution.",
            "output": json.dumps(details, ensure_ascii=False, indent=2),
            "artifacts": artifacts,
            "metadata": {},
        }

    def _sanitize_working_directory(self, working_directory: Path | None) -> Path | None:
        if working_directory is None:
            return None
        return ensure_within_roots(working_directory.resolve(), self.settings.allowed_workdirs)

    def _sanitize_path(self, path: Path, working_directory: Path | None) -> Path:
        return ensure_within_roots(resolve_path(path, working_directory), self.settings.allowed_workdirs)

    @staticmethod
    def _append_task_output(task_dir: Path, result: CommandResult) -> None:
        stdout_path = task_dir / "stdout.txt"
        stderr_path = task_dir / "stderr.txt"
        if result.stdout:
            stdout_path.parent.mkdir(parents=True, exist_ok=True)
            with stdout_path.open("a", encoding="utf-8") as out:
                out.write(result.stdout.rstrip("\n") + "\n")
        if result.stderr:
            stderr_path.parent.mkdir(parents=True, exist_ok=True)
            with stderr_path.open("a", encoding="utf-8") as err:
                err.write(result.stderr.rstrip("\n") + "\n")

    @staticmethod
    def _iter_files(root: Path, *, include_hidden: bool) -> Iterable[Path]:
        for candidate in sorted(root.rglob("*")):
            if not candidate.is_file():
                continue
            relative = candidate.relative_to(root)
            if not include_hidden and any(part.startswith(".") for part in relative.parts):
                continue
            yield candidate

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
