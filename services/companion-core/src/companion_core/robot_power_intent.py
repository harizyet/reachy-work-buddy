"""Deterministic intent detection for remote robot power control — same
keyword-matcher honesty as calendar_intent.py, not real NLU. Phase 22b:
owner-requested remote "turn off/standby" and "wake up" commands, so the
robot can be safely handled/moved without a supervised launcher session,
and later woken back up the same way. Matched before the generic
conversation branch ever calls the model — AGENTS.md: "Preserve
deterministic intent/consent precedence... The LLM has no authority to
bypass an action gate." Resume specifically replays the real daemon's
wake-up motion; AGENTS.md/docs/deployment.md record the owner's explicit
exception allowing that unattended via this same owner-authenticated
channel, on the designated production host.
"""

from __future__ import annotations

_STANDBY_PHRASES = (
    "turn off reachy",
    "turn reachy off",
    "shut down reachy",
    "shutdown reachy",
    "standby reachy",
    "stand by reachy",
    "reachy standby",
    "reachy stand by",
    "power off reachy",
    "put reachy away",
)

_RESUME_PHRASES = (
    "turn on reachy",
    "turn reachy on",
    "wake up reachy",
    "wake reachy up",
    "reachy wake up",
    "resume reachy",
    "power on reachy",
)


def is_standby_command(text: str) -> bool:
    lowered = text.lower()
    return any(phrase in lowered for phrase in _STANDBY_PHRASES)


def is_resume_command(text: str) -> bool:
    lowered = text.lower()
    return any(phrase in lowered for phrase in _RESUME_PHRASES)


def _describe_failures(results: list[dict]) -> str:
    return "; ".join(f"{r['robot_id']}: {r.get('error', 'unknown error')}" for r in results if not r.get("ok"))


def format_standby_reply(results: list[dict]) -> str:
    if not results:
        return "No robot is currently registered, so there's nothing to turn off."
    if all(r.get("ok") for r in results):
        return "Reachy is now in standby — safe to move or put away."
    if not any(r.get("ok") for r in results):
        return f"Couldn't put Reachy into standby: {_describe_failures(results)}"
    return f"Reachy standby was only partly successful: {_describe_failures(results)}"


def format_resume_reply(results: list[dict]) -> str:
    if not results:
        return "No robot is currently registered, so there's nothing to wake up."
    if all(r.get("ok") for r in results):
        return "Reachy is waking back up."
    if not any(r.get("ok") for r in results):
        return f"Couldn't wake Reachy up: {_describe_failures(results)}"
    return f"Waking Reachy up was only partly successful: {_describe_failures(results)}"
