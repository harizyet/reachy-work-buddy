"""HTTP clients for the Phase 27.2/27.3 speech-inference sidecars
(ADR 0025 — docs/adr/0025-speech-inference-service.md).

companion-core consumes speech inference only through the seam this
module defines — a `TranscriptionClient`/`DiarizationClient` protocol,
each with one real HTTP implementation — never a hardcoded hostname
scattered through `worker.py`, and never by importing `reachy_hub.stt`
(ADR 0001 sibling-import ban, reaffirmed by ADR 0025). Pointing both at a
future unified `speech-service` instead of today's two separate sidecars
is meant to be a constructor-argument change here, not a `MeetingWorker`
rewrite.

Both sidecars currently share one response shape (see
`deploy/homelab/diarization/app/server.py` and the transcription sidecar
under `deploy/homelab/transcription/`): `{duration_s, process_s, rtf,
segments: [...]}`. Only `segments` is used here; the timing fields are
for the sidecar's own `/health`-adjacent operator visibility, not
something companion-core currently persists.
"""

from __future__ import annotations

import math
import os
from typing import Any, BinaryIO, Protocol

import httpx

# ADR 0025's "authenticated service-to-service calls". Optional on
# purpose, matching this codebase's other internal-only integrations
# (REMOTE_UI_TOKEN, ACCOUNTS_SERVICE_TOKEN): unset means no header is
# sent and the sidecars (which check the same env var) don't require
# one — fine on a homelab where only the Compose network can reach them.
# Set SPEECH_SERVICE_TOKEN identically here and on both sidecars to
# require it.
_SPEECH_SERVICE_TOKEN_HEADER = "X-Reachy-Speech-Token"


def _auth_headers() -> dict[str, str]:
    token = os.environ.get("SPEECH_SERVICE_TOKEN")
    return {_SPEECH_SERVICE_TOKEN_HEADER: token} if token else {}


def _inference_timeout(override: float | None) -> httpx.Timeout:
    # This is response inactivity, not audio duration. Slow inference can
    # exceed real time; keep connection failures fast while allowing long jobs.
    seconds = override if override is not None else float(os.environ.get("MEETING_INFERENCE_TIMEOUT_SECONDS", "21600"))
    if not math.isfinite(seconds) or seconds <= 0:
        raise ValueError("MEETING_INFERENCE_TIMEOUT_SECONDS must be finite and positive")
    return httpx.Timeout(seconds, connect=10.0, write=600.0, pool=10.0)


class SpeechServiceError(Exception):
    """Base for a speech-inference sidecar call that did not produce segments."""


class SpeechServiceUnavailable(SpeechServiceError):
    """Transient: connection failed, timed out, or the sidecar isn't ready/returned
    5xx. The caller should leave job state unchanged and retry later, not fail
    the job — the sidecar being briefly down (or not deployed at all) is not
    the meeting's fault."""


class SpeechServiceRejected(SpeechServiceError):
    """Permanent: the sidecar understood the request and refused it (e.g.
    unreadable audio). Retrying the same audio would not help."""


class TranscriptionClient(Protocol):
    async def transcribe(self, audio: bytes | BinaryIO, *, filename: str, content_type: str) -> list[dict[str, Any]]: ...


class DiarizationClient(Protocol):
    async def diarize(self, audio: bytes | BinaryIO, *, filename: str, content_type: str) -> list[dict[str, Any]]: ...


async def _post_audio(
    client: httpx.AsyncClient, path: str, audio: bytes | BinaryIO, *, filename: str, content_type: str
) -> list[dict[str, Any]]:
    try:
        response = await client.post(path, files={"file": (filename, audio, content_type)})
    except httpx.HTTPError as exc:
        raise SpeechServiceUnavailable(f"{path} unreachable: {exc}") from exc
    if response.status_code >= 500 or response.status_code == 503:
        raise SpeechServiceUnavailable(f"{path} returned {response.status_code}")
    if response.status_code >= 400:
        detail = response.text
        try:
            detail = response.json().get("detail", detail)
        except ValueError:
            pass
        raise SpeechServiceRejected(f"{path} rejected the request ({response.status_code}): {detail}")
    return response.json()["segments"]


class HTTPTranscriptionClient:
    def __init__(
        self,
        base_url: str | None = None,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout: float | None = None,
    ) -> None:
        base = base_url or os.environ.get("TRANSCRIPTION_URL") or "http://transcription:8011"
        self._client = httpx.AsyncClient(base_url=base, transport=transport, timeout=_inference_timeout(timeout), headers=_auth_headers())

    async def aclose(self) -> None:
        await self._client.aclose()

    async def transcribe(self, audio: bytes | BinaryIO, *, filename: str, content_type: str) -> list[dict[str, Any]]:
        return await _post_audio(self._client, "/transcribe", audio, filename=filename, content_type=content_type)


class HTTPDiarizationClient:
    def __init__(
        self,
        base_url: str | None = None,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout: float | None = None,
    ) -> None:
        base = base_url or os.environ.get("DIARIZATION_URL") or "http://diarization:8010"
        self._client = httpx.AsyncClient(base_url=base, transport=transport, timeout=_inference_timeout(timeout), headers=_auth_headers())

    async def aclose(self) -> None:
        await self._client.aclose()

    async def diarize(self, audio: bytes | BinaryIO, *, filename: str, content_type: str) -> list[dict[str, Any]]:
        return await _post_audio(self._client, "/diarize", audio, filename=filename, content_type=content_type)
