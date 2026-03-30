"""Helpers for resolving paths under allowed work directories."""

from __future__ import annotations

from pathlib import Path
from typing import Iterable


def resolve_path(path: Path, working_directory: Path | None) -> Path:
    """Resolve a path relative to the working directory when needed."""

    return (path if path.is_absolute() else (working_directory or Path.cwd()) / path).resolve()


def is_within_roots(path: Path, roots: Iterable[Path]) -> bool:
    """Return whether a path stays under one of the allowed roots."""

    resolved = path.resolve()
    for root in roots:
        root_resolved = root.resolve()
        try:
            resolved.relative_to(root_resolved)
            return True
        except ValueError:
            continue
    return False


def ensure_within_roots(path: Path, roots: Iterable[Path]) -> Path:
    """Resolve and validate that a path is under an allowed root."""

    resolved = path.resolve()
    if not is_within_roots(resolved, roots):
        raise PermissionError(f"Path not allowed: {resolved}")
    return resolved
