"""System-level executor for local filesystem and command actions."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Callable, Dict, Optional

from raida.config import Settings
from raida.utils.command_runner import CommandResult, CommandRunner
from raida.utils.logger import get_logger

logger = get_logger(__name__)


class SystemExecutor:
    """Executes non-GUI local actions on the host machine."""

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
            if action_type == "list_directory":
                return self._list_directory(args=args, working_directory=working_directory)
            if action_type == "read_file":
                return self._read_file(args=args, working_directory=working_directory)
            if action_type == "write_file":
                return self._write_file(args=args, working_directory=working_directory)
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
            "artifacts": [str(task_dir / "stdout.txt"), str(task_dir / "stderr.txt")],
            "metadata": {
                "command": command,
                "returncode": result.returncode,
                "duration_seconds": round(result.duration_seconds, 2),
                "timed_out": result.timed_out,
                "cwd": str(safe_cwd) if safe_cwd else "",
            },
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
        resolved = working_directory.resolve()
        for allowed in self.settings.allowed_workdirs:
            allowed_resolved = allowed.resolve()
            if resolved == allowed_resolved or str(resolved).startswith(str(allowed_resolved)):
                return resolved
        raise PermissionError(f"Working directory not allowed: {resolved}")

    def _sanitize_path(self, path: Path, working_directory: Path | None) -> Path:
        resolved = path if path.is_absolute() else (working_directory or Path.cwd()) / path
        resolved = resolved.resolve()
        for allowed in self.settings.allowed_workdirs:
            allowed_resolved = allowed.resolve()
            if resolved == allowed_resolved or str(resolved).startswith(str(allowed_resolved)):
                return resolved
        raise PermissionError(f"Path not allowed: {resolved}")

    @staticmethod
    def _append_task_output(task_dir: Path, result: CommandResult) -> None:
        stdout_path = task_dir / "stdout.txt"
        stderr_path = task_dir / "stderr.txt"
        stdout_path.parent.mkdir(parents=True, exist_ok=True)
        with stdout_path.open("a", encoding="utf-8") as out:
            if result.stdout:
                out.write(result.stdout.rstrip("\n") + "\n")
        with stderr_path.open("a", encoding="utf-8") as err:
            if result.stderr:
                err.write(result.stderr.rstrip("\n") + "\n")

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

