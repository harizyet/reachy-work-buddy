"""Long-recording transport checks; inference quality is tested separately."""
import asyncio
import io
import struct
from contextlib import asynccontextmanager

import httpx
import pytest
from companion_core.meetings.models import MeetingJobStatus
from companion_core.meetings.postgres_store import PostgresMeetingStore
from companion_core.meetings.speech_clients import (
    HTTPDiarizationClient,
    HTTPTranscriptionClient,
)
from companion_core.meetings.store import InMemoryMeetingStore
from companion_core.meetings.worker import MeetingWorker


class BoundedReader(io.BufferedReader):
    def read(self, size=-1):
        assert 0 <= size <= 1024 * 1024, "audio must not be read wholesale"
        return super().read(size)


def long_wav(path):
    # Sparse 65-minute 16 kHz PCM WAV: real duration/size without a giant fixture.
    size = 3900 * 16000 * 2
    with path.open("wb") as stream:
        stream.write(struct.pack("<4sI4s4sIHHIIHH4sI", b"RIFF", size + 36, b"WAVE",
                                 b"fmt ", 16, 1, 1, 16000, 32000, 2, 16, b"data", size))
        stream.truncate(size + 44)
    return size + 44


class StreamingSpeechTransport(httpx.AsyncBaseTransport):
    def __init__(self):
        self.requests = []

    async def handle_async_request(self, request):
        assert request.extensions["timeout"]["read"] == 21600
        assert request.extensions["timeout"]["connect"] == 10
        total = 0
        async for chunk in request.stream:
            assert len(chunk) <= 65536
            total += len(chunk)
        self.requests.append((request.url.path, total))
        segment = {"start": 3890.0, "end": 3900.0}
        segment.update({"text": "last words"} if request.url.path == "/transcribe" else {"speaker": "speaker_0"})
        return httpx.Response(200, json={"segments": [segment]})


def test_65_minute_worker_streams_both_requests_and_closes_files(tmp_path, monkeypatch):
    monkeypatch.delenv("MEETING_INFERENCE_TIMEOUT_SECONDS", raising=False)
    path = tmp_path / "long.wav"
    size = long_wav(path)

    class DiskStore(InMemoryMeetingStore):
        def __init__(self):
            super().__init__()
            self.streams = []

        async def open_audio(self, meeting_id):
            stream = BoundedReader(path.open("rb", buffering=0))
            self.streams.append(stream)
            return stream

        async def load_audio(self, meeting_id):
            pytest.fail("worker must use file-backed audio")

    async def run():
        store = DiskStore()
        meeting = await store.create_meeting(title="long", audio=b"", source_filename="long.wav", content_type="audio/wav")
        transport = StreamingSpeechTransport()
        stt = HTTPTranscriptionClient(transport=transport)
        diar = HTTPDiarizationClient(transport=transport)
        try:
            worker = MeetingWorker(store, transcription_client=stt, diarization_client=diar)
            for _ in range(3):
                assert await worker.process_one()
            result = await store.get_meeting(meeting.id)
            assert result.duration_seconds == 3900
            assert result.status == MeetingJobStatus.ALIGNING
            assert result.transcript_segments[-1]["end"] == 3900
            assert result.diarization_segments[-1]["end"] == 3900
            assert [path for path, _ in transport.requests] == ["/transcribe", "/diarize"]
            assert all(size < count < size + 1024 for _, count in transport.requests)
            assert all(stream.closed for stream in store.streams)
        finally:
            await stt.aclose()
            await diar.aclose()
    asyncio.run(run())


def test_postgres_store_copies_upload_in_bounded_blocks(tmp_path):
    class Connection:
        async def execute(self, *args):
            pass

    class Pool:
        @asynccontextmanager
        async def connection(self):
            yield Connection()

    path = tmp_path / "source.wav"
    size = long_wav(path)

    async def run():
        store = PostgresMeetingStore(Pool(), tmp_path / "audio")
        with BoundedReader(path.open("rb", buffering=0)) as source:
            meeting = await store.create_meeting(title="long", audio=source, source_filename="long.wav", content_type="audio/wav")
        saved = store._audio_file(meeting.id, meeting.audio_path)
        assert saved.stat().st_size == size
        with saved.open("rb") as source:
            assert source.read(4) == b"RIFF"
    asyncio.run(run())


@pytest.mark.parametrize("client_type", [HTTPTranscriptionClient, HTTPDiarizationClient])
def test_inference_timeout_configuration(client_type, monkeypatch):
    async def run():
        monkeypatch.setenv("MEETING_INFERENCE_TIMEOUT_SECONDS", "28800")
        client = client_type()
        assert client._client.timeout.read == 28800
        await client.aclose()
        client = client_type(timeout=42)
        assert client._client.timeout.read == 42
        await client.aclose()
        for invalid in ("0", "-1", "nan", "inf"):
            monkeypatch.setenv("MEETING_INFERENCE_TIMEOUT_SECONDS", invalid)
            with pytest.raises(ValueError):
                client_type()
    asyncio.run(run())


@pytest.mark.parametrize("failure", [httpx.ReadTimeout, httpx.ConnectError])
def test_retry_reopens_audio_and_preserves_completed_transcription(failure):
    class Store(InMemoryMeetingStore):
        def __init__(self):
            super().__init__()
            self.streams = []

        async def open_audio(self, meeting_id):
            stream = await super().open_audio(meeting_id)
            self.streams.append(stream)
            return stream

    class Transport(httpx.AsyncBaseTransport):
        calls = 0

        async def handle_async_request(self, request):
            self.calls += 1
            body = b"".join([chunk async for chunk in request.stream])
            assert b"raw-audio" in body
            if self.calls == 1:
                raise failure("unavailable")
            return httpx.Response(200, json={"segments": [{"start": 3601, "end": 3602, "speaker": "speaker_0"}]})

    async def run():
        store = Store()
        meeting = await store.create_meeting(title="long", audio=b"raw-audio", source_filename="long.wav", content_type="audio/wav")
        await store.claim_next_upload()
        await store.mark_preprocessed(meeting.id, normalized_audio_path=None, duration_seconds=3900)
        transcript = [{"start": 3601, "end": 3602, "text": "retained"}]
        await store.mark_transcribed(meeting.id, transcript_segments=transcript)
        client = HTTPDiarizationClient(transport=Transport())
        try:
            worker = MeetingWorker(store, diarization_client=client)
            assert not await worker.process_one()
            assert (await store.get_meeting(meeting.id)).status == MeetingJobStatus.DIARIZING
            assert await worker.process_one()
            result = await store.get_meeting(meeting.id)
            assert result.status == MeetingJobStatus.ALIGNING
            assert result.transcript_segments == transcript
            assert len(store.streams) == 2
            assert all(stream.closed for stream in store.streams)
        finally:
            await client.aclose()
    asyncio.run(run())
