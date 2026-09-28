"""Owner-recognition benchmark-capture portal (Phase 25a.2/25b.3 skeleton,
docs/phase-25.md's "Enrollment portal"; Phase 26d's benchmark-vs-
operational data policy,
docs/phase-26.md#26d-addendum-benchmark-vs-operational-data-policy-owner-decision-2026-09-28).

This is deliberately narrow: it lets the owner explicitly enable and then
record raw voice/face samples for a benchmark and calibration dataset. It
does **not** implement speaker/face verification, templates, calibration,
trust, or authorization — those stay exactly where ADR 0024 puts them,
and none of it exists yet. A captured sample here can never become
identity evidence on its own, and this store is never the future
operational enrollment store (Phase 26d requires them kept separate).

Every route requires an owner cookie session (never the REMOTE_UI_TOKEN
bearer used elsewhere for trusted-network automation: this is sensitive
enough to require an actual logged-in owner browser). Mutating routes
additionally require same-origin CSRF and a fresh password
reauthentication. Recording a sample also requires benchmark mode to be
explicitly enabled first (Phase 26d's "explicitly enabled" requirement) —
CSRF and fresh reauth alone are not consent to start a dataset.
"""

from __future__ import annotations

import io
import json
import time
import zipfile

from fastapi import Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from reachy_hub.enrollment_store import (
    MAX_SAMPLE_BYTES,
    EnrollmentStore,
    SampleRejected,
)
from reachy_hub.operator import require_csrf
from shared.models.enrollment import (
    EnrollmentSample,
    EnrollmentSampleKind,
    EnrollmentStatus,
)
from shared.protocols.operator_api import (
    OWNER_RECOGNITION_BENCHMARK_ENABLED,
    OWNER_RECOGNITION_BENCHMARK_FACE_EXPORT,
    OWNER_RECOGNITION_BENCHMARK_FACE_SAMPLE,
    OWNER_RECOGNITION_BENCHMARK_FACE_SAMPLES,
    OWNER_RECOGNITION_BENCHMARK_VOICE_EXPORT,
    OWNER_RECOGNITION_BENCHMARK_VOICE_SAMPLE,
    OWNER_RECOGNITION_BENCHMARK_VOICE_SAMPLES,
    OWNER_RECOGNITION_REAUTH,
    OWNER_RECOGNITION_STATUS,
)

REAUTH_WINDOW_SECONDS = 300.0
_SESSION_REAUTH_KEY = "owner_recognition_reauth_at"


class ReauthRequest(BaseModel):
    password: str = Field(min_length=1, max_length=4096, repr=False)


class BenchmarkEnabledRequest(BaseModel):
    enabled: bool


def _reauth_remaining(request: Request) -> float | None:
    reauth_at = request.session.get(_SESSION_REAUTH_KEY)
    if reauth_at is None:
        return None
    return REAUTH_WINDOW_SECONDS - (time.time() - reauth_at)


