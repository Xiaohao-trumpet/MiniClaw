"""Subprocess command execution with streaming callbacks."""

from __future__ import annotations

import subprocess
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

    def run(
        self,
        command: str,
        cwd: Path | None = None,
        timeout_seconds: Optional[int] = None,
        env: Optional[Dict[str, str]] = None,
        on_output: Optional[Callable[[str], None]] = None,
    ) -> CommandResult:
        started = time.monotonic()
        collected: list[str] = []
        timed_out = False

        process = subprocess.Popen(
            command,
            cwd=str(cwd) if cwd else None,
            env=env,
            shell=True,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            bufsize=1,
        )

        assert process.stdout is not None
        while True:
            line = process.stdout.readline()
            if line:
                collected.append(line)
                if on_output:
                    on_output(line.rstrip("\n"))
            elif process.poll() is not None:
                break
            else:
                time.sleep(0.05)

            if timeout_seconds and (time.monotonic() - started) > timeout_seconds:
                timed_out = True
                process.kill()
                break

        returncode = process.wait()
        stdout = "".join(collected)
        stderr = "Command timed out." if timed_out else ""

        return CommandResult(
            command=command,
            returncode=returncode if not timed_out else 124,
            stdout=stdout,
            stderr=stderr,
            duration_seconds=time.monotonic() - started,
            timed_out=timed_out,
        )

