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

# Only actions actually wired to a hub call in app.py — docs/phase-24b.md's
# `/reachy gesture <name>` is illustrative syntax for a later extension, not
# something this phase implements; parsing an action this codebase can't yet
# execute would be a dangling command, not a real one.
_KNOWN_ACTIONS = {"standby", "wake", "status"}

# Telegram's BotCommand.command field cannot contain a space, so
# `/reachy standby` cannot itself be registered as a single Telegram menu
# entry. These flat aliases are registered there instead (see
# companion_core/telegram_commands.py); every channel accepts both forms
# as input text, and both parse to the identical Command below
# (docs/phase-24b.md "Channel handling").
TELEGRAM_ALIASES: dict[str, tuple[str, str]] = {
    "standby": ("reachy", "standby"),
    "wake": ("reachy", "wake"),
    "reachy_status": ("reachy", "status"),
}


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
    head = parts[0].lower()

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
