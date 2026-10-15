"""Shared voice identity: enrollment, 1:1 owner verification and the routes for them (Phase 32A.V,
ADR 0041). The embedding model runs in the stateless `speaker` sidecar; this module owns everything
that is a decision: profiles, consent, thresholds, quality rules, evidence and its lifetime.

What it is not: authorization. A verification result is identity evidence for one utterance, handed
back to the session that sent the audio (ADR 0024). Nothing in this module calls Companion Core with
it, changes a privacy ceiling, or ends a login. A missing, uncertain or failed result leaves the owner
exactly as signed in as before.

Biometric handling: enrollment drafts hold embeddings in process memory only, with a lifetime limit,
and vanish on restart; the stored profile is ciphertext (voice_profiles.py); audio is never written;
no log line or response contains a vector or a raw similarity score.
"""

from __future__ import annotations

import asyncio
import logging
import math
import os
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

import httpx
from fastapi import Depends, HTTPException, Query, Request
from pydantic import BaseModel

from reachy_hub.keyring import Keyring, KeyringUnavailable
from reachy_hub.operator import require_csrf
from reachy_hub.voice_profiles import (
    StoredProfile,
    VoiceProfileStore,
    load_template,
    seal,
)
from shared.models.voice_identity import (
    MAX_AUDIO_BYTES,
    ClientKind,
    ClientProvenance,
    EnrollmentDraftView,
    EnrollmentSampleView,
    ProfileInfo,
    VoiceEvidence,
    VoiceIdentityStatus,
    VoiceState,
    VoiceStateView,
)
from shared.protocols.voice_identity_api import (
    CLIENT_ID_HEADER,
    CLIENT_KIND_HEADER,
    DEVICE_ID_HEADER,
    UTTERANCE_ID_HEADER,
    VOICE_IDENTITY_ENROLL_COMMIT,
    VOICE_IDENTITY_ENROLL_DRAFT,
    VOICE_IDENTITY_ENROLL_SAMPLE,
    VOICE_IDENTITY_ENROLL_SAMPLES,
    VOICE_IDENTITY_PROFILE,
    VOICE_IDENTITY_STATUS,
    VOICE_IDENTITY_TURN,
    VOICE_IDENTITY_VERIFY,
)

log = logging.getLogger(__name__)

# Uncalibrated engineering defaults for quality gating. They decide whether a clip is usable, not whose
# voice it is, and the GV benchmark may change them.
MIN_ENROLL_SPEECH_S = 1.5
MIN_VERIFY_SPEECH_S = 0.8
MIN_RMS_DBFS = -45.0
MAX_CLIPPING = 0.02
MAX_DRAFT_SAMPLES = 12
DRAFT_TTL_SECONDS = 900.0


@dataclass(frozen=True)
class Embedding:
    vector: list[float]
    model_version: str
    duration_s: float
    speech_s: float
    rms_dbfs: float
    clipping_fraction: float


class EmbeddingUnavailable(Exception):
    """The embedding service cannot answer (down, busy, misconfigured). Never a verdict about the speaker."""


class EmbeddingRejected(Exception):
    """The service refused this audio (wrong format, too short)."""


class SidecarEmbeddingClient:
    def __init__(self, base_url: str, token: str | None = None, *, client: httpx.AsyncClient | None = None, timeout: float = 10.0) -> None:
        self._url = base_url.rstrip("/") + "/embed"
        self._headers = {"X-Reachy-Speech-Token": token} if token else {}
        self._client = client or httpx.AsyncClient(timeout=timeout)

    async def embed(self, wav: bytes) -> Embedding:
        try:
            response = await self._client.post(self._url, files={"file": ("audio.wav", wav, "audio/wav")}, headers=self._headers)
        except httpx.HTTPError:
            raise EmbeddingUnavailable() from None
        if response.status_code == 422:
            raise EmbeddingRejected()
        if response.status_code != 200:
            raise EmbeddingUnavailable()
        try:
            body = response.json()
            return Embedding([float(x) for x in body["embedding"]], str(body["model_version"]), float(body["duration_s"]),
                             float(body["speech_s"]), float(body["rms_dbfs"]), float(body["clipping_fraction"]))
        except (ValueError, KeyError, TypeError):
            raise EmbeddingUnavailable() from None

    async def healthy(self) -> bool:
        try:
            return (await self._client.get(self._url.removesuffix("/embed") + "/health")).status_code == 200
        except httpx.HTTPError:
            return False


