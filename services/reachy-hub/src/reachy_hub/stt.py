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
import os
from collections.abc import Sequence
from typing import Protocol

from shared.models.persona import DEFAULT_NAME


class SpeechToText(Protocol):
    def transcribe(self, wav_bytes: bytes, *, vocabulary: Sequence[str] = ()) -> str: ...


class FasterWhisperSTT:
    def __init__(self, model_size: str | None = None) -> None:
        from faster_whisper import WhisperModel

        # STT_MODEL is any faster-whisper model name. The owner chose to try
        # a larger one after the 24e physical run misheard "cold and the flu"
        # as "coil and the flue".
        self._model = WhisperModel(model_size or os.environ.get("STT_MODEL") or "base.en", compute_type="int8")

    def transcribe(self, wav_bytes: bytes, *, vocabulary: Sequence[str] = ()) -> str:
        # Phase 24e: bias recognition toward the robot's name, which 24d
        # heard as "Ricci"/"Richi", and the configured assistant name. An
        # initial prompt, not hotwords: on base.en, hotwords dropped final
        # punctuation, which the end-of-turn and search rules read.
        names = dict.fromkeys(w.strip() for w in (DEFAULT_NAME, *vocabulary) if w.strip())
        segments, _info = self._model.transcribe(
            io.BytesIO(wav_bytes), vad_filter=True, initial_prompt=f"Hello {' and '.join(names)}.",
        )
        return " ".join(segment.text.strip() for segment in segments).strip()
