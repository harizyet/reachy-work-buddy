"""Reply formatting for reachy-hub's per-robot standby/resume/status
results — moved from the retired robot_power_intent.py (Phase 24b); pure
formatting, carries no authority to actuate anything."""

from __future__ import annotations


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


def format_status_reply(robots: list[dict], states: dict[str, str]) -> str:
    if not robots:
        return "No robot is currently registered."
    lines = []
    for robot in robots:
        robot_id = robot["robot_id"]
        lines.append(f"{robot_id}: {states.get(robot_id, 'unreachable')}")
    return "\n".join(lines)
