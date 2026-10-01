"""Read-only discovery of Claude Code sessions started outside Reachy, from a
mounted copy of the host's ~/.claude/projects history. Only the head and tail
of each log are read, and only the newest files are considered."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from shared.models.coding_agent import TerminalSession

_CHUNK = 64 * 1024
_MAX_FILES = 40
_ACTIVE_WINDOW_SECONDS = 120
_TEXT_LIMIT = 300


def _lines(path: Path, *, tail: bool) -> list[dict]:
    with path.open("rb") as handle:
        if tail:
            size = handle.seek(0, 2)
            handle.seek(max(0, size - _CHUNK))
        raw = handle.read(_CHUNK)
    entries = []
    # The first/last line of a chunk may be cut off mid-record; skip what
    # does not parse.
    for line in raw.splitlines():
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        if isinstance(entry, dict):
            entries.append(entry)
    return entries


def _user_text(entry: dict) -> str | None:
    if entry.get("type") != "user" or entry.get("isMeta") or entry.get("isSidechain"):
        return None
    content = (entry.get("message") or {}).get("content")
    if not isinstance(content, str):
        return None
    content = content.strip()
    # Slash-command wrappers and injected reminders are not the owner's task.
    if not content or content.startswith("<"):
        return None
    return content[:_TEXT_LIMIT]


def _describe(path: Path, modified: float) -> TerminalSession:
    head = _lines(path, tail=False)
    tail = _lines(path, tail=True)
    entries = head + tail
    title = next(
        (
            e.get("customTitle")
            for e in reversed(entries)
            if e.get("type") == "custom-title"
        ),
        None,
    )
    first_prompt = next((t for t in map(_user_text, head) if t), None)
    last_prompt = next(
        (e.get("lastPrompt") for e in reversed(tail) if e.get("type") == "last-prompt"),
        None,
    )
    if last_prompt is None:
        last_prompt = next((t for t in map(_user_text, reversed(tail)) if t), None)
    cwd = next((e["cwd"] for e in head if isinstance(e.get("cwd"), str)), None)
    branch = next(
        (e["gitBranch"] for e in reversed(tail) if isinstance(e.get("gitBranch"), str)),
        None,
    )
    now = datetime.now(UTC).timestamp()
    return TerminalSession(
        session_id=path.stem,
        project_path=cwd,
        git_branch=branch,
        title=(title or first_prompt or "")[:_TEXT_LIMIT] or None,
        last_prompt=str(last_prompt)[:_TEXT_LIMIT] if last_prompt else None,
        last_activity_at=datetime.fromtimestamp(modified, UTC),
        active=now - modified < _ACTIVE_WINDOW_SECONDS,
    )


def list_terminal_sessions(root: Path | None) -> list[TerminalSession]:
    if root is None or not root.is_dir():
        return []
    files = []
    for path in root.glob("*/*.jsonl"):
        try:
            files.append((path.stat().st_mtime, path))
        except OSError:
            continue
    sessions = []
    for modified, path in sorted(files, reverse=True)[:_MAX_FILES]:
        try:
            sessions.append(_describe(path, modified))
        except OSError:
            continue
    return sessions
