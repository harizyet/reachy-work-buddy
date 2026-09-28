"""SpeakerVerifier protocol (Phase 25a.3, docs/phase-25.md's
"Integration into RobotVoiceManager"). Recognition models produce
evidence, not authorization — see ADR 0024. This module defines only the
adapter boundary and a safe unconfigured default; no real model is wired
into production yet (SpeechBrain/torch deliberately stay out of the hub
image until a model is actually selected — see docs/phase-25.md's
"Recommended dependency rollout" and
docs/verification/phase-25a1-voice-benchmark-2026-09-28.md for the
isolated benchmark evaluation so far).
"""

from __future__ import annotations

from typing import Protocol

from shared.models.trust import SpeakerEvidence


class SpeakerVerifier(Protocol):
    async def verify(
        self,
        wav_bytes: bytes,
        *,
        owner_id: str,
        robot_id: str,
        voice_session_id: str,
        turn: int,
    ) -> SpeakerEvidence | None:
        """Score `wav_bytes` against the enrolled owner and return fresh
        evidence, or `None` if verification could not run (no enrolled
        profile, model/service unavailable, audio unusable). Must never
        raise: a broken verifier degrades trust to T0 for that utterance
        (docs/phase-25.md's "Sensor/service failure and reboot" — a
        speaker-verifier outage caps trust at T0, it does not fail the
        turn), it must not break the conversation. Callers (`run_turn` in
        `reachy_hub/robot_voice.py`) still treat an unexpected exception
        defensively, but a correct adapter should never raise."""
        ...


class NoSpeakerVerifier:
    """The default until a real adapter is selected and integrated: never
    produces evidence, so `effective_trust` always resolves to T0 for
    voice — the same "capped, not blocked" degradation documented for a
    real verifier outage, just permanent until 25a.3's model integration
    lands."""

    async def verify(
        self,
        wav_bytes: bytes,
        *,
        owner_id: str,
        robot_id: str,
        voice_session_id: str,
        turn: int,
    ) -> SpeakerEvidence | None:
        return None
