"""Subprocess command execution with streaming callbacks."""

from __future__ import annotations

import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, Optional


@dataclass
class CommandResult:
    """Represents the result of running a shell command."""

    command: str
    returncode: int
    stdout: str
    stderr: str
    duration_seconds: float
    timed_out: bool = False

    @property
    def success(self) -> bool:
        return self.returncode == 0 and not self.timed_out


class CommandRunner:
    """Runs shell commands and streams output incrementally."""

    def __init__(self, shell_executable: str = "") -> None:
        self._shell_executable = shell_executable.strip()

    @property
    def shell_executable(self) -> str:
        return self._shell_executable

    def run(
        self,
        command: str,
        cwd: Path | None = None,
        timeout_seconds: Optional[int] = None,
        env: Optional[Dict[str, str]] = None,
        on_output: Optional[Callable[[str], None]] = None,
    ) -> CommandResult:
        started = time.monotonic()
        stdout_lines: list[str] = []
        stderr_lines: list[str] = []
        timed_out = False

        process = subprocess.Popen(
            command,
            cwd=str(cwd) if cwd else None,
            env=env,
            shell=True,
            executable=self._shell_executable or None,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=1,
        )

        assert process.stdout is not None
        assert process.stderr is not None

        def _read_stream(stream, sink: list[str], prefix: str = "") -> None:
            while True:
                line = stream.readline()
                if not line:
                    break
                sink.append(line)
                if on_output:
                    on_output(f"{prefix}{line.rstrip()}")

        stdout_thread = threading.Thread(
            target=_read_stream,
            args=(process.stdout, stdout_lines, ""),
            daemon=True,
        )
        stderr_thread = threading.Thread(
            target=_read_stream,
            args=(process.stderr, stderr_lines, "[stderr] "),
            daemon=True,
        )
        stdout_thread.start()
        stderr_thread.start()

        while process.poll() is None:
            if timeout_seconds and (time.monotonic() - started) > timeout_seconds:
                timed_out = True
                process.kill()
                break
            time.sleep(0.05)

        returncode = process.wait()
        stdout_thread.join(timeout=1)
        stderr_thread.join(timeout=1)

        stdout = "".join(stdout_lines)
        stderr = "".join(stderr_lines)
        if timed_out:
            stderr = f"{stderr}\nCommand timed out.".strip()

        return CommandResult(
            command=command,
            returncode=returncode if not timed_out else 124,
            stdout=stdout,
            stderr=stderr,
            duration_seconds=time.monotonic() - started,
            timed_out=timed_out,
        )
