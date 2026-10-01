"""Deterministic slash-command parser (Phase 24b, docs/phase-24b.md).

Free-form conversational text is never, by itself, sufficient
authorization for a consequential action — see
companion_core/command_suggestion.py for the separate, non-authoritative
natural-language suggestion path. This module is the *only* place a
`Command` value is constructed, and only an explicit `/reachy <action>`
(or a registered channel alias) can produce one. Evaluated before both
the existing deterministic-intent chain and the generic LLM branch in
app.py — the same precedence position the now-retired
`robot_power_intent` substring matcher used to occupy.
"""

from __future__ import annotations

from dataclasses import dataclass

from shared.protocols.commands import COMMANDS, QUERY_COMMANDS

_KNOWN_ACTIONS = {action for _, action, _, _ in COMMANDS}
_QUERY_ARGUMENTS = {action: argument for _, action, _, argument in QUERY_COMMANDS}
TELEGRAM_ALIASES = {alias: ("reachy", action) for alias, action, _, _ in COMMANDS}


def format_help() -> str:
    return "Available commands:\n" + "\n".join(
        f"/{alias}" + (f" <{argument}>" if argument else "") + f" — {description}"
        for alias, _, description, argument in COMMANDS
    )


def query_usage_error(command: Command) -> str | None:
    if command.action not in _QUERY_ARGUMENTS:
        return None
    argument = _QUERY_ARGUMENTS[command.action]
    if bool(command.argument) != bool(argument):
        suffix = f" <{argument}>" if argument else ""
        return f"Usage: /{command.action}{suffix}"
    return None


@dataclass(frozen=True)
class Command:
    namespace: str
    action: str
    argument: str | None = None


def parse(text: str) -> Command | None:
    stripped = text.strip()
    if not stripped.startswith("/"):
        return None
    body = stripped[1:]
    if not body:
        return None
    parts = body.split()
    # Telegram may append @bot_username when selecting a command.
    head = parts[0].lower().split("@", 1)[0]

    if head == "reachy":
        if len(parts) < 2:
            return None
        action = parts[1].lower()
        if action not in _KNOWN_ACTIONS:
            return None
        argument = " ".join(parts[2:]) if len(parts) > 2 else None
        return Command(namespace="reachy", action=action, argument=argument)

    alias = TELEGRAM_ALIASES.get(head)
    if alias is not None:
        argument = " ".join(parts[1:]) if len(parts) > 1 else None
        return Command(namespace=alias[0], action=alias[1], argument=argument)

    return None