def normalize(vector: list[float]) -> list[float]:
    norm = math.sqrt(sum(x * x for x in vector))
    if norm == 0:
        raise ValueError("zero vector")
    return [x / norm for x in vector]


def cosine(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(normalize(a), normalize(b), strict=True))


def centroid(vectors: list[list[float]]) -> list[float]:
    """Mean of the unit vectors, renormalised: the one template shape used by live verification and, later, meeting matching."""
    units = [normalize(v) for v in vectors]
    return normalize([sum(column) / len(units) for column in zip(*units, strict=True)])


def assess(embedding: Embedding, min_speech_s: float) -> list[str]:
    reasons = []
    if embedding.speech_s < min_speech_s:
        reasons.append("too_little_speech")
    if embedding.rms_dbfs < MIN_RMS_DBFS:
        reasons.append("too_quiet")
    if embedding.clipping_fraction > MAX_CLIPPING:
        reasons.append("clipped")
    return reasons


@dataclass(frozen=True)
class VoiceIdentityConfig:
    enabled: bool = False
    # Unset until the owner approves a calibration (gate GV): without both, no result is ever "verified".
    accept_threshold: float | None = None
    uncertain_threshold: float | None = None
    calibration_version: str = "uncalibrated"
    ttl_seconds: float = 10.0
    required_samples: int = 5
    enroll_consistency: float = 0.35  # each sample vs the mean of the others; catches two voices in one session

    @property
    def calibrated(self) -> bool:
        return (self.accept_threshold is not None and self.uncertain_threshold is not None
                and self.uncertain_threshold <= self.accept_threshold)

    @classmethod
    def from_env(cls) -> VoiceIdentityConfig:
        def number(name: str) -> float | None:
            raw = os.environ.get(name, "").strip()
            return float(raw) if raw else None

        accept, uncertain = number("VOICE_IDENTITY_ACCEPT_THRESHOLD"), number("VOICE_IDENTITY_UNCERTAIN_THRESHOLD")
        return cls(
            enabled=os.environ.get("VOICE_IDENTITY_ENABLED", "false").lower() == "true",
            accept_threshold=accept, uncertain_threshold=uncertain,
            calibration_version=os.environ.get("VOICE_IDENTITY_CALIBRATION_VERSION", "owner-approved" if accept is not None else "uncalibrated"),
        )


class EvidenceLedger:
    """The latest evidence per (owner, client), process-local and short-lived, like the robot's `VoiceSession.trust`.
    A consumer asks for the evidence of one utterance in one session; anything older, replaced or for another
    utterance is simply not there (A16)."""

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._latest: dict[tuple[str, str], VoiceEvidence] = {}

    def put(self, evidence: VoiceEvidence) -> None:
        self._latest[(evidence.owner_id, evidence.client.client_id)] = evidence

    def current(self, owner_id: str, client_id: str, utterance_id: str, session_id: str | None = None) -> VoiceEvidence | None:
        found = self._latest.get((owner_id, client_id))
        if found is None or not found.fresh(self._clock()) or found.utterance_id != utterance_id:
            return None
        if session_id is not None and found.session_id is not None and found.session_id != session_id:
            return None
        return found

    def invalidate(self, owner_id: str) -> None:
        for key in [k for k in self._latest if k[0] == owner_id]:
            del self._latest[key]


