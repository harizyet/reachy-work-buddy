from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel


class Behaviour(StrEnum):
    """Initial semantic behaviour vocabulary. See docs/adr/0003.

    New behaviours are added here as reachy-embodiment's catalogue grows;
    companion-core must never request a behaviour outside this set.
    """

    LISTENING = "listening"
    THINKING = "thinking"
    SPEAKING = "speaking"
    ACKNOWLEDGEMENT = "acknowledgement"
    UNDERSTOOD = "understood"
    UNCERTAIN = "uncertain"
    GREETING = "greeting"
    GOODBYE = "goodbye"
    WAITING = "waiting"
    TASK_COMPLETE = "task_complete"
    CANNOT_COMPLY = "cannot_comply"
    SENT_TO_PHONE = "sent_to_phone"
    INCOMING_MESSAGE = "incoming_message"
    MEETING_SOON = "meeting_soon"
    IMPORTANT_NOTICE = "important_notice"
    DO_NOT_DISTURB = "do_not_disturb"
    IDLE_BREATHING = "idle_breathing"
    SUBTLE_SCAN = "subtle_scan"
    ANTENNA_TWITCH = "antenna_twitch"
    SLEEP = "sleep"
    WAKE = "wake"


class Priority(StrEnum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"


class EmbodimentCommand(BaseModel):
    """Sent by companion-core (via reachy-hub) to reachy-embodiment's
    POST /behaviour/{name}. See docs/adr/0003-embodiment-command-api.md.
    """

    behaviour_name: Behaviour
    priority: Priority = Priority.NORMAL
    parameters: dict[str, str] = {}
    interruptible: bool = True
    correlation_id: str | None = None


class EmbodimentState(StrEnum):
    """reachy-embodiment's local presence/fallback state machine.
    See docs/adr/0004-offline-fallback.md.
    """

    IDLE = "idle"
    LISTENING = "listening"
    THINKING = "thinking"
    SPEAKING = "speaking"
    REMOTE = "remote"
    SLEEP = "sleep"
    DISCONNECTED = "disconnected"
