"""Unit tests for the parts of webrtc.py that don't need a real peer
connection: encode_wav (pure), CallTurnHandler (pure orchestration, fakes
for transcribe/synthesize/trigger_behaviour/ask_agent), and the two
MediaStreamTrack implementations (exercised via their real .recv(), just
without an actual RTCPeerConnection driving them) plus RecordingBuffer
against real av.AudioFrame objects. A real end-to-end peer-connection
negotiation is covered separately by a live aiortc-client test (see
deploy/homelab/README.md), not unit tests.
"""

import asyncio
import wave
from io import BytesIO

import av
import numpy as np
from PIL import Image
from reachy_hub.webrtc import (
    CallTurnHandler,
    CameraPollTrack,
    RecordingBuffer,
    SilentAudioTrack,
    WavPlaybackTrack,
    encode_wav,
)

from shared.models.embodiment import Behaviour


def _make_wav(samples: list[int], *, sample_rate: int = 8000, channels: int = 1, sampwidth: int = 2) -> bytes:
    pcm = np.array(samples, dtype="<i2").tobytes()
    return encode_wav([pcm], sample_rate=sample_rate, channels=channels, sampwidth=sampwidth)


def test_encode_wav_roundtrip() -> None:
    wav_bytes = _make_wav([1, 2, 3, 4], sample_rate=16000, channels=1)
    with wave.open(BytesIO(wav_bytes), "rb") as wf:
        assert wf.getframerate() == 16000
        assert wf.getnchannels() == 1
        assert wf.getsampwidth() == 2
        assert np.frombuffer(wf.readframes(wf.getnframes()), dtype="<i2").tolist() == [1, 2, 3, 4]


def test_call_turn_handler_full_turn_triggers_behaviours_in_order() -> None:
    async def run() -> None:
        behaviours: list[Behaviour] = []

        async def trigger_behaviour(b: Behaviour) -> None:
            behaviours.append(b)

        async def ask_agent(transcript: str) -> str:
            assert transcript == "what's next"
            return "Team Standup at 10am"

        handler = CallTurnHandler(
            transcribe=lambda wav: "what's next",
            synthesize=lambda text: _make_wav([0]),
            trigger_behaviour=trigger_behaviour,
            ask_agent=ask_agent,
        )

        await handler.on_start_talk()
        reply_wav = await handler.process_utterance(b"fake-wav-bytes")
        await handler.on_reply_finished()

        assert behaviours == [Behaviour.LISTENING, Behaviour.THINKING, Behaviour.SPEAKING, Behaviour.WAITING]
        assert reply_wav == _make_wav([0])

    asyncio.run(run())


def test_call_turn_handler_empty_transcript_skips_agent_but_still_speaks() -> None:
    async def run() -> None:
        behaviours: list[Behaviour] = []
        agent_calls: list[str] = []

        async def trigger_behaviour(b: Behaviour) -> None:
            behaviours.append(b)

        async def ask_agent(transcript: str) -> str:
            agent_calls.append(transcript)
            return "should not be reached"

        synthesized_texts: list[str] = []

        def synthesize(text: str) -> bytes:
            synthesized_texts.append(text)
            return _make_wav([0])

        handler = CallTurnHandler(
            transcribe=lambda wav: "",  # nothing understood
            synthesize=synthesize,
            trigger_behaviour=trigger_behaviour,
            ask_agent=ask_agent,
        )

        await handler.process_utterance(b"silence")

        assert agent_calls == []  # never asked the agent anything
        assert Behaviour.THINKING not in behaviours  # no thinking without a real question
        assert behaviours == [Behaviour.SPEAKING]
        assert synthesized_texts == ["Sorry, I didn't catch that."]

    asyncio.run(run())


def test_silent_audio_track_produces_zeroed_frames() -> None:
    async def run() -> None:
        track = SilentAudioTrack()
        frame = await track.recv()
        assert frame.sample_rate == 48000
        array = frame.to_ndarray()
        assert (array == 0).all()

        second = await track.recv()
        assert second.pts > frame.pts  # timestamps actually advance

    asyncio.run(run())


