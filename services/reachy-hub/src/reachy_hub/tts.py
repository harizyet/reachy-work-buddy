"""Text-to-speech provider interface + local implementations.

Per docs/plan.md §8, TTS sits behind a pluggable provider interface. No
cloud TTS key is available, so the providers here are local engines: Piper
(neural, the deployed default when the image's voice model is configured)
and espeak-ng (the fallback without a model). A cloud provider implements
the same TextToSpeech protocol without any caller changing.
"""

from __future__ import annotations

import io
import os
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


class PiperTTS:
    """Local neural TTS (Piper). Replaced espeak as the deployed voice in
    Phase 24d after the owner found espeak too robotic on the real speaker.
    The ONNX voice loads once (about 1 s); a sentence then synthesizes in a
    fraction of its playback time on the homelab CPU."""

    def __init__(self, model_path: str) -> None:
        from piper import PiperVoice

        self._voice = PiperVoice.load(model_path)

    def synthesize(self, text: str) -> bytes:
        out = io.BytesIO()
        with wave.open(out, "wb") as wav:
            # Piper sets the format only when it emits audio, so empty text
            # would otherwise fail to produce a valid (silent) WAV.
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(self._voice.config.sample_rate)
            self._voice.synthesize_wav(text, wav, set_wav_format=False)
        return out.getvalue()


def default_tts() -> TextToSpeech:
    """Piper when a voice model is configured (the hub image sets one),
    otherwise espeak-ng for dev/test environments without the model."""
    model_path = os.environ.get("PIPER_VOICE_MODEL")
    return PiperTTS(model_path) if model_path else EspeakTTS()


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
