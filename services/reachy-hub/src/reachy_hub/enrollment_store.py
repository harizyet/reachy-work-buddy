"""Owner-recognition benchmark-capture dataset (Phase 25a.2/25b.3 portal
skeleton, Phase 26d benchmark-vs-operational data policy:
docs/phase-26.md#26d-addendum-benchmark-vs-operational-data-policy-owner-decision-2026-09-28).

This is explicitly the *benchmark* store, never the future *operational*
enrollment store: raw voice/face captures are retained here only because
an explicitly enabled benchmark/calibration purpose needs them (building
and evaluating a real owner/non-owner dataset, comparing model
candidates, replay/spoof testing). Nothing here is a biometric template,
and no verification model reads these files — see
`docs/phase-25.md`'s proposed `reachy_hub/recognition_store.py` for where
an operational, template-only store belongs once one exists. Keeping the
two conceptually and, eventually, physically separate matters: deleting
this research dataset must never risk an active biometric profile, and
re-enrolling the owner must never leave an old raw dataset implicitly
trusted by anything.
"""

from __future__ import annotations

import json
import os
import secrets
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

from reachy_hub.keyring import Keyring
from shared.models.enrollment import EnrollmentSample, EnrollmentSampleKind

# Generous but bounded: a single browser-recorded voice/face capture.
MAX_SAMPLE_BYTES = 10 * 1024 * 1024

_CONTENT_TYPES = {
    EnrollmentSampleKind.VOICE: {"audio/webm", "audio/ogg", "audio/wav", "audio/wave"},
    EnrollmentSampleKind.FACE: {"image/jpeg", "image/png", "image/webp"},
}


class SampleRejected(Exception):
    pass


class BenchmarkModeDisabled(Exception):
    """The owner has not explicitly enabled benchmark-dataset collection
    (Phase 26d's "explicitly enabled" requirement). Distinct from
    `SampleRejected`: this is an authorization gate, not a data-validation
    failure — the caller should answer 403, not 422."""


class EnrollmentStore(Protocol):
    async def is_benchmark_enabled(self) -> bool: ...
    async def set_benchmark_enabled(self, enabled: bool) -> None: ...
    async def add_sample(
        self, kind: EnrollmentSampleKind, content_type: str, data: bytes
    ) -> EnrollmentSample: ...
    async def list_samples(self, kind: EnrollmentSampleKind) -> list[EnrollmentSample]: ...
    async def read_sample(self, kind: EnrollmentSampleKind, sample_id: str) -> bytes | None: ...
    async def delete_sample(self, kind: EnrollmentSampleKind, sample_id: str) -> bool: ...
    async def delete_all(self, kind: EnrollmentSampleKind) -> int: ...


def _validate(kind: EnrollmentSampleKind, content_type: str, data: bytes) -> None:
    if content_type not in _CONTENT_TYPES[kind]:
        raise SampleRejected(f"Unsupported content type for {kind.value}: {content_type}")
    if not data:
        raise SampleRejected("Empty sample")
    if len(data) > MAX_SAMPLE_BYTES:
        raise SampleRejected("Sample too large")


def _sample_aad(kind: EnrollmentSampleKind, sample_id: str, content_type: str) -> bytes:
    # Binds ciphertext to this exact sample's identity/kind/content-type so
    # a swapped or relabeled encrypted file fails to decrypt rather than
    # silently being accepted as a different sample.
    return json.dumps([kind.value, sample_id, content_type], separators=(",", ":")).encode()


class InMemoryEnrollmentStore:
    """Process-local default: samples vanish on restart. Real deployment
    should set `OWNER_RECOGNITION_CAPTURE_DIR` (plus `SECRET_KEY_FILE`) to
    use `FilesystemEnrollmentStore` instead — this default exists so
    `create_app()` never touches the filesystem or requires an encryption
    key unconfigured, matching every other optional-integration default in
    `app.py`. Not encrypted: there is nothing "at rest" to protect when
    nothing is persisted past process lifetime."""

    def __init__(self) -> None:
        self._samples: dict[EnrollmentSampleKind, dict[str, tuple[EnrollmentSample, bytes]]] = {
            kind: {} for kind in EnrollmentSampleKind
        }
        self._benchmark_enabled = False

    async def is_benchmark_enabled(self) -> bool:
        return self._benchmark_enabled

    async def set_benchmark_enabled(self, enabled: bool) -> None:
        self._benchmark_enabled = enabled

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

    async def read_sample(self, kind: EnrollmentSampleKind, sample_id: str) -> bytes | None:
        entry = self._samples[kind].get(sample_id)
        return entry[1] if entry else None

    async def delete_sample(self, kind: EnrollmentSampleKind, sample_id: str) -> bool:
        return self._samples[kind].pop(sample_id, None) is not None

    async def delete_all(self, kind: EnrollmentSampleKind) -> int:
        count = len(self._samples[kind])
        self._samples[kind].clear()
        return count


class FilesystemEnrollmentStore:
    """One directory per kind, one AESGCM-encrypted file plus a plaintext
    JSON metadata sidecar per sample (Phase 26d: encryption at rest is a
    hard requirement for any persisted benchmark capture, not optional).
    Metadata (id/kind/content-type/size — never the sample content itself)
    is re-read from disk on every call rather than cached: this dataset
    stays small (tens of samples), and a file-backed source of truth
    survives a hub restart without needing its own persistence layer. The
    `enabled` flag is a single JSON marker file, so "benchmark collection
    is on" also survives a restart rather than resetting silently."""

    def __init__(self, root: str | Path, keyring: Keyring) -> None:
        self._root = Path(root)
        self._keyring = keyring
        for kind in EnrollmentSampleKind:
            (self._root / kind.value).mkdir(parents=True, exist_ok=True, mode=0o700)

    def _dir(self, kind: EnrollmentSampleKind) -> Path:
        return self._root / kind.value

    def _enabled_marker(self) -> Path:
        return self._root / "benchmark_enabled"

    async def is_benchmark_enabled(self) -> bool:
        return self._enabled_marker().is_file()

    async def set_benchmark_enabled(self, enabled: bool) -> None:
        marker = self._enabled_marker()
        if enabled:
            marker.touch(mode=0o600, exist_ok=True)
        else:
            marker.unlink(missing_ok=True)

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
        record = self._keyring.encrypt(_sample_aad(kind, sample_id, content_type), data)
        directory = self._dir(kind)
        data_path = directory / sample_id
        meta_path = directory / f"{sample_id}.json"
        data_path.write_text(json.dumps({
            "key_id": record["key_id"],
            "nonce": record["nonce"].hex(),
            "ciphertext": record["ciphertext"].hex(),
        }))
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

    async def read_sample(self, kind: EnrollmentSampleKind, sample_id: str) -> bytes | None:
        meta_path = self._dir(kind) / f"{sample_id}.json"
        data_path = self._dir(kind) / sample_id
        if not meta_path.is_file() or not data_path.is_file():
            return None
        meta = EnrollmentSample.model_validate(json.loads(meta_path.read_text()))
        record = json.loads(data_path.read_text())
        return self._keyring.decrypt(
            _sample_aad(kind, sample_id, meta.content_type),
            {
                "key_id": record["key_id"],
                "nonce": bytes.fromhex(record["nonce"]),
                "ciphertext": bytes.fromhex(record["ciphertext"]),
            },
        )

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
