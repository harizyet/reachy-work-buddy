"""Deterministic (not LLM) intent matching for owner questions about
coding-agent sessions — same "a keyword matcher, not real NLU" honesty as
calendar_intent.py. Phase 29's actual exit criterion here is that the
*answer* is computed from a real session/usage read, not that the
question-understanding be sophisticated.
"""

from __future__ import annotations

from typing import Any

_STATUS_PHRASES = (
    "is my coding session done", "is my code session done", "is my claude session done",
    "did claude finish", "is claude done", "is claude finished", "claude finished yet",
    "claude done yet", "check my coding session", "check my claude session",
    "coding agent status", "coding session status", "claude code status",
    "how is my coding session", "how's my coding session", "how is my claude session",
)

_USAGE_PHRASES = (
    "claude usage", "claude code usage", "coding agent usage", "check my claude usage",
    "check my coding usage", "how much usage", "usage limit", "claude credits",
)

# 29.5: never claimed COMPLETED/FAILED without a real provider result
# (29.8); these are exactly the terminal statuses worth reporting distinctly.
_TERMINAL_LABELS = {
    "completed": "finished",
    "failed": "failed",
    "stopped": "was stopped",
    "lost": "was lost (its container stopped unexpectedly)",
}


def is_status_query(text: str) -> bool:
    lowered = text.lower()
    return any(phrase in lowered for phrase in _STATUS_PHRASES)


def is_usage_query(text: str) -> bool:
    lowered = text.lower()
    return any(phrase in lowered for phrase in _USAGE_PHRASES)


def _label(session: dict[str, Any]) -> str:
    status = session["status"]
    return _TERMINAL_LABELS.get(status, status.replace("_", " "))


def format_status_reply(sessions: list[dict[str, Any]] | None) -> str:
    if sessions is None:
        return "I can't reach the coding-agent service right now."
    if not sessions:
        return "You have no coding-agent sessions."
    ordered = sorted(sessions, key=lambda s: s["started_at"], reverse=True)
    lines = [f"{s['task_summary']} ({s['provider']}): {_label(s)}" for s in ordered]
    return "Coding-agent sessions:\n" + "\n".join(lines)


def format_usage_reply(sessions: list[dict[str, Any]] | None, usage_by_session_id: dict[str, dict[str, Any]]) -> str:
    """29.26: usage is not a universal contract — only report dimensions a
    provider actually measured, never a guessed/zero value for one it
    didn't."""
    if sessions is None:
        return "I can't reach the coding-agent service right now."
    active = [s for s in sessions if s["status"] not in _TERMINAL_LABELS]
    if not active:
        return "You have no active coding-agent sessions."
    lines = []
    for session in active:
        usage = usage_by_session_id.get(session["id"])
        dimensions = usage.get("dimensions", []) if usage else []
        if not dimensions:
            lines.append(f"{session['task_summary']} ({session['provider']}): no usage information available yet.")
            continue
        parts = []
        for dim in dimensions:
            value = f"{dim['value']:.2f}" if dim["unit"] in ("usd", "%") else f"{dim['value']:.0f}"
            parts.append(f"{dim['name'].replace('_', ' ')} {value}{dim['unit']}")
        lines.append(f"{session['task_summary']} ({session['provider']}): " + ", ".join(parts))
    return "Coding-agent usage:\n" + "\n".join(lines)


def format_completion_notification(session: dict[str, Any]) -> str:
    """What reachy-hub pushes to Telegram for one newly-claimed completion
    (GET /coding-agents/completions/due). 29.8: states what actually
    happened — "stopped and is waiting"-style honesty, not an inferred
    success claim beyond what the session's own status already says."""
    return f"Claude Code session '{session['task_summary']}' {_label(session)}."


def is_terminal(status: str) -> bool:
    return status in _TERMINAL_LABELS
