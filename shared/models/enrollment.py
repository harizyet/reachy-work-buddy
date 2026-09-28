"""Owner-recognition raw benchmark-capture dataset (Phase 25a.2/25b.3
portal skeleton; docs/phase-25.md's "Enrollment portal" section; Phase
26d's benchmark-vs-operational data policy,
docs/phase-26.md#26d-addendum-benchmark-vs-operational-data-policy-owner-decision-2026-09-28).

These are consented, raw voice/face samples collected through the owner
portal's explicitly-enabled benchmark mode, to build a real
benchmark/calibration dataset. They are **not** biometric templates: no
speaker or face verification model reads them yet (Phase 25a.1's
benchmark uses its own separate, unrelated public example clips — see
docs/verification/phase-25a1-voice-benchmark-2026-09-28.md). Turning
captured samples into an activated `SpeakerEvidence`/`VisualEvidence`-
producing template is later work (25a.2/25b.3 model integration), covered
by ADR 0024's evidence/trust/authorization split, and belongs in a
separate operational store per the Phase 26d policy — never this one.
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
    benchmark_enabled: bool
    voice_samples: list[EnrollmentSample]
    face_samples: list[EnrollmentSample]
    voice_total_bytes: int
    face_total_bytes: int
    reauthenticated: bool
    reauth_expires_in_seconds: float | None = None