class EnrollmentError(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass
class _DraftSample:
    sample_id: str
    quality_reasons: list[str]
    speech_s: float
    vector: list[float] | None  # usable samples only; process memory only
    model_version: str


@dataclass
class _Draft:
    created: float
    samples: list[_DraftSample] = field(default_factory=list)


class VoiceIdentityService:
    def __init__(self, config: VoiceIdentityConfig, embedder, *, store: VoiceProfileStore | None = None,
                 keyring: Keyring | None = None, clock: Callable[[], float] = time.monotonic) -> None:
        self.config, self.embedder, self.store, self.keyring, self._clock = config, embedder, store, keyring, clock
        self.ledger = EvidenceLedger(clock)
        self._drafts: dict[str, _Draft] = {}

    # --- enrollment -------------------------------------------------------------------------------------

    def _draft(self, owner_id: str, create: bool = False) -> _Draft | None:
        draft = self._drafts.get(owner_id)
        if draft is not None and self._clock() - draft.created > DRAFT_TTL_SECONDS:
            self._drafts.pop(owner_id, None)
            draft = None
        if draft is None and create:
            draft = self._drafts[owner_id] = _Draft(created=self._clock())
        return draft

    def draft_view(self, owner_id: str) -> EnrollmentDraftView | None:
        draft = self._draft(owner_id)
        if draft is None:
            return None
        return EnrollmentDraftView(
            samples=[EnrollmentSampleView(sample_id=s.sample_id, quality_ok=s.vector is not None, reasons=s.quality_reasons, speech_seconds=s.speech_s)
                     for s in draft.samples],
            usable_samples=sum(s.vector is not None for s in draft.samples), required_samples=self.config.required_samples,
            expires_in_seconds=max(DRAFT_TTL_SECONDS - (self._clock() - draft.created), 0.0),
        )

    async def add_sample(self, owner_id: str, wav: bytes) -> EnrollmentSampleView:
        embedding = await self.embedder.embed(wav)  # EmbeddingUnavailable / EmbeddingRejected go to the route
        draft = self._draft(owner_id, create=True)
        if len(draft.samples) >= MAX_DRAFT_SAMPLES:
            raise EnrollmentError("draft_full")
        reasons = assess(embedding, MIN_ENROLL_SPEECH_S)
        sample = _DraftSample(uuid.uuid4().hex, reasons, embedding.speech_s, None if reasons else embedding.vector, embedding.model_version)
        draft.samples.append(sample)
        return EnrollmentSampleView(sample_id=sample.sample_id, quality_ok=not reasons, reasons=reasons, speech_seconds=sample.speech_s)

    def remove_sample(self, owner_id: str, sample_id: str) -> bool:
        draft = self._draft(owner_id)
        if draft is None:
            return False
        before = len(draft.samples)
        draft.samples = [s for s in draft.samples if s.sample_id != sample_id]
        return len(draft.samples) < before

    def discard_draft(self, owner_id: str) -> None:
        self._drafts.pop(owner_id, None)

    async def commit(self, owner_id: str, client: ClientProvenance, *, consent: bool) -> ProfileInfo:
        if self.store is None or self.keyring is None:
            raise EnrollmentError("storage_unavailable")
        if not consent:
            raise EnrollmentError("consent_required")
        draft = self._draft(owner_id)
        usable = [s for s in (draft.samples if draft else []) if s.vector is not None]
        if len(usable) < self.config.required_samples:
            raise EnrollmentError("not_enough_samples")
        if len({s.model_version for s in usable}) != 1:
            raise EnrollmentError("mixed_model_versions")
        for i, sample in enumerate(usable):
            others = centroid([s.vector for j, s in enumerate(usable) if j != i])
            if cosine(sample.vector, others) < self.config.enroll_consistency:
                raise EnrollmentError("inconsistent_samples")
        sealed = seal(self.keyring, owner_id=owner_id, model_version=usable[0].model_version,
                      template=centroid([s.vector for s in usable]), sample_count=len(usable),
                      enrolled_by=client, consented_at=datetime.now(UTC))
        stored = await self.store.put(sealed)
        self.discard_draft(owner_id)
        self.ledger.invalidate(owner_id)  # evidence from an earlier template means nothing now
        log.info("voice profile stored: version=%s samples=%s client_kind=%s", stored.version, stored.sample_count, client.client_kind.value)
        return stored.info()

    async def delete_profile(self, owner_id: str) -> bool:
        self.discard_draft(owner_id)
        self.ledger.invalidate(owner_id)
        deleted = await self.store.delete(owner_id) if self.store else False
        if deleted:
            log.info("voice profile deleted")
        return deleted

    # --- verification -----------------------------------------------------------------------------------

    def _evidence(self, state: VoiceState, owner_id: str, client: ClientProvenance, utterance_id: str, session_id: str | None,
                  turn: int | None, *, reasons: list[str], model_version: str = "", profile: StoredProfile | None = None,
                  score: float | None = None, quality_ok: bool = False) -> VoiceEvidence:
        now, wall = self._clock(), datetime.now(UTC)
        evidence = VoiceEvidence(
            evidence_id=uuid.uuid4().hex, utterance_id=utterance_id, owner_id=owner_id, client=client, session_id=session_id, turn=turn,
            issued_monotonic=now, expires_monotonic=now + self.config.ttl_seconds,
            issued_at=wall, expires_at=wall + timedelta(seconds=self.config.ttl_seconds),
            model_version=model_version or (profile.model_version if profile else ""), calibration_version=self.config.calibration_version,
            profile_id=profile.profile_id if profile else None, profile_version=profile.version if profile else None,
            similarity_score=score, quality_ok=quality_ok, quality_reasons=reasons, spoof_check="unavailable", state=state,
        )
        self.ledger.put(evidence)
        return evidence

    async def verify(self, owner_id: str, wav: bytes, client: ClientProvenance, *, utterance_id: str, session_id: str | None = None,
                     turn: int | None = None) -> VoiceEvidence:
        """Never raises: every failure is a state, because a broken verifier must not break the conversation (docs/phase-25.md)."""
        def unavailable(reason: str, **kw) -> VoiceEvidence:
            return self._evidence(VoiceState.UNAVAILABLE, owner_id, client, utterance_id, session_id, turn, reasons=[reason], **kw)

        try:
            if self.store is None or self.keyring is None:
                return unavailable("storage_unavailable")
            profile = await self.store.get(owner_id)
            if profile is None:
                return unavailable("no_profile")
            try:
                template = load_template(self.keyring, profile)
            except KeyringUnavailable:
                return unavailable("profile_unreadable", profile=profile)
            try:
                embedding = await self.embedder.embed(wav)
            except EmbeddingRejected:
                return unavailable("audio_rejected", profile=profile)
            except EmbeddingUnavailable:
                return unavailable("service_unavailable", profile=profile)
            if embedding.model_version != profile.model_version:
                return unavailable("model_changed_reenroll", profile=profile, model_version=embedding.model_version)
            reasons = assess(embedding, MIN_VERIFY_SPEECH_S)
            score = cosine(embedding.vector, template)
            if reasons:
                return self._evidence(VoiceState.UNCERTAIN, owner_id, client, utterance_id, session_id, turn, reasons=reasons, profile=profile, score=score)
            if not self.config.calibrated:
                return self._evidence(VoiceState.UNAVAILABLE, owner_id, client, utterance_id, session_id, turn, reasons=["not_calibrated"],
                                      profile=profile, score=score, quality_ok=True)
            state = (VoiceState.VERIFIED if score >= self.config.accept_threshold
                     else VoiceState.UNCERTAIN if score >= self.config.uncertain_threshold else VoiceState.NOT_VERIFIED)
            return self._evidence(state, owner_id, client, utterance_id, session_id, turn, reasons=[], profile=profile, score=score, quality_ok=True)
        except Exception:  # noqa: BLE001 - the verifier contract: a failure is a state, never a broken turn
            log.warning("voice verification failed", exc_info=False)
            return unavailable("internal_error")

    def view(self, evidence: VoiceEvidence) -> VoiceStateView:
        return VoiceStateView(
            state=evidence.state, utterance_id=evidence.utterance_id, issued_at=evidence.issued_at, expires_at=evidence.expires_at,
            expires_in_seconds=max(evidence.expires_monotonic - self._clock(), 0.0), reasons=evidence.quality_reasons,
        )

    async def status(self, owner_id: str, *, reauthenticated: bool) -> VoiceIdentityStatus:
        if not self.config.enabled:
            return VoiceIdentityStatus(enabled=False, ready=False, calibration_version=self.config.calibration_version, calibrated=False)
        profile = await self.store.get(owner_id) if self.store else None
        return VoiceIdentityStatus(
            enabled=True, ready=await self.embedder.healthy(), profile=profile.info() if profile else None,
            draft=self.draft_view(owner_id), reauthenticated=reauthenticated, model_version=profile.model_version if profile else None,
            calibration_version=self.config.calibration_version, calibrated=self.config.calibrated,
        )


# --- routes ---------------------------------------------------------------------------------------------

class CommitRequest(BaseModel):
    consent: bool


def provenance(request: Request) -> ClientProvenance:
    try:
        return ClientProvenance(
            client_kind=ClientKind(request.headers.get(CLIENT_KIND_HEADER, "")), client_id=request.headers.get(CLIENT_ID_HEADER, ""),
            device_id=request.headers.get(DEVICE_ID_HEADER) or None,
        )
    except ValueError:
        raise HTTPException(422, "Client provenance headers are required") from None


async def read_audio(request: Request) -> bytes:
    declared = request.headers.get("content-length")
    if declared is not None and declared.isdigit() and int(declared) > MAX_AUDIO_BYTES:
        raise HTTPException(413, "Audio too large")
    data = bytearray()
    async for chunk in request.stream():
        data += chunk
        if len(data) > MAX_AUDIO_BYTES:
            raise HTTPException(413, "Audio too large")
    if len(data) < 44 or data[:4] != b"RIFF" or data[8:12] != b"WAVE":
        raise HTTPException(422, "Audio must be a WAV file")
    return bytes(data)


def install_voice_identity_routes(
    app, require_owner_session, service: VoiceIdentityService, *, owner_user_id: str, reauth_remaining: Callable[[Request], float | None],
    transcribe: Callable[[bytes], Awaitable[str]], converse: Callable[[str, str], Awaitable[BaseModel]],
) -> None:
    """Owner cookie session only: no REMOTE_UI_TOKEN bearer path, like every biometric route (ADR 0024)."""

    def require_enabled() -> None:
        if not service.config.enabled:
            raise HTTPException(404, "Voice identity is not enabled")

    def require_fresh_reauth(request: Request) -> None:
        remaining = reauth_remaining(request)
        if remaining is None or remaining <= 0:
            raise HTTPException(401, "Fresh reauthentication required")

    read_deps = [Depends(require_owner_session)]
    write_deps = [Depends(require_owner_session), Depends(require_csrf), Depends(require_enabled)]
    sensitive_deps = [*write_deps, Depends(require_fresh_reauth)]

    def unavailable(exc: Exception) -> HTTPException:
        if isinstance(exc, EmbeddingRejected):
            return HTTPException(422, "The audio could not be used")
        return HTTPException(503, "Voice identity service unavailable")

    @app.get(VOICE_IDENTITY_STATUS, dependencies=read_deps)
    async def status(request: Request) -> VoiceIdentityStatus:
        remaining = reauth_remaining(request)
        return await service.status(owner_user_id, reauthenticated=remaining is not None and remaining > 0)

    @app.post(VOICE_IDENTITY_ENROLL_SAMPLES, dependencies=write_deps)
    async def add_sample(request: Request) -> EnrollmentSampleView:
        provenance(request)  # required on every call, even though only commit records it
        wav = await read_audio(request)
        try:
            return await service.add_sample(owner_user_id, wav)
        except (EmbeddingUnavailable, EmbeddingRejected) as exc:
            raise unavailable(exc) from None
        except EnrollmentError as exc:
            raise HTTPException(409, exc.reason) from None

    @app.delete(VOICE_IDENTITY_ENROLL_SAMPLE, dependencies=write_deps)
    async def remove_sample(sample_id: str) -> dict:
        if not service.remove_sample(owner_user_id, sample_id):
            raise HTTPException(404, "Sample not found")
        return {"deleted": True}

    @app.delete(VOICE_IDENTITY_ENROLL_DRAFT, dependencies=write_deps)
    async def discard_draft() -> dict:
        service.discard_draft(owner_user_id)
        return {"deleted": True}

    @app.post(VOICE_IDENTITY_ENROLL_COMMIT, dependencies=sensitive_deps)
    async def commit(body: CommitRequest, request: Request) -> ProfileInfo:
        try:
            return await service.commit(owner_user_id, provenance(request), consent=body.consent)
        except EnrollmentError as exc:
            raise HTTPException(409 if exc.reason != "storage_unavailable" else 503, exc.reason) from None

    @app.delete(VOICE_IDENTITY_PROFILE, dependencies=sensitive_deps)
    async def delete_profile() -> dict:
        return {"deleted": await service.delete_profile(owner_user_id)}

    @app.post(VOICE_IDENTITY_VERIFY, dependencies=write_deps)
    async def verify(request: Request) -> VoiceStateView:
        client, wav = provenance(request), await read_audio(request)
        evidence = await service.verify(owner_user_id, wav, client, utterance_id=request.headers.get(UTTERANCE_ID_HEADER) or uuid.uuid4().hex)
        return service.view(evidence)

    @app.post(VOICE_IDENTITY_TURN, dependencies=write_deps)
    async def voice_turn(request: Request, converse_now: bool = Query(default=True, alias="converse")) -> dict:
        """One captured utterance, one upload: Reachy's own STT and the verifier read the same bytes concurrently, then the
        ordinary conversation runs as a spoken (never typed) message. The conversation does not wait for, depend on or receive
        the voice result. With `converse=false` the hub stops after transcription and the result: the Android app then sends the
        text through the unchanged `/messages` path, so the phone-side "begin meeting recording" command still never reaches the hub."""
        client, wav = provenance(request), await read_audio(request)
        utterance_id = request.headers.get(UTTERANCE_ID_HEADER) or uuid.uuid4().hex
        transcript, evidence = await asyncio.gather(
            transcribe(wav), service.verify(owner_user_id, wav, client, utterance_id=utterance_id),
        )
        transcript = transcript.strip()
        if not transcript:
            raise HTTPException(422, "no speech detected in audio")
        message = await converse(owner_user_id, transcript) if converse_now else None
        return {"transcript": transcript, "message": message.model_dump(mode="json") if message else None,
                "voice": service.view(evidence).model_dump(mode="json")}
