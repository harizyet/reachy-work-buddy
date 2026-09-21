"""Behaviour catalogue: reachy-embodiment's semantic vocabulary.

See docs/adr/0003-embodiment-command-api.md. Every value in shared's
Behaviour enum must have a catalogue entry here — companion-core is never
allowed to request a behaviour outside that enum, so there's nothing to
validate beyond "is it a valid enum member," but every member needs a
human-readable description for GET /behaviours.
"""

from __future__ import annotations

from shared.models.embodiment import Behaviour, EmbodimentState

DESCRIPTIONS: dict[Behaviour, str] = {
    Behaviour.LISTENING: "Orient toward the speaker, subtle attentive posture.",
    Behaviour.THINKING: "Look away slightly, processing animation.",
    Behaviour.SPEAKING: "Stable gaze, speech-driven micro-motion.",
    Behaviour.ACKNOWLEDGEMENT: "Brief nod acknowledging input was received.",
    Behaviour.UNDERSTOOD: "Confirming nod/gesture that a request was understood.",
    Behaviour.UNCERTAIN: "Head tilt / hesitation gesture signalling low confidence.",
    Behaviour.GREETING: "Wake-up greeting gesture at conversation start.",
    Behaviour.GOODBYE: "Farewell gesture at conversation end.",
    Behaviour.WAITING: "Idle-attentive posture while waiting on an external result.",
    Behaviour.TASK_COMPLETE: "Positive completion gesture.",
    Behaviour.CANNOT_COMPLY: "Apologetic/declining gesture for a refused request.",
    Behaviour.SENT_TO_PHONE: "Gesture indicating the full response was routed to phone.",
    Behaviour.INCOMING_MESSAGE: "Attention gesture for an incoming message notification.",
    Behaviour.MEETING_SOON: "Reminder gesture ahead of an upcoming meeting.",
    Behaviour.IMPORTANT_NOTICE: "Elevated-attention gesture for an urgent notice.",
    Behaviour.DO_NOT_DISTURB: "Privacy posture — centered, quiet, not soliciting attention.",
    Behaviour.IDLE_BREATHING: "Slow breathing motion, no external input.",
    Behaviour.SUBTLE_SCAN: "Occasional small attention shift while idle.",
    Behaviour.ANTENNA_TWITCH: "Antenna-only idle accent motion.",
    Behaviour.SLEEP: "Transition to sleep posture.",
    Behaviour.WAKE: "Transition from sleep to idle posture.",
}

# Behaviours that represent a standing state (as opposed to a one-off
# gesture) update reachy-embodiment's reported EmbodimentState. Gestures
# like GREETING or ACKNOWLEDGEMENT are transient and leave the standing
# state unchanged — this distinction becomes load-bearing once Phase 3
# builds the real presence loop; for now /state just reflects it.
STATE_FOR_BEHAVIOUR: dict[Behaviour, EmbodimentState] = {
    Behaviour.LISTENING: EmbodimentState.LISTENING,
    Behaviour.THINKING: EmbodimentState.THINKING,
    Behaviour.SPEAKING: EmbodimentState.SPEAKING,
    Behaviour.IDLE_BREATHING: EmbodimentState.IDLE,
    Behaviour.SUBTLE_SCAN: EmbodimentState.IDLE,
    Behaviour.ANTENNA_TWITCH: EmbodimentState.IDLE,
    Behaviour.SLEEP: EmbodimentState.SLEEP,
    Behaviour.WAKE: EmbodimentState.IDLE,
}

assert set(DESCRIPTIONS) == set(Behaviour), "every Behaviour needs a catalogue description"
