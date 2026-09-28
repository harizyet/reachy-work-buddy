"""Owner-recognition enrollment capture portal (Phase 25a.2/25b.3 skeleton,
docs/phase-25.md's "Enrollment portal"). This is deliberately narrow: it
lets the owner record raw voice/face samples for a future benchmark and
enrollment dataset. It does **not** implement speaker/face verification,
templates, calibration, trust, or authorization — those stay exactly where
ADR 0024 puts them, and none of it exists yet. A captured sample here can
never become identity evidence on its own.

Every route requires an owner cookie session (never the REMOTE_UI_TOKEN
bearer used elsewhere for trusted-network automation: enrollment is
sensitive enough to require an actual logged-in owner browser). Mutating
routes additionally require same-origin CSRF and a fresh password
reauthentication, matching docs/phase-25.md's "Require owner login plus
fresh password reauthentication and CSRF protection to enroll, replace or
delete templates" — applied here one step earlier, to raw samples, since
this portal doesn't create templates yet.
"""

from __future__ import annotations

import time

from fastapi import Depends, HTTPException, Request
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
    OWNER_RECOGNITION_FACE_SAMPLE,
    OWNER_RECOGNITION_FACE_SAMPLES,
    OWNER_RECOGNITION_REAUTH,
    OWNER_RECOGNITION_STATUS,
    OWNER_RECOGNITION_VOICE_SAMPLE,
    OWNER_RECOGNITION_VOICE_SAMPLES,
)

REAUTH_WINDOW_SECONDS = 300.0
_SESSION_REAUTH_KEY = "owner_recognition_reauth_at"


class ReauthRequest(BaseModel):
    password: str = Field(min_length=1, max_length=4096, repr=False)


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
        return EnrollmentStatus(
            voice_samples=await store.list_samples(EnrollmentSampleKind.VOICE),
            face_samples=await store.list_samples(EnrollmentSampleKind.FACE),
            reauthenticated=remaining is not None and remaining > 0,
            reauth_expires_in_seconds=max(remaining, 0.0) if remaining is not None else None,
        )

    for kind, samples_path, sample_path in (
        (EnrollmentSampleKind.VOICE, OWNER_RECOGNITION_VOICE_SAMPLES, OWNER_RECOGNITION_VOICE_SAMPLE),
        (EnrollmentSampleKind.FACE, OWNER_RECOGNITION_FACE_SAMPLES, OWNER_RECOGNITION_FACE_SAMPLE),
    ):
        def make_routes(kind=kind, samples_path=samples_path, sample_path=sample_path):
            @app.post(samples_path, dependencies=write_deps)
            async def upload(request: Request) -> EnrollmentSample:
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

        make_routes()
