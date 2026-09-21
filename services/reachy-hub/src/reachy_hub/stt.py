"""Speech-to-text provider interface + a faster-whisper implementation.

Per docs/plan.md §8 ("STT | Homelab initially"), speech-to-text runs here
in reachy-hub, not on reachy-embodiment — unlike Jarvis's monolithic
on-device design (see docs/jarvis-baseline.md's audio/stt.py notes, which
this adapts: local faster-whisper, int8 compute for CPU-friendly
inference). reachy-embodiment keeps its own Silero VAD (audio/vad.py) for
the low-latency, locally-colocated concern of live barge-in detection —
a different problem from transcribing a complete utterance after the fact.

vad_filter=True below uses faster-whisper's own bundled Silero VAD to trim
leading/trailing silence from a submitted clip. This is not a duplicate of
reachy-embodiment's VAD: that one is for real-time streaming signals fed to
the presence loop (not wired to live hardware yet — see
reachy-embodiment/src/reachy_embodiment/audio/vad.py); this one just cleans
up whatever complete audio clip STT is asked to transcribe.
"""

from __future__ import annotations

import io
from typing import Protocol


class SpeechToText(Protocol):
    def transcribe(self, wav_bytes: bytes) -> str: ...


class FasterWhisperSTT:
    def __init__(self, model_size: str = "base.en") -> None:
        from faster_whisper import WhisperModel

        self._model = WhisperModel(model_size, compute_type="int8")

    def transcribe(self, wav_bytes: bytes) -> str:
        segments, _info = self._model.transcribe(io.BytesIO(wav_bytes), vad_filter=True)
        return " ".join(segment.text.strip() for segment in segments).strip()
