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

import subprocess
from typing import Protocol


class TextToSpeech(Protocol):
    def synthesize(self, text: str) -> bytes:
        """Returns WAV-encoded audio bytes."""
        ...


class EspeakTTS:
    """Wraps the espeak-ng CLI (not the shared library) for simplicity:
    `espeak-ng --stdout` writes a complete WAV file to stdout, no manual
    PCM/header handling needed.
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
        return result.stdout
