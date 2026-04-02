"""Lightweight session/project memory helpers for MiniClaw v1."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

from src.orchestrator.context_store import ContextStore
from src.orchestrator.task_manager import TaskManager
from src.utils.path_utils import find_project_root


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _today_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _compact_line(text: str, *, limit: int = 280) -> str:
    value = " ".join(str(text).strip().split())
    if not value:
        return ""
    return value if len(value) <= limit else f"{value[: limit - 3].rstrip()}..."


class MemoryService:
    """Keeps session summaries and lightweight project memory files in sync."""

    STOP_WORDS = {
        "the",
        "and",
        "for",
        "with",
        "that",
        "this",
        "from",
        "into",
        "about",
        "then",
        "what",
        "when",
        "where",
        "which",
        "your",
        "have",
        "will",
        "them",
        "they",
        "their",
        "repo",
        "project",
        "code",
    }

    def __init__(self, task_manager: TaskManager, context_store: ContextStore) -> None:
        self.task_manager = task_manager
        self.context_store = context_store

    @staticmethod
    def derive_project_key(working_directory: str) -> str:
        raw = working_directory.strip()
        if not raw:
            return ""
        resolved = Path(raw).resolve()
        project_root = find_project_root(resolved)
        return str((project_root or resolved).resolve())

    def build_planner_memory_context(self, *, session_id: str, instruction: str, project_key: str) -> Dict[str, Any]:
        return {
            "session_summary": self.load_session_summary(session_id),
            "project_memory_snippets": self.load_project_memory_snippets(
                project_key=project_key,
                query=instruction,
            ),
        }

    def load_session_summary(self, session_id: str) -> Dict[str, Any]:
        if not session_id.strip():
            return {}
        payload = self.context_store.load_session_summary(session_id, default={})
        if isinstance(payload, dict) and payload:
            return payload
        session = self.task_manager.get_session(session_id)
        summary = session.get("summary", {}) if session else {}
        return summary if isinstance(summary, dict) else {}

    def update_session_summary(
        self,
        *,
        session_id: str,
        task: Dict[str, Any],
        final_text: str,
        success: bool,
    ) -> Dict[str, Any]:
        if not session_id.strip():
            return {}

        current = self.load_session_summary(session_id)
        known_facts = current.get("known_facts", [])
        if not isinstance(known_facts, list):
            known_facts = []
        recent_decisions = current.get("recent_decisions", [])
        if not isinstance(recent_decisions, list):
            recent_decisions = []
        open_loops = current.get("open_loops", [])
        if not isinstance(open_loops, list):
            open_loops = []

        final_line = _compact_line(final_text)
        if final_line and final_line not in known_facts:
            known_facts.append(final_line)
        known_facts = known_facts[-6:]

        decision_line = _compact_line(
            f"{'Completed' if success else 'Failed'} task {task.get('task_id', '')}: {task.get('instruction', '')}"
        )
        if decision_line:
            recent_decisions.append(decision_line)
        recent_decisions = recent_decisions[-6:]

        if success:
            open_loops = []
        elif final_line:
            open_loops.append(final_line)
            open_loops = open_loops[-4:]

        summary = {
            "goal": _compact_line(str(task.get("instruction", "")), limit=200),
            "known_facts": known_facts,
            "open_loops": open_loops,
            "recent_decisions": recent_decisions,
            "last_task_id": str(task.get("task_id", "")),
            "updated_at": _utc_now(),
        }
        self.context_store.save_session_summary(session_id, summary)
        self.task_manager.update_session(session_id, summary=summary)
        return summary

    def flush_project_memory(
        self,
        *,
        project_key: str,
        working_directory: str,
        task: Dict[str, Any],
        execution_records: List[dict],
        final_text: str,
    ) -> None:
        if not project_key.strip():
            return

        now = _utc_now()
        compact_final = _compact_line(final_text)
        self._sync_project_meta(project_key=project_key, working_directory=working_directory, updated_at=now)
        self._append_daily_note(project_key=project_key, task=task, final_text=compact_final, updated_at=now)
        self._update_memory_file(
            project_key=project_key,
            working_directory=working_directory,
            execution_records=execution_records,
            final_text=compact_final,
        )

    def load_project_memory_snippets(self, *, project_key: str, query: str, limit: int = 4) -> List[Dict[str, str]]:
        if not project_key.strip():
            return []

        snippets: List[Dict[str, str]] = []
        memory_text = self.context_store.load_project_memory_text(project_key)
        if memory_text.strip():
            selected = self._select_relevant_lines(memory_text, query, fallback_limit=3)
            if selected:
                snippets.append({"source": "MEMORY.md", "text": "\n".join(selected)})

        note_text = self.context_store.load_project_note_text(project_key, _today_utc())
        if note_text.strip():
            selected = self._select_relevant_lines(note_text, query, fallback_limit=2)
            if selected:
                snippets.append({"source": f"notes/{_today_utc()}.md", "text": "\n".join(selected)})

        return snippets[:limit]

    def _sync_project_meta(self, *, project_key: str, working_directory: str, updated_at: str) -> None:
        current = self.context_store.load_project_meta(project_key, default={})
        payload = current if isinstance(current, dict) else {}
        payload.setdefault("project_key", project_key)
        payload.setdefault("working_directory", working_directory)
        payload.setdefault("created_at", updated_at)
        payload["updated_at"] = updated_at
        self.context_store.save_project_meta(project_key, payload)

    def _append_daily_note(
        self,
        *,
        project_key: str,
        task: Dict[str, Any],
        final_text: str,
        updated_at: str,
    ) -> None:
        lines = [
            f"## {updated_at} task {task.get('task_id', '')}",
            f"- instruction: {_compact_line(str(task.get('instruction', '')), limit=400)}",
        ]
        if final_text:
            lines.append(f"- summary: {final_text}")
        self.context_store.append_project_note(project_key, _today_utc(), "\n".join(lines) + "\n")

    def _update_memory_file(
        self,
        *,
        project_key: str,
        working_directory: str,
        execution_records: List[dict],
        final_text: str,
    ) -> None:
        current = self.context_store.load_project_memory_text(project_key)
        if not current.strip():
            current = (
                "# Project Memory\n\n"
                "## Repo Facts\n\n"
                f"- Default working directory: {working_directory}\n\n"
                "## Useful Commands\n\n"
            )

        next_text = current
        if final_text:
            next_text = self._append_section_bullet(next_text, "Repo Facts", final_text)

        for item in execution_records:
            if not isinstance(item, dict):
                continue
            if str(item.get("action_type", "")) != "run_command":
                continue
            if not bool(item.get("success", False)):
                continue
            command = _compact_line(str(item.get("args", {}).get("command", "")), limit=180)
            if command:
                next_text = self._append_section_bullet(next_text, "Useful Commands", command)

        if next_text != current:
            self.context_store.write_project_memory_text(project_key, next_text)

    def _select_relevant_lines(self, text: str, query: str, *, fallback_limit: int) -> List[str]:
        lines = [_compact_line(line, limit=260) for line in text.splitlines()]
        lines = [line for line in lines if line and not line.startswith("#")]
        if not lines:
            return []

        tokens = self._query_tokens(query)
        scored: List[tuple[int, str]] = []
        for line in lines:
            lowered = line.lower()
            score = sum(1 for token in tokens if token in lowered)
            if score > 0:
                scored.append((score, line))

        if not scored:
            return lines[:fallback_limit]

        scored.sort(key=lambda item: (-item[0], item[1]))
        selected: List[str] = []
        for _, line in scored:
            if line not in selected:
                selected.append(line)
            if len(selected) >= fallback_limit:
                break
        return selected

    def _query_tokens(self, query: str) -> List[str]:
        tokens: List[str] = []
        for raw in query.lower().replace("/", " ").replace("_", " ").split():
            token = raw.strip(".,:;!?()[]{}<>\"'`")
            if len(token) < 3 or token in self.STOP_WORDS:
                continue
            if token not in tokens:
                tokens.append(token)
        return tokens

    def _append_section_bullet(self, text: str, section_title: str, bullet: str) -> str:
        normalized_bullet = _compact_line(bullet)
        if not normalized_bullet:
            return text
        bullet_line = f"- {normalized_bullet}"
        if bullet_line in text:
            return text

        heading = f"## {section_title}"
        if heading not in text:
            text = text.rstrip() + f"\n\n{heading}\n\n"

        marker = text.index(heading)
        after_heading = text[marker + len(heading) :]
        insert_at = marker + len(heading)
        if after_heading.startswith("\n\n"):
            insert_at += 2
        elif after_heading.startswith("\n"):
            insert_at += 1

        next_heading = text.find("\n## ", insert_at)
        section_body = text[insert_at: next_heading if next_heading != -1 else len(text)]
        if section_body and not section_body.endswith("\n"):
            section_body += "\n"
        section_body += bullet_line + "\n"

        if next_heading == -1:
            return text[:insert_at] + section_body
        return text[:insert_at] + section_body + text[next_heading:]
