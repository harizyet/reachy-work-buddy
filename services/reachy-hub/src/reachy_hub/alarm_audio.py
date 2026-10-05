"""TuneIn stations and bounded stream playback for alarms (Phase 38.3, ADR 0027).

Station search and URL resolution use TuneIn's public OPML API. Stream URLs
are resolved when an alarm plays and are never supplied by a client. Every
URL fetched, including each redirect hop, must be http(s) and resolve only to
public addresses. Residual risk: the name is resolved once for the check and
again by the HTTP client, so a hostile DNS server could rebind in between.
Only direct MP3/AAC streams are handled; HLS stations are skipped.

The robot plays WAV bytes only, so the stream is read continuously, cut into
a short first chunk then longer ones, decoded in memory with PyAV and played
one chunk after another.
"""

from __future__ import annotations

import asyncio
import contextlib
import io
import ipaddress
import logging
import socket
import time
import wave
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any
from urllib.parse import urljoin, urlsplit

import httpx
import numpy as np

log = logging.getLogger(__name__)

TUNEIN_BASE = "https://opml.radiotime.com"
SAMPLE_RATE = 16000
MAX_REDIRECTS = 3
DEFAULT_BITRATE_KBPS = 128
DIRECT_MEDIA_TYPES = {"mp3", "aac"}
SEARCH_LIMIT = 20


class StreamError(Exception):
    """A stream could not be resolved, fetched or decoded."""


Resolver = Callable[[str], Awaitable[list[str]]]


async def _resolve_host(host: str) -> list[str]:
    infos = await asyncio.get_running_loop().getaddrinfo(host, None, type=socket.SOCK_STREAM)
    return [info[4][0] for info in infos]


async def assert_public_url(url: str, *, resolver: Resolver = _resolve_host) -> None:
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise StreamError("stream URL must be http or https")
    try:
        addresses = await resolver(parts.hostname)
    except OSError as exc:
        raise StreamError("stream host did not resolve") from exc
    if not addresses:
        raise StreamError("stream host did not resolve")
    for address in addresses:
        if not ipaddress.ip_address(address.split("%")[0]).is_global:
            raise StreamError("stream host is not a public address")


async def search_stations(client: httpx.AsyncClient, query: str) -> list[dict[str, str]]:
    try:
        resp = await client.get(
            f"{TUNEIN_BASE}/Search.ashx", params={"query": query, "render": "json", "types": "station"}
        )
        resp.raise_for_status()
        body = resp.json().get("body", [])
    except (httpx.HTTPError, ValueError) as exc:
        raise StreamError(f"TuneIn search failed: {exc}") from exc
    found: list[dict[str, str]] = []
    for item in body:
        guide_id = str(item.get("guide_id", ""))
        if guide_id.startswith("s") and guide_id[1:].isdigit():
            found.append({"guide_id": guide_id, "name": str(item.get("text", guide_id)), "detail": str(item.get("subtext", ""))})
    return found[:SEARCH_LIMIT]


async def resolve_stream(client: httpx.AsyncClient, guide_id: str) -> tuple[str, int]:
    """Returns (stream URL, bitrate kbps) of the best direct stream."""
    try:
        resp = await client.get(f"{TUNEIN_BASE}/Tune.ashx", params={"id": guide_id, "render": "json"})
        resp.raise_for_status()
        body = resp.json().get("body", [])
    except (httpx.HTTPError, ValueError) as exc:
        raise StreamError(f"TuneIn lookup failed: {exc}") from exc
    candidates = [
        item
        for item in body
        if item.get("element") == "audio"
        and str(item.get("media_type", "")).lower() in DIRECT_MEDIA_TYPES
        and str(item.get("is_hls_advanced", "false")).lower() != "true"
        and item.get("url")
    ]
    if not candidates:
        raise StreamError("station has no direct MP3/AAC stream")
    best = max(candidates, key=lambda i: int(i.get("reliability") or 0))
    return str(best["url"]), int(best.get("bitrate") or DEFAULT_BITRATE_KBPS)


