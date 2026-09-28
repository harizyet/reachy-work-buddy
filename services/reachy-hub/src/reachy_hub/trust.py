"""Deterministic trust computation (Phase 25.0, ADR 0024).

Turns identity evidence into a `TrustLevel`. This module understands only
evidence fields — fresh/stale, accepted/rejected, same owner, same session,
quality, spoof/liveness result, audio/visual association — and nothing about
which model produced them (no SpeechBrain/ECAPA/ArcFace/SFace/MiniFASNet/
Whisper/LLM awareness), so it stays auditable and swappable independently of
model choice (docs/phase-25.md).

Recognition models produce evidence, not authorization: this function only
ever returns a `TrustLevel`, never an allow/deny decision. See
`reachy_hub.request_sensitivity.authorize_request` for the next stage.
"""

from __future__ import annotations

from shared.models.trust import SpeakerEvidence, TrustLevel, VisualEvidence


def effective_trust(
    speaker: SpeakerEvidence | None,
    visual: VisualEvidence | None,
    *,
    authenticated_channel: bool,
    now: float,
) -> TrustLevel:
    """Recompute trust from current evidence; never read from a cache.

    Callers must call this at every point docs/phase-25.md lists (after wake
    admission, at utterance start, after each verification stage, before
    admitting protected input, before tool/data access, before TTS,
    throughout sensitive playback, on sensor-state change, on evidence
    expiry) rather than reuse a previously computed level.
    """
    if authenticated_channel:
        return TrustLevel.T3

    speaker_ok = speaker is not None and speaker.qualifies(now)
    if speaker_ok and visual is not None and visual.qualifies(now):
        same_owner = speaker.owner_id == visual.owner_id
        same_session = speaker.voice_session_id == visual.voice_session_id
        if same_owner and same_session:
            return TrustLevel.T2

    if speaker_ok:
        return TrustLevel.T1

    return TrustLevel.T0
