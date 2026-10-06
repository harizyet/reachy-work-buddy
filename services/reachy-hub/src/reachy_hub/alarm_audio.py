"""TuneIn stations and bounded stream playback for alarms (Phase 38.3, ADR 0027).

Station search and URL resolution use TuneIn's public OPML API. Stream URLs
are resolved when an alarm plays and are never supplied by a client. Every
URL fetched, including each redirect hop, must be http(s) and resolve only to
public addresses. Residual risk: the name is resolved once for the check and
again by the HTTP client, so a hostile DNS server could rebind in between.
Only direct MP3/AAC streams are handled; HLS stations are skipped.

The robot plays WAV bytes only, so the stream is read continuously, cut into
a short first chunk then longer ones, decoded incrementally in memory with
PyAV and played one chunk after another.
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


async def resolve_stream(client: httpx.AsyncClient, guide_id: str) -> str:
    """Returns the stream URL of the best direct stream."""
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
    return str(best["url"])


def sniff_codec(data: bytes) -> str | None:
    """"aac" for ADTS, "mp3" for MPEG audio, None until a frame header shows.
    TuneIn's listed media type is wrong for some stations, so it is not used."""
    if data.startswith(b"ID3"):
        return "mp3"
    for i in range(len(data) - 1):
        if data[i] != 0xFF:
            continue
        second = data[i + 1]
        if second & 0xF6 == 0xF0:
            return "aac"
        if second & 0xE0 == 0xE0 and second & 0x06 == 0x02:
            return "mp3"
    return None


class _StreamDecoder:
    """Incremental MP3/AAC decoder. Decoder and parser state live across the
    whole stream, so a read that starts mid-frame resyncs and later reads
    decode normally; decoding each slice as a standalone file does not."""

    def __init__(self) -> None:
        import av

        self._av = av
        self._ctx = None
        self._head = b""
        self._resampler = av.AudioResampler(format="s16", layout="mono", rate=SAMPLE_RATE)

    def feed(self, data: bytes) -> list[np.ndarray]:
        av = self._av
        out: list[np.ndarray] = []
        if self._ctx is None:
            self._head += data
            codec = sniff_codec(self._head)
            if codec is None:
                self._head = self._head[-4096:]
                return out
            self._ctx = av.CodecContext.create(codec, "r")
            data, self._head = self._head, b""
        try:
            packets = self._ctx.parse(data)
        except (av.error.FFmpegError, ValueError):
            return out
        for packet in packets:
            try:
                frames = self._ctx.decode(packet)
            except (av.error.FFmpegError, ValueError):
                continue
            for frame in frames:
                for resampled in self._resampler.resample(frame):
                    out.append(resampled.to_ndarray().reshape(-1))
        return out


def pcm_to_wav(pcm: np.ndarray) -> bytes:
    out = io.BytesIO()
    with wave.open(out, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(SAMPLE_RATE)
        wav.writeframes(pcm.astype("<i2").tobytes())
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
    *,
    total_seconds: float,
    first_seconds: float = 5.0,
    chunk_seconds: float = 15.0,
    resolver: Resolver = _resolve_host,
) -> AsyncIterator[bytes]:
    """Yields WAV chunks covering `total_seconds` of decoded audio, sized by
    decoded duration (a station's listed bitrate is unreliable)."""
    wanted = [first_seconds]
    remaining = total_seconds - first_seconds
    while remaining > 0:
        wanted.append(min(chunk_seconds, remaining))
        remaining -= chunk_seconds
    decoder = _StreamDecoder()
    pending: list[np.ndarray] = []
    have = 0
    index = 0
    try:
        async for piece in _open_guarded(client, url, resolver):
            for samples in await asyncio.to_thread(decoder.feed, piece):
                pending.append(samples)
                have += len(samples)
            while index < len(wanted) and have >= wanted[index] * SAMPLE_RATE:
                pcm = np.concatenate(pending)
                size = int(wanted[index] * SAMPLE_RATE)
                pending, have = ([pcm[size:]], len(pcm) - size)
                yield pcm_to_wav(pcm[:size])
                index += 1
            if index >= len(wanted):
                return
    except httpx.HTTPError as exc:
        raise StreamError(f"stream read failed: {exc}") from exc
    if have >= SAMPLE_RATE // 2 or (index == 0 and have):
        yield pcm_to_wav(np.concatenate(pending))
    elif index == 0:
        raise StreamError("stream ended before any audio decoded")


def apply_gain(wav_bytes: bytes, percent: int) -> bytes:
    """Scales 16-bit mono WAV samples, clipping rather than wrapping."""
    if percent == 100:
        return wav_bytes
    with wave.open(io.BytesIO(wav_bytes)) as wav:
        pcm = np.frombuffer(wav.readframes(wav.getnframes()), dtype="<i2")
    return pcm_to_wav(np.clip(pcm.astype(np.float32) * percent / 100, -32768, 32767))


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
