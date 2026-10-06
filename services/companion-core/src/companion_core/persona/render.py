"""Persona-aware wording for simple deterministic acknowledgements (Phase 39,
ADR 0028, response class B).

Handlers pass facts they already committed; the tone only picks the wording.
The `default` entry is the wording the handlers used before tones existed, so
an unset persona is unchanged. No model call, so no added latency and no way
for the wording to alter a fact."""

from __future__ import annotations

from typing import Final

TEMPLATES: Final[dict[str, dict[str, str]]] = {
    "alarm_set": {
        "default": "Alright, an alarm is set for {when}{station}.",
        "cheery": "Done! Your alarm is set for {when}{station}.",
        "serious": "Alarm set for {when}{station}.",
        "formal": "Your alarm has been scheduled for {when}{station}.",
        "casual": "Sure, alarm set for {when}{station}.",
        "playful": "Done, I'll make some noise at {when}{station}.",
        "calm": "All set. Your alarm is scheduled for {when}{station}.",
    },
    "alarm_declined": {
        "default": "Okay, no alarm.",
        "cheery": "No problem, no alarm!",
        "serious": "No alarm set.",
        "formal": "Understood. No alarm has been set.",
        "casual": "Okay, no alarm.",
        "playful": "Alarm skipped, enjoy the quiet.",
        "calm": "That's fine. No alarm.",
    },
    "task_captured": {
        "default": "Got it, I'll remember: '{text}'.",
        "cheery": "Got it! I've added '{text}' to your list.",
        "serious": "Task recorded: '{text}'.",
        "formal": "I have recorded the following task: '{text}'.",
        "casual": "Got it, '{text}' is on your list.",
        "playful": "Noted, '{text}' is officially on the to-do pile.",
        "calm": "Okay, I've noted '{text}'.",
    },
    "task_completed": {
        "default": "Marked '{text}' as done.",
        "cheery": "Nice work! '{text}' is done.",
        "serious": "'{text}' marked as done.",
        "formal": "The task '{text}' has been marked as complete.",
        "casual": "Okay, '{text}' is done.",
        "playful": "Ticked off: '{text}'. Well played.",
        "calm": "Alright, '{text}' is marked as done.",
    },
    "memory_captured": {
        "default": "I'll remember that: {content}.",
        "cheery": "Got it, I'll remember that: {content}.",
        "serious": "Stored: {content}.",
        "formal": "I have stored the following: {content}.",
        "casual": "Okay, I'll remember that: {content}.",
        "playful": "Filed away in my memory: {content}.",
        "calm": "I'll keep that in mind: {content}.",
    },
    "reminder_added": {
        "default": " I'll also remind you on {when}.",
        "cheery": " I'll also remind you on {when}!",
        "serious": " Reminder set for {when}.",
        "formal": " A reminder has also been scheduled for {when}.",
        "casual": " I'll remind you on {when} too.",
        "playful": " And I'll nudge you on {when}.",
        "calm": " I'll gently remind you on {when}.",
    },
}


def render(event: str, tone: str, **facts: str) -> str:
    """Unknown tone falls back to `default`; an unknown event is a bug."""
    options = TEMPLATES[event]
    return options.get(tone, options["default"]).format(**facts)
