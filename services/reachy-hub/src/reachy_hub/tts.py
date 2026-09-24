"""Text-to-speech provider interface + a local implementation.

Per docs/plan.md §8, TTS is "cloud initially" with a "pluggable provider
interface." No cloud TTS API key is available in this environment, so the
concrete provider here is a real local engine (espeak-ng) rather than a
stub — the same graceful-degradation-without-credentials approach Phase 7
used for Telegram. A cloud provider (e.g. ElevenLabs, per
docs/jarvis-baseline.md's reference) implements the same TextToSpeech
protocol and slots in later without any caller changing.
"""

from __future__ import annotations

import io
import subprocess
import wave
from typing import Protocol


class TextToSpeech(Protocol):
    def synthesize(self, text: str) -> bytes:
        """Returns WAV-encoded audio bytes."""
        ...


class EspeakTTS:
    """Wraps the espeak-ng CLI (not the shared library) for simplicity.

    `espeak-ng --stdout` writes a *streaming* WAV: its header carries a
    placeholder frame count (0x7fffffff), because it's written before the
    audio length is known. Anything trusting that header sees a ~13-hour
    clip — found in Phase 24c when the robot waited that long for "playback"
    to finish. The PCM is re-wrapped here with a correct header.
    """

    def __init__(self, binary: str = "espeak-ng", voice: str = "en-us") -> None:
        self._binary = binary
        self._voice = voice

    def synthesize(self, text: str) -> bytes:
        result = subprocess.run(
            [self._binary, "-v", self._voice, "--stdout", text],
            capture_output=True,
            check=True,
        )
        return _rewrap_wav(result.stdout)


def _rewrap_wav(streamed: bytes) -> bytes:
    with wave.open(io.BytesIO(streamed), "rb") as source:
        params = source.getparams()
        # readframes stops at the real end of data despite the bogus count.
        frames = source.readframes(source.getnframes())
    out = io.BytesIO()
    with wave.open(out, "wb") as target:
        target.setnchannels(params.nchannels)
        target.setsampwidth(params.sampwidth)
        target.setframerate(params.framerate)
        target.writeframes(frames)
    return out.getvalue()
