"""Phase 25.0 trust engine (docs/phase-25.md, ADR 0024): deterministic,
tested without real-time sleeps."""

from reachy_hub.trust import effective_trust

from shared.models.trust import SpeakerEvidence, TrustLevel, VisualEvidence

OWNER = "owner-1"
ROBOT = "robot-1"
SESSION = "voice-session-1"


def _speaker(
    *,
    now: float,
    ttl: float = 10.0,
    owner_id: str = OWNER,
    voice_session_id: str = SESSION,
    accepted: bool = True,
    quality_ok: bool = True,
    spoof_check: str = "pass",
    captured: float | None = None,
) -> SpeakerEvidence:
    captured = now if captured is None else captured
    return SpeakerEvidence(
        owner_id=owner_id,
        robot_id=ROBOT,
        voice_session_id=voice_session_id,
        turn=1,
        captured_monotonic=captured,
        expires_monotonic=captured + ttl,
        model_version="ecapa-1",
        calibration_version="cal-1",
        similarity_score=0.9,
        calibrated_confidence=0.95,
        quality_ok=quality_ok,
        spoof_check=spoof_check,
        accepted=accepted,
    )


def _visual(
    *,
    now: float,
    ttl: float = 1.0,
    owner_id: str = OWNER,
    voice_session_id: str = SESSION,
    accepted: bool = True,
    quality_ok: bool = True,
    liveness_ok: bool = True,
    frozen_frame: bool = False,
    doa_consistent: bool | None = True,
    captured: float | None = None,
) -> VisualEvidence:
    captured = now if captured is None else captured
    return VisualEvidence(
        owner_id=owner_id,
        robot_id=ROBOT,
        voice_session_id=voice_session_id,
        captured_monotonic=captured,
        expires_monotonic=captured + ttl,
        frame_sequence=1,
        model_version="sface-1",
        calibration_version="cal-1",
        calibrated_confidence=0.9,
        quality_ok=quality_ok,
        liveness_ok=liveness_ok,
        frozen_frame=frozen_frame,
        doa_consistent=doa_consistent,
        accepted=accepted,
    )


def test_no_evidence_is_t0() -> None:
    assert effective_trust(None, None, authenticated_channel=False, now=100.0) == TrustLevel.T0


def test_fresh_accepted_voice_alone_is_t1() -> None:
    speaker = _speaker(now=100.0)
    assert effective_trust(speaker, None, authenticated_channel=False, now=100.5) == TrustLevel.T1


def test_voice_expiry_boundary() -> None:
    speaker = _speaker(now=0.0, ttl=10.0)
    just_before = effective_trust(speaker, None, authenticated_channel=False, now=9.999)
    at_expiry = effective_trust(speaker, None, authenticated_channel=False, now=10.0)
    assert (just_before, at_expiry) == (TrustLevel.T1, TrustLevel.T0)


def test_rejected_speaker_evidence_is_t0() -> None:
    speaker = _speaker(now=0.0, accepted=False)
    assert effective_trust(speaker, None, authenticated_channel=False, now=0.0) == TrustLevel.T0


def test_poor_quality_or_failed_spoof_check_blocks_t1_even_if_accepted() -> None:
    bad_quality = _speaker(now=0.0, quality_ok=False)
    failed_spoof = _speaker(now=0.0, spoof_check="fail")
    assert effective_trust(bad_quality, None, authenticated_channel=False, now=0.0) == TrustLevel.T0
    assert effective_trust(failed_spoof, None, authenticated_channel=False, now=0.0) == TrustLevel.T0


def test_fresh_voice_and_visual_same_owner_and_session_is_t2() -> None:
    speaker = _speaker(now=0.0)
    visual = _visual(now=0.0)
    assert effective_trust(speaker, visual, authenticated_channel=False, now=0.5) == TrustLevel.T2


