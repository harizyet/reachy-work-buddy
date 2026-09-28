"""Raw owner-recognition sample capture (Phase 25a.2/25b.3 portal skeleton).

Stores whatever voice/face samples the owner records through the Settings
portal so a real benchmark/enrollment dataset can be built (Phase 25a.1's
next step, and eventual 25a.2/25b.3 template creation). This is
deliberately *not* the encrypted biometric-template store
`docs/phase-25.md` describes for an activated profile
(`reachy_hub/recognition_store.py` in the proposed layout) — no
verification model reads these files, and nothing here is evidence a
`TrustEngine` (`reachy_hub/trust.py`) would accept. Keep that distinction:
a captured sample is raw diagnostic data, not a template.
"""

from __future__ import annotations

import json
import os
import secrets
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

from shared.models.enrollment import EnrollmentSample, EnrollmentSampleKind

# Generous but bounded: a single browser-recorded voice/face capture.
MAX_SAMPLE_BYTES = 10 * 1024 * 1024

_CONTENT_TYPES = {
    EnrollmentSampleKind.VOICE: {"audio/webm", "audio/ogg", "audio/wav", "audio/wave"},
    EnrollmentSampleKind.FACE: {"image/jpeg", "image/png", "image/webp"},
}


class SampleRejected(Exception):
    pass


class EnrollmentStore(Protocol):
    async def add_sample(
        self, kind: EnrollmentSampleKind, content_type: str, data: bytes
    ) -> EnrollmentSample: ...
    async def list_samples(self, kind: EnrollmentSampleKind) -> list[EnrollmentSample]: ...
    async def delete_sample(self, kind: EnrollmentSampleKind, sample_id: str) -> bool: ...
    async def delete_all(self, kind: EnrollmentSampleKind) -> int: ...


def _validate(kind: EnrollmentSampleKind, content_type: str, data: bytes) -> None:
    if content_type not in _CONTENT_TYPES[kind]:
        raise SampleRejected(f"Unsupported content type for {kind.value}: {content_type}")
    if not data:
        raise SampleRejected("Empty sample")
    if len(data) > MAX_SAMPLE_BYTES:
        raise SampleRejected("Sample too large")


class InMemoryEnrollmentStore:
    """Process-local default: samples vanish on restart. Real deployment
    should set `OWNER_RECOGNITION_CAPTURE_DIR` to use
    `FilesystemEnrollmentStore` instead — this default exists so
    `create_app()` never touches the filesystem unconfigured, matching
    every other optional-integration default in `app.py`."""

    def __init__(self) -> None:
        self._samples: dict[EnrollmentSampleKind, dict[str, tuple[EnrollmentSample, bytes]]] = {
            kind: {} for kind in EnrollmentSampleKind
        }

    async def add_sample(
        self, kind: EnrollmentSampleKind, content_type: str, data: bytes
    ) -> EnrollmentSample:
        _validate(kind, content_type, data)
        sample = EnrollmentSample(
            sample_id=secrets.token_urlsafe(16),
            kind=kind,
            captured_at=datetime.now(UTC),
            content_type=content_type,
            size_bytes=len(data),
        )
        self._samples[kind][sample.sample_id] = (sample, data)
        return sample

    async def list_samples(self, kind: EnrollmentSampleKind) -> list[EnrollmentSample]:
        return sorted((sample for sample, _ in self._samples[kind].values()), key=lambda sample: sample.captured_at)

    async def delete_sample(self, kind: EnrollmentSampleKind, sample_id: str) -> bool:
        return self._samples[kind].pop(sample_id, None) is not None

    async def delete_all(self, kind: EnrollmentSampleKind) -> int:
        count = len(self._samples[kind])
        self._samples[kind].clear()
        return count


class FilesystemEnrollmentStore:
    """One directory per kind, one file plus a JSON metadata sidecar per
    sample. Restricted to the owner (0700 dirs, 0600 files) since these are
    raw voice/face recordings. Metadata is re-read from disk on every call
    rather than cached: this dataset stays small (tens of samples), and a
    file-backed source of truth survives a hub restart without needing its
    own persistence layer."""

    def __init__(self, root: str | Path) -> None:
        self._root = Path(root)
        for kind in EnrollmentSampleKind:
            (self._root / kind.value).mkdir(parents=True, exist_ok=True, mode=0o700)

    def _dir(self, kind: EnrollmentSampleKind) -> Path:
        return self._root / kind.value

    async def add_sample(
        self, kind: EnrollmentSampleKind, content_type: str, data: bytes
    ) -> EnrollmentSample:
        _validate(kind, content_type, data)
        sample_id = secrets.token_urlsafe(16)
        captured_at = datetime.now(UTC)
        sample = EnrollmentSample(
            sample_id=sample_id,
            kind=kind,
            captured_at=captured_at,
            content_type=content_type,
            size_bytes=len(data),
        )
        directory = self._dir(kind)
        data_path = directory / sample_id
        meta_path = directory / f"{sample_id}.json"
        data_path.write_bytes(data)
        os.chmod(data_path, 0o600)
        meta_path.write_text(sample.model_dump_json())
        os.chmod(meta_path, 0o600)
        return sample

    async def list_samples(self, kind: EnrollmentSampleKind) -> list[EnrollmentSample]:
        samples = []
        for meta_path in self._dir(kind).glob("*.json"):
            samples.append(EnrollmentSample.model_validate(json.loads(meta_path.read_text())))
        samples.sort(key=lambda sample: sample.captured_at)
        return samples

    async def delete_sample(self, kind: EnrollmentSampleKind, sample_id: str) -> bool:
        directory = self._dir(kind)
        # Reject anything that isn't a bare token before it touches the
        # filesystem, so a crafted sample_id can never walk outside the
        # per-kind directory.
        if "/" in sample_id or "\\" in sample_id or sample_id in {".", ".."}:
            return False
        data_path, meta_path = directory / sample_id, directory / f"{sample_id}.json"
        if not meta_path.is_file():
            return False
        meta_path.unlink(missing_ok=True)
        data_path.unlink(missing_ok=True)
        return True

    async def delete_all(self, kind: EnrollmentSampleKind) -> int:
        samples = await self.list_samples(kind)
        for sample in samples:
            await self.delete_sample(kind, sample.sample_id)
        return len(samples)
