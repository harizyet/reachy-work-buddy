"""Deterministic (not LLM) intent matching for owner questions about
coding-agent sessions — same "a keyword matcher, not real NLU" honesty as
calendar_intent.py. Phase 29's actual exit criterion here is that the
*answer* is computed from a real session/usage read, not that the
question-understanding be sophisticated.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from shared.models.coding_agent import ALLOWANCE_WINDOW_NAMES

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

_STATUS_SCOPE = "I can only see sessions managed by Reachy, not other terminal sessions."
_USAGE_SCOPE = (
    "Session figures cover only sessions recorded by Reachy, not account-wide usage. Allowance figures are "
    "what Claude Code last reported during those sessions, not a live reading of "
    "your account quota."
)
_LIVE_ALLOWANCE_SCOPE = "Allowance figures are a live reading of your Claude account."
_NO_ALLOWANCE = (
    "Claude Code has not reported your allowance windows to Reachy; it only does "
    "so as you approach a limit."
)

# A phone reply stays readable; the full history remains in the service.
DISPLAY_LIMIT = 5

_ALLOWANCE_LABELS = {
    "five_hour_window": "5-hour window",
    "weekly_window": "weekly window",
    "weekly_opus_window": "weekly Opus window",
    "weekly_sonnet_window": "weekly Sonnet window",
}

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
    # Usage questions can also mention session status; usage takes precedence.
    if is_usage_query(text):
        return False
    subject = re.search(r"\b(?:claude(?:[ -]code)?|codex|coding[ -](?:agent|session)s?)\b", lowered)
    status = re.search(r"\b(?:sessions?|running|active|done|finished|completed|status)\b", lowered)
    return any(phrase in lowered for phrase in _STATUS_PHRASES) or bool(subject and status)


def is_usage_query(text: str) -> bool:
    lowered = text.lower()
    return any(phrase in lowered for phrase in _USAGE_PHRASES)


def _label(session: dict[str, Any]) -> str:
    status = session["status"]
    return _TERMINAL_LABELS.get(status, status.replace("_", " "))


def recent_sessions(sessions: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], int]:
    """The newest DISPLAY_LIMIT sessions, and how many older ones were left out."""
    ordered = sorted(sessions, key=lambda s: s["started_at"], reverse=True)
    return ordered[:DISPLAY_LIMIT], max(0, len(ordered) - DISPLAY_LIMIT)


def _older_line(omitted: int) -> str:
    return f"...and {omitted} older session{'s' if omitted != 1 else ''}.\n" if omitted else ""


def format_status_reply(sessions: list[dict[str, Any]] | None) -> str:
    if sessions is None:
        return "I can't reach the coding-agent service right now."
    if not sessions:
        return "I have no recorded coding-agent sessions managed by Reachy. " + _STATUS_SCOPE
    shown, omitted = recent_sessions(sessions)
    lines = [f"{s['task_summary']} ({s['provider']}): {_label(s)}" for s in shown]
    return (
        "Coding-agent sessions (last recorded status):\n" + "\n".join(lines) + "\n"
        + _older_line(omitted) + _STATUS_SCOPE
    )


def _reset_text(resets_at: str, now: datetime, timezone: str) -> str:
    zone = ZoneInfo(timezone)
    local = datetime.fromisoformat(resets_at).astimezone(zone)
    clock = local.strftime("%I:%M %p").lstrip("0")
    if local.date() == now.astimezone(zone).date():
        return f"today {clock}"
    return f"{local.strftime('%a')} {clock}"


def format_allowance_lines(
    allowances: list[dict[str, Any]], now: datetime, timezone: str
) -> list[str]:
    """One line per still-open window. An empty allowance is never rendered
    as 0% used — the CLI reports utilization only near a limit."""
    lines = []
    for allowance in allowances:
        for window in allowance.get("windows", []):
            if window["name"] not in ALLOWANCE_WINDOW_NAMES or not window.get("resets_at"):
                continue
            label = _ALLOWANCE_LABELS.get(window["name"], window["name"].replace("_", " "))
            lines.append(
                f"Claude {label}: {window['value']:.0f}% used, resets {_reset_text(window['resets_at'], now, timezone)}"
            )
    return lines


def format_usage_reply(
    sessions: list[dict[str, Any]] | None,
    usage_by_session_id: dict[str, dict[str, Any]],
    allowance_lines: list[str] | None = None,
    allowance_live: bool = False,
) -> str:
    """29.26: usage is not a universal contract — only report dimensions a
    provider actually measured, never a guessed/zero value for one it
    didn't."""
    if sessions is None:
        return "I can't reach the coding-agent service right now."
    if not sessions:
        if allowance_lines:
            return (
                "\n".join(allowance_lines) + "\nI have no recorded coding-agent sessions managed by Reachy. "
                + (_LIVE_ALLOWANCE_SCOPE if allowance_live else _USAGE_SCOPE)
            )
        return "I have no recorded coding-agent usage for sessions managed by Reachy. " + _USAGE_SCOPE
    shown, omitted = recent_sessions(sessions)
    lines = []
    for session in shown:
        usage = usage_by_session_id.get(session["id"])
        dimensions = [
            dim for dim in (usage.get("dimensions", []) if usage else [])
            if dim["name"] not in ALLOWANCE_WINDOW_NAMES
        ]
        if not dimensions:
            lines.append(f"{session['task_summary']} ({session['provider']}): no usage information available yet.")
            continue
        parts = []
        for dim in dimensions:
            value = f"{dim['value']:.2f}" if dim["unit"] in ("usd", "%") else f"{dim['value']:.0f}"
            parts.append(f"{dim['name'].replace('_', ' ')} {value}{dim['unit']}")
        lines.append(f"{session['task_summary']} ({session['provider']}): " + ", ".join(parts))
    allowance = "\n".join(allowance_lines) if allowance_lines else _NO_ALLOWANCE
    return (
        "Recorded coding-agent usage (including finished sessions):\n" + "\n".join(lines) + "\n"
        + _older_line(omitted) + allowance + "\n"
        + (_USAGE_SCOPE + " " + _LIVE_ALLOWANCE_SCOPE if allowance_live and allowance_lines else _USAGE_SCOPE)
    )


def format_completion_notification(session: dict[str, Any]) -> str:
    """What reachy-hub pushes to Telegram for one newly-claimed completion
    (GET /coding-agents/completions/due). 29.8: states what actually
    happened — "stopped and is waiting"-style honesty, not an inferred
    success claim beyond what the session's own status already says."""
    return f"Claude Code session '{session['task_summary']}' {_label(session)}."


def is_terminal(status: str) -> bool:
    return status in _TERMINAL_LABELS