def test_visual_ttl_boundary_downgrades_t2_to_t1() -> None:
    speaker = _speaker(now=0.0, ttl=10.0)
    visual = _visual(now=0.0, ttl=1.0)
    just_before = effective_trust(speaker, visual, authenticated_channel=False, now=0.999)
    at_expiry = effective_trust(speaker, visual, authenticated_channel=False, now=1.0)
    assert (just_before, at_expiry) == (TrustLevel.T2, TrustLevel.T1)


def test_stale_voice_and_stale_visual_is_t0() -> None:
    speaker = _speaker(now=0.0, ttl=10.0)
    visual = _visual(now=0.0, ttl=1.0)
    assert effective_trust(speaker, visual, authenticated_channel=False, now=11.0) == TrustLevel.T0


def test_spoof_or_liveness_failure_blocks_t2() -> None:
    speaker = _speaker(now=0.0)
    failed_liveness = _visual(now=0.0, liveness_ok=False)
    rejected_visual = _visual(now=0.0, accepted=False)
    assert effective_trust(speaker, failed_liveness, authenticated_channel=False, now=0.0) == TrustLevel.T1
    assert effective_trust(speaker, rejected_visual, authenticated_channel=False, now=0.0) == TrustLevel.T1


def test_frozen_frame_cannot_grant_t2() -> None:
    speaker = _speaker(now=0.0)
    visual = _visual(now=0.0, frozen_frame=True)
    assert effective_trust(speaker, visual, authenticated_channel=False, now=0.0) == TrustLevel.T1


def test_doa_disagreement_blocks_t2_but_none_does_not() -> None:
    speaker = _speaker(now=0.0)
    disagreeing = _visual(now=0.0, doa_consistent=False)
    unknown_doa = _visual(now=0.0, doa_consistent=None)
    assert effective_trust(speaker, disagreeing, authenticated_channel=False, now=0.0) == TrustLevel.T1
    assert effective_trust(speaker, unknown_doa, authenticated_channel=False, now=0.0) == TrustLevel.T2


def test_session_mismatch_between_speaker_and_visual_blocks_t2() -> None:
    speaker = _speaker(now=0.0, voice_session_id="session-a")
    visual = _visual(now=0.0, voice_session_id="session-b")
    assert effective_trust(speaker, visual, authenticated_channel=False, now=0.0) == TrustLevel.T1


def test_wrong_owner_between_speaker_and_visual_blocks_t2() -> None:
    speaker = _speaker(now=0.0, owner_id="owner-1")
    visual = _visual(now=0.0, owner_id="owner-2")
    assert effective_trust(speaker, visual, authenticated_channel=False, now=0.0) == TrustLevel.T1


def test_owner_face_visible_with_visual_only_evidence_is_t0() -> None:
    # A visible owner face never authorizes anyone by itself: without fresh,
    # accepted speaker evidence there is no T1, so T2's speaker leg is also
    # absent regardless of how good the visual evidence is.
    visual = _visual(now=0.0)
    assert effective_trust(None, visual, authenticated_channel=False, now=0.0) == TrustLevel.T0


def test_authenticated_channel_is_t3_regardless_of_biometric_evidence() -> None:
    assert effective_trust(None, None, authenticated_channel=True, now=0.0) == TrustLevel.T3
    speaker = _speaker(now=0.0, accepted=False)
    assert effective_trust(speaker, None, authenticated_channel=True, now=0.0) == TrustLevel.T3


def test_model_or_calibration_mismatch_is_not_itself_disqualifying_here() -> None:
    # The trust engine only understands evidence fields, not model identity
    # (docs/phase-25.md); version auditing/rejection of an unexpected
    # model/calibration combination is the verifier's job before it ever
    # produces `accepted=True` evidence, not the trust engine's.
    speaker = _speaker(now=0.0)
    speaker.model_version = "unexpected-model"
    assert effective_trust(speaker, None, authenticated_channel=False, now=0.0) == TrustLevel.T1