def decode_to_wav(data: bytes) -> bytes:
    """Decodes a raw MP3/AAC slice to 16 kHz mono 16-bit WAV. A slice cut
    mid-frame resyncs at the next frame, so the cut costs at most a click."""
    import av

    samples: list[np.ndarray] = []
    try:
        with av.open(io.BytesIO(data), mode="r") as container:
            resampler = av.AudioResampler(format="s16", layout="mono", rate=SAMPLE_RATE)
            for frame in container.decode(audio=0):
                for out in resampler.resample(frame):
                    samples.append(out.to_ndarray().reshape(-1))
    except (av.error.FFmpegError, ValueError, OSError) as exc:
        if not samples:
            raise StreamError(f"could not decode stream audio: {exc}") from exc
    if not samples:
        raise StreamError("stream audio decoded to nothing")
    pcm = np.concatenate(samples).astype("<i2")
    out = io.BytesIO()
    with wave.open(out, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(SAMPLE_RATE)
        wav.writeframes(pcm.tobytes())
    return out.getvalue()


async def _open_guarded(
    client: httpx.AsyncClient, url: str, resolver: Resolver
) -> AsyncIterator[bytes]:
    for _ in range(MAX_REDIRECTS + 1):
        await assert_public_url(url, resolver=resolver)
        request = client.build_request("GET", url, headers={"Icy-MetaData": "0"})
        response = await client.send(request, stream=True)
        if response.is_redirect:
            location = response.headers.get("location")
            await response.aclose()
            if not location:
                raise StreamError("stream redirect without a location")
            url = urljoin(url, location)
            continue
        try:
            response.raise_for_status()
            async for piece in response.aiter_bytes(8192):
                yield piece
        finally:
            await response.aclose()
        return
    raise StreamError("too many stream redirects")


async def stream_chunks(
    client: httpx.AsyncClient,
    url: str,
    bitrate_kbps: int,
    *,
    total_seconds: float,
    first_seconds: float = 5.0,
    chunk_seconds: float = 15.0,
    resolver: Resolver = _resolve_host,
) -> AsyncIterator[bytes]:
    """Yields WAV chunks covering roughly `total_seconds` of the stream."""
    bytes_per_second = max(1, bitrate_kbps) * 1000 // 8
    wanted = [first_seconds]
    remaining = total_seconds - first_seconds
    while remaining > 0:
        wanted.append(min(chunk_seconds, remaining))
        remaining -= chunk_seconds
    buffer = bytearray()
    index = 0
    try:
        async for piece in _open_guarded(client, url, resolver):
            buffer.extend(piece)
            while index < len(wanted) and len(buffer) >= wanted[index] * bytes_per_second:
                size = int(wanted[index] * bytes_per_second)
                raw, buffer = bytes(buffer[:size]), buffer[size:]
                yield await asyncio.to_thread(decode_to_wav, raw)
                index += 1
            if index >= len(wanted):
                return
    except httpx.HTTPError as exc:
        raise StreamError(f"stream read failed: {exc}") from exc
    if index == 0:
        raise StreamError("stream ended before any audio arrived")


def chime_wav(seconds: float = 6.0) -> bytes:
    """Plain repeating two-tone chime for an alarm with no station chosen."""
    t = np.arange(int(SAMPLE_RATE * 0.4)) / SAMPLE_RATE
    note = lambda hz: (np.sin(2 * np.pi * hz * t) * np.hanning(len(t)) * 0.4)
    pair = np.concatenate([note(880), note(660), np.zeros(int(SAMPLE_RATE * 0.4))])
    pcm = (np.tile(pair, max(1, round(seconds / (len(pair) / SAMPLE_RATE)))) * 32767).astype("<i2")
    out = io.BytesIO()
    with wave.open(out, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(SAMPLE_RATE)
        wav.writeframes(pcm.tobytes())
    return out.getvalue()


def wav_seconds(wav_bytes: bytes) -> float:
    with wave.open(io.BytesIO(wav_bytes)) as wav:
        return wav.getnframes() / wav.getframerate()


async def play_chunks(
    play: Callable[[bytes], Awaitable[Any]],
    chunks: AsyncIterator[bytes],
    stop: asyncio.Event,
    *,
    clock: Callable[[], float] = time.monotonic,
) -> int:
    """Plays each chunk when the previous one ends. Returns chunks played.
    `stop` ends it between chunks; the caller also silences the robot."""
    played = 0
    ends_at = clock()
    async for wav_bytes in chunks:
        wait = ends_at - clock()
        if wait > 0:
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(stop.wait(), timeout=wait)
        if stop.is_set():
            break
        await play(wav_bytes)
        played += 1
        ends_at = clock() + wav_seconds(wav_bytes)
    return played