def install_owner_recognition_routes(app, require_owner_session, store: EnrollmentStore) -> None:
    def require_fresh_reauth(request: Request) -> None:
        remaining = _reauth_remaining(request)
        if remaining is None or remaining <= 0:
            raise HTTPException(401, "Fresh reauthentication required")

    read_deps = [Depends(require_owner_session)]
    write_deps = [Depends(require_owner_session), Depends(require_csrf), Depends(require_fresh_reauth)]
    export_deps = [Depends(require_owner_session), Depends(require_fresh_reauth)]

    @app.post(OWNER_RECOGNITION_REAUTH, dependencies=[Depends(require_owner_session), Depends(require_csrf)])
    async def reauth(body: ReauthRequest, request: Request) -> dict:
        owner = request.session.get("user")
        if not owner or not await app.state.user_store.authenticate(owner, body.password):
            raise HTTPException(401, "Invalid password")
        request.session[_SESSION_REAUTH_KEY] = time.time()
        return {"reauthenticated": True, "expires_in_seconds": REAUTH_WINDOW_SECONDS}

    @app.get(OWNER_RECOGNITION_STATUS, dependencies=read_deps)
    async def status(request: Request) -> EnrollmentStatus:
        remaining = _reauth_remaining(request)
        voice_samples = await store.list_samples(EnrollmentSampleKind.VOICE)
        face_samples = await store.list_samples(EnrollmentSampleKind.FACE)
        return EnrollmentStatus(
            benchmark_enabled=await store.is_benchmark_enabled(),
            voice_samples=voice_samples,
            face_samples=face_samples,
            voice_total_bytes=sum(sample.size_bytes for sample in voice_samples),
            face_total_bytes=sum(sample.size_bytes for sample in face_samples),
            reauthenticated=remaining is not None and remaining > 0,
            reauth_expires_in_seconds=max(remaining, 0.0) if remaining is not None else None,
        )

    @app.put(OWNER_RECOGNITION_BENCHMARK_ENABLED, dependencies=write_deps)
    async def set_benchmark_enabled(body: BenchmarkEnabledRequest) -> dict:
        # Turning it off never deletes anything already collected (Phase
        # 26d: mode separation, not a hidden delete); the owner deletes
        # explicitly via the existing per-sample/delete-all routes.
        await store.set_benchmark_enabled(body.enabled)
        return {"benchmark_enabled": body.enabled}

    for kind, samples_path, sample_path, export_path in (
        (
            EnrollmentSampleKind.VOICE,
            OWNER_RECOGNITION_BENCHMARK_VOICE_SAMPLES,
            OWNER_RECOGNITION_BENCHMARK_VOICE_SAMPLE,
            OWNER_RECOGNITION_BENCHMARK_VOICE_EXPORT,
        ),
        (
            EnrollmentSampleKind.FACE,
            OWNER_RECOGNITION_BENCHMARK_FACE_SAMPLES,
            OWNER_RECOGNITION_BENCHMARK_FACE_SAMPLE,
            OWNER_RECOGNITION_BENCHMARK_FACE_EXPORT,
        ),
    ):
        def make_routes(kind=kind, samples_path=samples_path, sample_path=sample_path, export_path=export_path):
            @app.post(samples_path, dependencies=write_deps)
            async def upload(request: Request) -> EnrollmentSample:
                if not await store.is_benchmark_enabled():
                    raise HTTPException(403, "Benchmark dataset collection is not enabled")
                content_length = request.headers.get("content-length")
                if content_length is not None and int(content_length) > MAX_SAMPLE_BYTES:
                    raise HTTPException(413, "Sample too large")
                data = await request.body()
                try:
                    return await store.add_sample(kind, request.headers.get("content-type", ""), data)
                except SampleRejected as exc:
                    raise HTTPException(422, str(exc)) from None

            @app.delete(samples_path, dependencies=write_deps)
            async def delete_all() -> dict:
                return {"deleted": await store.delete_all(kind)}

            @app.delete(sample_path, dependencies=write_deps)
            async def delete_one(sample_id: str) -> dict:
                if not await store.delete_sample(kind, sample_id):
                    raise HTTPException(404, "Sample not found")
                return {"ok": True}

            @app.get(export_path, dependencies=export_deps)
            async def export() -> StreamingResponse:
                samples = await store.list_samples(kind)
                buffer = io.BytesIO()
                with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
                    manifest = [sample.model_dump(mode="json") for sample in samples]
                    archive.writestr("manifest.json", json.dumps(manifest, indent=2))
                    for sample in samples:
                        data = await store.read_sample(kind, sample.sample_id)
                        if data is None:
                            continue
                        extension = sample.content_type.split("/")[-1]
                        archive.writestr(f"{sample.sample_id}.{extension}", data)
                buffer.seek(0)
                return StreamingResponse(
                    buffer,
                    media_type="application/zip",
                    headers={"Content-Disposition": f'attachment; filename="{kind.value}-benchmark-dataset.zip"'},
                )

        make_routes()
