"""Phase 15: "Call Reachy" — real WebRTC audio between the web/PWA client
(clients/web-pwa/) and reachy-hub, synchronized with reachy-embodiment's
listening/thinking/speaking state, per docs/plan.md's Phase 15 row and
§11's critical scenario ("Private WebRTC phone call -> Reachy
listening/thinking/speaking animation with no room audio").

Turn-taking is push-to-talk, not continuous VAD: the browser holds a
"control" RTCDataChannel alongside the audio track and sends
`{"type": "start_talk"}` / `{"type": "end_talk"}` when the user presses and
releases a hold-to-talk button. This reuses the existing non-streaming
STT/TTS pipeline (stt.py/tts.py, both whole-utterance-in/out) exactly as
Phase 8's POST /voice/turn does, rather than requiring new real-time
streaming ASR infrastructure this codebase doesn't have. Audio only ever
flows over the peer connection to the browser — reachy-embodiment has no
speaker output wired to hardware at all (no physical Reachy in this
environment, same as every other phase), so "no room audio" holds by
construction, not by an extra guard.

Every transcript that reaches handle_inbound_message here carries
`InputModality.VOICE` (ADR 0011) — spoken audio over a WebRTC call is
exactly as untrusted for destructive-action consent as spoken audio over
`/voice/turn`; the transport changing doesn't change that rule.

Known limitation: a browser on a different machine than the Docker host
would need reachy-hub's WebRTC media (UDP/ICE) reachable directly — Caddy
only proxies the signaling HTTP POST, not the RTP media itself, and
Docker's default bridge networking NATs the container's ICE host
candidates. Untested in this environment (no real browser, no second
machine); live verification here uses a real (non-browser) aiortc Python
client, itself a genuine WebRTC peer, not a mock.

Phase 16/ADR 0013 (remote telepresence) adds a second, unrelated
negotiation path in this same module: `negotiate_telepresence` wires a
video-only, hub-to-browser `CameraPollTrack` sourced from
reachy-embodiment's `GET /camera/frame` (polled MJPEG-over-HTTP, wrapped
into a real WebRTC video track — same "real transport, simulated content"
precedent as `SilentAudioTrack`/`WavPlaybackTrack` above, since no
physical camera exists in this environment either). It's a separate
function/route from `negotiate_call` on purpose: telepresence carries no
reasoning and no companion-core involvement at all, and sharing one
endpoint for two purposes would need offer-shape sniffing for no benefit.
"""

from __future__ import annotations

import asyncio
import contextlib
import io
import json
import logging
import wave
from collections.abc import Awaitable, Callable
from fractions import Fraction

import av
import numpy as np
from aiortc import RTCPeerConnection, RTCSessionDescription
from aiortc.mediastreams import AudioFrame, MediaStreamTrack
from PIL import Image

from shared.models.embodiment import Behaviour

log = logging.getLogger(__name__)

_FRAME_MS = 20
_SILENCE_SAMPLE_RATE = 48000
_SAMPLES_PER_SILENT_FRAME = _SILENCE_SAMPLE_RATE * _FRAME_MS // 1000
# Camera frames are polled over HTTP, not pushed — 5fps is plenty to prove
# a live feed (see CameraPollTrack) without hammering reachy-embodiment.
_CAMERA_FPS = 5

TranscribeFn = Callable[[bytes], str]
SynthesizeFn = Callable[[str], bytes]
TriggerBehaviourFn = Callable[[Behaviour], Awaitable[None]]
# (text, input_modality) -> reply text — app.py's closure adapts this to an
# actual InboundMessage/handle_inbound_message call, so this module never
# needs to import app.py's InboundMessage (would be circular).
AskAgentFn = Callable[[str], Awaitable[str]]
# Returns a single JPEG-encoded frame — app.py's closure adapts this to an
# EmbodimentClient.get_camera_frame() call.
FrameSourceFn = Callable[[], Awaitable[bytes]]


