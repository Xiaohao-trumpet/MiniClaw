import sys

from raida.utils.command_runner import CommandRunner


def test_command_runner_captures_stdout_and_stderr() -> None:
    runner = CommandRunner()
    command = f"\"{sys.executable}\" -c \"import sys; print('ok'); print('err', file=sys.stderr)\""
    result = runner.run(command=command, timeout_seconds=10)
    assert result.success is True
    assert "ok" in result.stdout
    assert "err" in result.stderr


def test_command_runner_timeout() -> None:
    runner = CommandRunner()
    command = f"\"{sys.executable}\" -c \"import time; time.sleep(2)\""
    result = runner.run(command=command, timeout_seconds=1)
    assert result.success is False
    assert result.timed_out is True
    assert result.returncode == 124

