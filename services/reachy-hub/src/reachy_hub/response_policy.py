"""Deterministic response routing. See docs/adr/0006-response-routing.md.

resolve_delivery_channel takes no response content (no text, no
AgentResponse) — that's the point: Phase 6's exit criterion is that mode
changes routing *without prompt changes*, and the absence of a content
parameter here makes that a structural guarantee, not just a behavioural
one. Phase 9 adds a second function that takes AgentResponse into account
for privacy/urgency-driven overrides; it does not replace this one.
"""

from __future__ import annotations

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