def test_wav_playback_track_plays_content_then_pads_silence_and_completes_once() -> None:
    async def run() -> None:
        # Sourced already at 48kHz mono (WavPlaybackTrack's fixed output
        # format) so the resampling step it always runs is a no-op here —
        # keeps this test's exact-sample-value assertions meaningful
        # without also needing to model resampling math. 100 samples is
        # under one 20ms frame, so the very first recv() should already
        # contain the tail padding and fire on_complete.
        wav_bytes = _make_wav(list(range(1, 101)), sample_rate=48000, channels=1)
        completions = 0

        def on_complete() -> None:
            nonlocal completions
            completions += 1

        track = WavPlaybackTrack(wav_bytes, on_complete=on_complete)
        frame = await track.recv()
        array = frame.to_ndarray()
        assert array[0, :100].tolist() == list(range(1, 101))
        assert (array[0, 100:] == 0).all()  # padded with silence
        assert completions == 1

        # Further reads are pure silence, and on_complete never fires again.
        again = await track.recv()
        assert (again.to_ndarray() == 0).all()
        assert completions == 1

    asyncio.run(run())


def test_wav_playback_track_rejects_non_16_bit_audio() -> None:
    # encode_wav always writes 16-bit, so force an 8-bit WAV directly to
    # exercise the guard.
    buf = BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(1)
        wf.setframerate(8000)
        wf.writeframes(bytes([10, 20, 30]))
    try:
        WavPlaybackTrack(buf.getvalue())
        raise AssertionError("expected ValueError")
    except ValueError:
        pass


def _audio_frame(samples: list[int], *, sample_rate: int = 8000) -> av.AudioFrame:
    array = np.array([samples], dtype="int16")
    frame = av.AudioFrame.from_ndarray(array, format="s16", layout="mono")
    frame.sample_rate = sample_rate
    return frame


def test_recording_buffer_ignores_frames_while_disarmed() -> None:
    buf = RecordingBuffer()
    buf.add_frame(_audio_frame([1, 2, 3]))  # not armed yet
    assert buf.take_wav() is None


def test_recording_buffer_captures_frames_while_armed() -> None:
    buf = RecordingBuffer()
    buf.armed = True
    buf.add_frame(_audio_frame([1, 2, 3], sample_rate=8000))
    buf.add_frame(_audio_frame([4, 5], sample_rate=8000))

    wav_bytes = buf.take_wav()
    assert wav_bytes is not None
    with wave.open(BytesIO(wav_bytes), "rb") as wf:
        assert wf.getframerate() == 8000
        assert wf.getnchannels() == 1
        samples = np.frombuffer(wf.readframes(wf.getnframes()), dtype="<i2").tolist()
        assert samples == [1, 2, 3, 4, 5]


def test_recording_buffer_stops_capturing_once_disarmed() -> None:
    buf = RecordingBuffer()
    buf.armed = True
    buf.add_frame(_audio_frame([1, 2]))
    buf.armed = False
    buf.add_frame(_audio_frame([99, 99]))  # must not be captured

    wav_bytes = buf.take_wav()
    with wave.open(BytesIO(wav_bytes), "rb") as wf:
        samples = np.frombuffer(wf.readframes(wf.getnframes()), dtype="<i2").tolist()
        assert samples == [1, 2]


def _jpeg_bytes(color: tuple[int, int, int]) -> bytes:
    image = Image.new("RGB", (16, 12), color=color)
    buf = BytesIO()
    image.save(buf, format="JPEG")
    return buf.getvalue()


def test_camera_poll_track_wraps_polled_jpegs_as_video_frames() -> None:
    async def run() -> None:
        served = [_jpeg_bytes((255, 0, 0)), _jpeg_bytes((0, 255, 0))]

        async def frame_source() -> bytes:
            return served.pop(0)

        track = CameraPollTrack(frame_source)

        first = await track.recv()
        assert isinstance(first, av.VideoFrame)
        assert (first.width, first.height) == (16, 12)

        second = await track.recv()
        assert second.pts > first.pts  # timestamps actually advance

    asyncio.run(run())


def test_recording_buffer_take_wav_resets_for_next_utterance() -> None:
    buf = RecordingBuffer()
    buf.armed = True
    buf.add_frame(_audio_frame([1, 2]))
    first = buf.take_wav()
    assert first is not None

    buf.add_frame(_audio_frame([3, 4]))
    second = buf.take_wav()
    with wave.open(BytesIO(second), "rb") as wf:
        samples = np.frombuffer(wf.readframes(wf.getnframes()), dtype="<i2").tolist()
        assert samples == [3, 4]  # not [1, 2, 3, 4] — the first take cleared the buffer
