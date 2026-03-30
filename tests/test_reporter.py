from pathlib import Path

from src.orchestrator.reporter import Reporter


class DummyGateway:
    def __init__(self) -> None:
        self.messages: list[str] = []
        self.images: list[str] = []
        self.files: list[str] = []

    def send_message(self, user_id: str, text: str) -> None:  # noqa: ARG002
        self.messages.append(text)

    def send_image(self, user_id: str, image_path: str) -> None:  # noqa: ARG002
        self.images.append(image_path)

    def send_file(self, user_id: str, file_path: str) -> None:  # noqa: ARG002
        self.files.append(file_path)


def test_maybe_send_path_skips_empty_file(tmp_path: Path) -> None:
    gateway = DummyGateway()
    reporter = Reporter(gateway)
    empty_file = tmp_path / "empty.txt"
    empty_file.write_text("", encoding="utf-8")

    reporter.maybe_send_path("tg_1", empty_file)

    assert gateway.files == []


def test_maybe_send_path_sends_non_empty_file(tmp_path: Path) -> None:
    gateway = DummyGateway()
    reporter = Reporter(gateway)
    non_empty_file = tmp_path / "stdout.txt"
    non_empty_file.write_text("hello", encoding="utf-8")

    reporter.maybe_send_path("tg_1", non_empty_file)

    assert gateway.files == [str(non_empty_file)]


def test_action_output_truncates_preview() -> None:
    gateway = DummyGateway()
    reporter = Reporter(gateway)

    reporter.action_output("tg_1", "task-1", "run_command", "abcdef", max_chars=3)

    assert any("Action output (run_command)" in item for item in gateway.messages)
    assert any("abc" in item and "...[truncated]" in item for item in gateway.messages)
