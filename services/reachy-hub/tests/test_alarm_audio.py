"""TuneIn lookup, SSRF guard, stream chunking and chunk playback (Phase 38.3)."""

import asyncio
import io

import httpx
import numpy as np
import pytest
from reachy_hub import alarm_audio as aa


def make_mp3(seconds: float) -> bytes:
    import av

    out = io.BytesIO()
    with av.open(out, mode="w", format="mp3") as container:
        stream = container.add_stream("mp3", rate=44100)
        stream.bit_rate = 128000
        t = np.arange(int(44100 * seconds)) / 44100
        pcm = (np.sin(2 * np.pi * 440 * t) * 12000).astype(np.int16).reshape(1, -1)
        frame = av.AudioFrame.from_ndarray(pcm, format="s16", layout="mono")
        frame.sample_rate = 44100
        for packet in stream.encode(frame):
            container.mux(packet)
        for packet in stream.encode(None):
            container.mux(packet)
    return out.getvalue()


def public(_host):
    async def resolve(_h):
        return ["93.184.216.34"]

    return resolve(_host)


def client_for(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def run(coro):
    return asyncio.run(coro)


def test_guard_accepts_public_and_rejects_private_loopback_link_local_and_odd_schemes():
    async def resolves(*addresses):
        async def resolver(_host):
            return list(addresses)

        return resolver

    async def check(url, *addresses):
        await aa.assert_public_url(url, resolver=await resolves(*addresses))

    run(check("http://radio.example/stream", "93.184.216.34"))
    for url, addresses in [
        ("http://radio.example/s", ("127.0.0.1",)),
        ("http://radio.example/s", ("10.0.0.5",)),
        ("http://radio.example/s", ("169.254.169.254",)),
        ("http://radio.example/s", ("93.184.216.34", "192.168.1.1")),
        ("http://radio.example/s", ("::1",)),
        ("http://radio.example/s", ()),
        ("file:///etc/passwd", ("93.184.216.34",)),
        ("ftp://radio.example/s", ("93.184.216.34",)),
    ]:
        with pytest.raises(aa.StreamError):
            run(check(url, *addresses))


def test_search_keeps_only_numeric_station_ids_and_tune_picks_the_most_reliable_direct_stream():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/Search.ashx":
            assert request.url.params["query"] == "jazz"
            return httpx.Response(200, json={"body": [
                {"text": "Artist: X", "guide_id": "m1"},
                {"text": "Jazz FM", "subtext": "London", "guide_id": "s123"},
                {"text": "Bad", "guide_id": "sabc"},
            ]})
        return httpx.Response(200, json={"body": [
            {"element": "audio", "url": "http://a/hls", "media_type": "hls", "reliability": 100},
            {"element": "audio", "url": "http://a/low", "media_type": "mp3", "reliability": 40, "bitrate": 64},
            {"element": "audio", "url": "http://a/best", "media_type": "aac", "reliability": 90, "bitrate": 96},
        ]})

    async def go():
        async with client_for(handler) as client:
            assert await aa.search_stations(client, "jazz") == [{"guide_id": "s123", "name": "Jazz FM", "detail": "London"}]
            assert await aa.resolve_stream(client, "s123") == "http://a/best"

    run(go())


def test_tune_without_a_direct_stream_or_with_an_error_raises():
    async def go():
        async with client_for(lambda r: httpx.Response(200, json={"body": [{"element": "audio", "url": "u", "media_type": "hls"}]})) as c:
            with pytest.raises(aa.StreamError):
                await aa.resolve_stream(c, "s1")
        async with client_for(lambda r: httpx.Response(500)) as c:
            with pytest.raises(aa.StreamError):
                await aa.resolve_stream(c, "s1")

    run(go())


def test_stream_is_cut_into_first_then_later_chunks_and_decoded_to_wav():
    data = make_mp3(8.0)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=data)

    async def go():
        async with client_for(handler) as client:
            return [
                w
                async for w in aa.stream_chunks(
                    client, "http://radio.example/s", total_seconds=7, first_seconds=2, chunk_seconds=3, resolver=public
                )
            ]

    chunks = run(go())
    assert len(chunks) == 3
    durations = [aa.wav_seconds(c) for c in chunks]
    assert durations[0] == pytest.approx(2.0, abs=0.2) and durations[1] == pytest.approx(3.0, abs=0.2)


def test_stream_joined_mid_frame_in_odd_pieces_still_decodes_every_chunk():
    data = make_mp3(8.0)[1001:]

    async def go():
        client = httpx.AsyncClient(transport=httpx.MockTransport(
            lambda r: httpx.Response(200, content=data)))
        async with client:
            return [w async for w in aa.stream_chunks(
                client, "http://radio.example/s", total_seconds=6, first_seconds=2, chunk_seconds=2, resolver=public)]

    chunks = run(go())
    assert len(chunks) == 3
    assert all(aa.wav_seconds(c) == pytest.approx(2.0, abs=0.05) for c in chunks)


def test_redirect_to_a_private_host_is_refused_and_redirect_loops_end():
    async def resolver(host):
        return ["10.0.0.1"] if host == "internal" else ["93.184.216.34"]

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "radio.example":
            return httpx.Response(302, headers={"location": "http://internal/secret"})
        raise AssertionError("private host must not be fetched")

    async def go(h, url):
        async with client_for(h) as client:
            return [w async for w in aa.stream_chunks(client, url, total_seconds=5, resolver=resolver)]

    with pytest.raises(aa.StreamError, match="public"):
        run(go(handler, "http://radio.example/s"))
    with pytest.raises(aa.StreamError, match="redirects"):
        run(go(lambda r: httpx.Response(302, headers={"location": "/again"}), "http://radio.example/s"))


def test_short_stream_with_no_complete_chunk_fails_and_garbage_does_not_decode():
    async def go():
        async with client_for(lambda r: httpx.Response(200, content=b"x" * 100)) as client:
            return [w async for w in aa.stream_chunks(client, "http://radio.example/s", total_seconds=5, resolver=public)]

    with pytest.raises(aa.StreamError):
        run(go())


def test_chime_is_valid_wav_and_chunk_playback_waits_for_each_chunk_and_honours_stop():
    chime = aa.chime_wav(2.0)
    assert 1.5 < aa.wav_seconds(chime) < 3.0

    async def chunks(n):
        for _ in range(n):
            yield chime

    async def go():
        now = [0.0]
        played: list[float] = []

        async def play(_wav):
            played.append(now[0])

        stop = asyncio.Event()
        count = await aa.play_chunks(play, chunks(2), stop, clock=lambda: now[0])
        assert count == 2 and played == [0.0, 0.0]  # the clock never advanced past the first end

        played.clear()
        stop = asyncio.Event()
        stop.set()
        assert await aa.play_chunks(play, chunks(3), stop, clock=lambda: now[0]) == 0

        calls = []

        async def play_and_stop(_wav):
            calls.append(1)
            stop.set()

        stop = asyncio.Event()
        assert await aa.play_chunks(play_and_stop, chunks(5), stop) == 1 and calls == [1]

    run(go())


def test_codec_is_sniffed_from_frame_headers_not_the_listed_media_type():
    assert aa.sniff_codec(b"\x00\x12\xff\xf1\x50\x80") == "aac"
    assert aa.sniff_codec(b"junk\xff\xfb\x90\x00") == "mp3"
    assert aa.sniff_codec(b"ID3\x04") == "mp3"
    assert aa.sniff_codec(b"no header here") is None
