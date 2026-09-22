"""Deterministic response routing. See docs/adr/0006-response-routing.md.

resolve_delivery_channel takes no response content (no text, no
AgentResponse) — that's the point: Phase 6's exit criterion is that mode
changes routing *without prompt changes*, and the absence of a content
parameter here makes that a structural guarantee, not just a behavioural
one. Phase 9 adds a second function that takes AgentResponse into account
for privacy/urgency-driven overrides; it does not replace this one.
"""

from __future__ import annotations

from shared.models.response import Privacy
from shared.models.session import Channel, InteractionMode


def resolve_delivery_channel(mode: InteractionMode, active_channel: Channel) -> Channel:
    if mode == InteractionMode.DESK:
        return Channel.REACHY
    if mode == InteractionMode.OFFICE:
        return Channel.PHONE
    if mode == InteractionMode.SILENT:
        # Never speak aloud. Stay on whatever text-capable channel is
        # already in use; Reachy has no silent/text-only output path, so
        # fall back to the web client instead.
        return active_channel if active_channel != Channel.REACHY else Channel.WEB
    if mode == InteractionMode.REMOTE:
        return Channel.PHONE
    raise ValueError(f"unhandled interaction mode: {mode!r}")


# Privacy levels that must never be spoken aloud through Reachy's speaker,
# regardless of mode. Desk mode is nominally "private room" (docs/plan.md
# §4), but the routing table is explicit that sensitive/work-private
# content goes to "a private channel only" — a blanket rule, not one
# conditioned on an assumption about the room the robot happens to be in
# that this system has no way to verify.
_NEVER_SPOKEN_ALOUD = frozenset({Privacy.SENSITIVE, Privacy.WORK_PRIVATE})


def apply_privacy_override(base_channel: Channel, privacy: Privacy, active_channel: Channel) -> Channel:
    """Phase 9 (ADR 0006): a second, separate function from
    resolve_delivery_channel, not a modified version of it — that function's
    signature (mode, active_channel only) is itself a structural guarantee
    tested in test_response_policy.py, and privacy-based overrides must not
    erode it. This function is the deterministic policy engine's "final
    authority" clause: it can veto a mode-driven Reachy delivery, but it
    never has the power to introduce Reachy delivery that resolve_delivery_channel
    didn't already choose.
    """
    if base_channel == Channel.REACHY and privacy in _NEVER_SPOKEN_ALOUD:
        return active_channel if active_channel != Channel.REACHY else Channel.WEB
    return base_channel