def encode_wav(chunks: list[bytes], *, sample_rate: int, channels: int, sampwidth: int = 2) -> bytes:
    """Pure PCM-chunks-to-WAV-bytes encoding — no aiortc/audio-hardware
    involved, so this is unit-testable directly."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(sampwidth)
        wf.setframerate(sample_rate)
        wf.writeframes(b"".join(chunks))
    return buf.getvalue()


class CallTurnHandler:
    """The turn-taking orchestration, deliberately separated from the
    aiortc/SDP/media-framing plumbing below so it's testable with fakes —
    same split as email/workflow.py (pure orchestration) vs.
    email/sender.py (real transport)."""

    def __init__(
        self,
        *,
        transcribe: TranscribeFn,
        synthesize: SynthesizeFn,
        trigger_behaviour: TriggerBehaviourFn,
        ask_agent: AskAgentFn,
    ) -> None:
        self._transcribe = transcribe
        self._synthesize = synthesize
        self._trigger_behaviour = trigger_behaviour
        self._ask_agent = ask_agent

    async def on_start_talk(self) -> None:
        await self._trigger_behaviour(Behaviour.LISTENING)

    async def process_utterance(self, wav_bytes: bytes) -> bytes:
        """Runs a full turn: STT -> (thinking) -> agent -> (speaking) ->
        TTS. Returns the reply WAV bytes to play back over the call."""
        transcript = await asyncio.to_thread(self._transcribe, wav_bytes)
        if not transcript:
            reply_text = "Sorry, I didn't catch that."
        else:
            await self._trigger_behaviour(Behaviour.THINKING)
            reply_text = await self._ask_agent(transcript)

        await self._trigger_behaviour(Behaviour.SPEAKING)
        return await asyncio.to_thread(self._synthesize, reply_text)

    async def on_reply_finished(self) -> None:
        await self._trigger_behaviour(Behaviour.WAITING)


class SilentAudioTrack(MediaStreamTrack):
    """Placeholder outbound track: the SDP needs a sendrecv audio m-line
    from the moment the call connects, before there's any reply to play —
    real WebRTC audio tracks can't be added mid-call, only replaced
    (RTCRtpSender.replaceTrack), so this is what's replaced once a reply
    is ready."""

    kind = "audio"

    def __init__(self) -> None:
        super().__init__()
        self._pts = 0

    async def recv(self) -> AudioFrame:
        await asyncio.sleep(_FRAME_MS / 1000)
        frame = AudioFrame(format="s16", layout="mono", samples=_SAMPLES_PER_SILENT_FRAME)
        for plane in frame.planes:
            plane.update(bytes(plane.buffer_size))
        frame.sample_rate = _SILENCE_SAMPLE_RATE
        frame.pts = self._pts
        frame.time_base = Fraction(1, _SILENCE_SAMPLE_RATE)
        self._pts += _SAMPLES_PER_SILENT_FRAME
        return frame


class WavPlaybackTrack(MediaStreamTrack):
    """Plays a single WAV (assumed 16-bit PCM, from tts.py's espeak-ng
    output — often 22050Hz mono, not 48kHz) out to the peer, frame by
    frame, then pads with silence and calls on_complete exactly once.

    Always resampled to _SILENCE_SAMPLE_RATE/mono on construction, matching
    SilentAudioTrack's format exactly: aiortc's RTCRtpSender sets up its
    Opus encoder/resampler from the *first* frame it ever sees and doesn't
    re-adapt it when `replaceTrack` swaps in a track with a different
    sample rate — confirmed live, that mismatch raised "Frame does not
    match AudioResampler setup" deep inside aiortc's encode path the first
    time this was tried without resampling here.
    """

    kind = "audio"

    def __init__(self, wav_bytes: bytes, *, on_complete: Callable[[], None] | None = None) -> None:
        super().__init__()
        with io.BytesIO(wav_bytes) as buf, wave.open(buf, "rb") as wf:
            if wf.getsampwidth() != 2:
                raise ValueError(f"WavPlaybackTrack only supports 16-bit PCM, got sampwidth={wf.getsampwidth()}")
            source_rate = wf.getframerate()
            channels = wf.getnchannels()
            raw = wf.readframes(wf.getnframes())

        array = np.frombuffer(raw, dtype="<i2").reshape(-1, channels).T.copy()
        source_frame = av.AudioFrame.from_ndarray(array, format="s16", layout="mono" if channels == 1 else "stereo")
        source_frame.sample_rate = source_rate
        resampler = av.AudioResampler(format="s16", layout="mono", rate=_SILENCE_SAMPLE_RATE)
        resampled = [*resampler.resample(source_frame), *resampler.resample(None)]  # None flushes remaining samples
        self._pcm = b"".join(bytes(f.planes[0]) for f in resampled)

        self._sample_rate = _SILENCE_SAMPLE_RATE
        self._samples_per_frame = _SAMPLES_PER_SILENT_FRAME
        self._bytes_per_sample_frame = 2  # 16-bit mono
        self._offset = 0
        self._pts = 0
        self._on_complete = on_complete
        self._completed = False

    async def recv(self) -> AudioFrame:
        await asyncio.sleep(_FRAME_MS / 1000)
        frame_bytes = self._samples_per_frame * self._bytes_per_sample_frame
        chunk = self._pcm[self._offset : self._offset + frame_bytes]
        self._offset += frame_bytes
        if len(chunk) < frame_bytes:
            chunk = chunk + bytes(frame_bytes - len(chunk))
            if not self._completed:
                self._completed = True
                if self._on_complete is not None:
                    self._on_complete()

        frame = AudioFrame(format="s16", layout="mono", samples=self._samples_per_frame)
        frame.planes[0].update(chunk)
        frame.sample_rate = self._sample_rate
        frame.pts = self._pts
        frame.time_base = Fraction(1, self._sample_rate)
        self._pts += self._samples_per_frame
        return frame


class RecordingBuffer:
    """Accumulates raw PCM chunks from incoming aiortc AudioFrames while
    `armed`, and produces WAV bytes on demand. Kept separate from the
    aiortc track-reading loop so the PCM-conversion step
    (`frame.to_ndarray()` -> interleaved int16 bytes) is exercised by the
    same real frames aiortc actually decodes, while `encode_wav` above
    stays testable without aiortc at all."""

    def __init__(self) -> None:
        self.armed = False
        self._chunks: list[bytes] = []
        self.sample_rate: int | None = None
        self.channels: int | None = None

    def add_frame(self, frame: AudioFrame) -> None:
        if not self.armed:
            return
        if self.sample_rate is None:
            self.sample_rate = frame.sample_rate
            self.channels = len(frame.layout.channels)
        array = frame.to_ndarray()  # shape (channels, samples), dtype matches frame format
        interleaved = array.reshape(self.channels, -1).T.astype(np.int16, copy=False)
        self._chunks.append(interleaved.tobytes())

    def take_wav(self) -> bytes | None:
        if not self._chunks or self.sample_rate is None or self.channels is None:
            self._chunks = []
            return None
        wav_bytes = encode_wav(self._chunks, sample_rate=self.sample_rate, channels=self.channels)
        self._chunks = []
        return wav_bytes


async def negotiate_call(
    *, offer_sdp: str, offer_type: str, turn_handler: CallTurnHandler
) -> tuple[str, str, RTCPeerConnection]:
    """Wires a real aiortc RTCPeerConnection: receives the browser's audio
    track (buffered into a RecordingBuffer, armed/disarmed by the
    "control" data channel's start_talk/end_talk messages), and an
    outbound track that starts silent and gets replaceTrack'd with a real
    TTS reply once a turn completes. Returns the SDP answer to send back,
    plus the live PeerConnection (caller owns its lifecycle/cleanup)."""
    pc = RTCPeerConnection()
    recorder = RecordingBuffer()
    audio_sender = pc.addTrack(SilentAudioTrack())

    @pc.on("track")
    def on_track(track: MediaStreamTrack) -> None:
        if track.kind != "audio":
            return

        async def read_loop() -> None:
            try:
                while True:
                    frame = await track.recv()
                    recorder.add_frame(frame)
            except Exception:
                log.debug("webrtc call audio track ended", exc_info=True)

        asyncio.ensure_future(read_loop())

    async def finish_turn(channel) -> None:
        await turn_handler.on_reply_finished()
        with contextlib.suppress(Exception):
            channel.send(json.dumps({"type": "status", "state": "waiting"}))

    @pc.on("datachannel")
    def on_datachannel(channel) -> None:
        @channel.on("message")
        def on_message(message: str) -> None:
            try:
                payload = json.loads(message)
            except (TypeError, ValueError):
                return

            async def handle() -> None:
                msg_type = payload.get("type")
                if msg_type == "start_talk":
                    recorder.armed = True
                    await turn_handler.on_start_talk()
                    channel.send(json.dumps({"type": "status", "state": "listening"}))
                elif msg_type == "end_talk":
                    recorder.armed = False
                    wav_bytes = recorder.take_wav()
                    if wav_bytes is None:
                        channel.send(json.dumps({"type": "status", "state": "waiting"}))
                        return
                    channel.send(json.dumps({"type": "status", "state": "thinking"}))
                    reply_wav = await turn_handler.process_utterance(wav_bytes)
                    channel.send(json.dumps({"type": "status", "state": "speaking"}))
                    audio_sender.replaceTrack(
                        WavPlaybackTrack(
                            reply_wav, on_complete=lambda: asyncio.ensure_future(finish_turn(channel))
                        )
                    )

            asyncio.ensure_future(handle())

    offer = RTCSessionDescription(sdp=offer_sdp, type=offer_type)
    await pc.setRemoteDescription(offer)
    answer = await pc.createAnswer()
    await pc.setLocalDescription(answer)

    return pc.localDescription.sdp, pc.localDescription.type, pc


class CameraPollTrack(MediaStreamTrack):
    """Video track for Phase 16/ADR 0013 telepresence: polls `frame_source`
    (reachy-embodiment's GET /camera/frame) at _CAMERA_FPS and re-emits each
    JPEG as a real WebRTC video frame. Not a proper push-driven video
    stream — the same MJPEG-over-HTTP pattern many real IP cameras use at
    the transport level — but a genuine `av.VideoFrame` the browser decodes
    like any other video track."""

    kind = "video"

    def __init__(self, frame_source: FrameSourceFn) -> None:
        super().__init__()
        self._frame_source = frame_source
        self._pts = 0

    async def recv(self) -> av.VideoFrame:
        await asyncio.sleep(1 / _CAMERA_FPS)
        jpeg_bytes = await self._frame_source()
        image = Image.open(io.BytesIO(jpeg_bytes)).convert("RGB")
        frame = av.VideoFrame.from_image(image)
        frame.pts = self._pts
        frame.time_base = Fraction(1, _CAMERA_FPS)
        self._pts += 1
        return frame


async def negotiate_telepresence(
    *, offer_sdp: str, offer_type: str, frame_source: FrameSourceFn
) -> tuple[str, str, RTCPeerConnection]:
    """Wires a video-only peer connection: reachy-hub only ever sends the
    robot's camera feed here, the browser has nothing to send back — no
    audio track, no data channel, no companion-core involvement at all
    (that's what makes this satisfy "without Companion Core")."""
    pc = RTCPeerConnection()
    pc.addTrack(CameraPollTrack(frame_source))

    offer = RTCSessionDescription(sdp=offer_sdp, type=offer_type)
    await pc.setRemoteDescription(offer)
    answer = await pc.createAnswer()
    await pc.setLocalDescription(answer)

    return pc.localDescription.sdp, pc.localDescription.type, pc
