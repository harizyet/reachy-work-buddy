"""Owner-recognition raw enrollment capture (Phase 25a.2/25b.3 portal
skeleton; docs/phase-25.md's "Enrollment portal" section).

These are consented, raw voice/face samples collected through the owner
portal to build a benchmark/enrollment dataset. They are **not** biometric
templates: no speaker or face verification model reads them yet (Phase
25a.1's benchmark uses its own separate, unrelated public example clips —
see docs/verification/phase-25a1-voice-benchmark-2026-09-28.md). Turning
captured samples into an activated `SpeakerEvidence`/`VisualEvidence`-
producing template is later work (25a.2/25b.3 model integration), covered
by ADR 0024's evidence/trust/authorization split.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel


class EnrollmentSampleKind(StrEnum):
    VOICE = "voice"
    FACE = "face"


class EnrollmentSample(BaseModel):
    sample_id: str
    kind: EnrollmentSampleKind
    captured_at: datetime
    content_type: str
    size_bytes: int


class EnrollmentStatus(BaseModel):
    voice_samples: list[EnrollmentSample]
    face_samples: list[EnrollmentSample]
    reauthenticated: bool
    reauth_expires_in_seconds: float | None = None
