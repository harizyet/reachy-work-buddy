"""Voice Activity Detection using Silero VAD.

Adapted from Jarvis's audio/vad.py (see docs/jarvis-baseline.md): the
`silero-vad` pip package's `VADIterator` for streaming detection, fixed
512-sample (32ms) chunks at 16kHz — a hard requirement of the Silero model,
not a design choice.

reachy-embodiment (not reachy-hub) owns this, unlike STT/TTS (see
docs/plan.md §8: "STT | Homelab initially") — VAD's job here is real-time,
low-latency barge-in/presence-loop signalling co-located with the
microphone, a genuinely different problem from transcribing a complete
utterance after the fact (which reachy-hub's stt.py does, using faster-
whisper's own bundled VAD filter for that unrelated purpose).

Phase 24c wires this into the robot conversation loop (voice.py's
UtteranceSegmenter) to delimit turns inside an owner-started session. It
decides only where an utterance ends, never whether capture is allowed.
The presence loop still has no vad_energy input.
"""

from __future__ import annotations

import numpy as np
import torch

SAMPLE_RATE = 16000
CHUNK_SAMPLES = 512  # exactly 32ms at 16kHz — required by Silero


class VoiceActivityDetector:
    def __init__(
        self, threshold: float = 0.5, sample_rate: int = SAMPLE_RATE, *, min_silence_duration_ms: int = 100
    ) -> None:
        if sample_rate != SAMPLE_RATE:
            raise ValueError("Silero VAD requires 16kHz audio")

        from silero_vad import VADIterator, load_silero_vad

        torch.set_num_threads(1)  # small model; threading overhead hurts
        self._model = load_silero_vad()
        self._iterator = VADIterator(
            self._model,
            threshold=threshold,
            sampling_rate=sample_rate,
            min_silence_duration_ms=min_silence_duration_ms,
        )

    def reset(self) -> None:
        self._iterator.reset_states()

    def process_chunk(self, chunk: np.ndarray) -> dict[str, int] | None:
        """chunk: exactly CHUNK_SAMPLES samples. Returns {"start": sample}
        or {"end": sample} when this chunk crosses a speech boundary, else
        None."""
        if len(chunk) != CHUNK_SAMPLES:
            raise ValueError(f"expected exactly {CHUNK_SAMPLES} samples, got {len(chunk)}")
        tensor = torch.from_numpy(chunk.astype(np.float32))
        return self._iterator(tensor, return_seconds=False)

    def extract_speech_segments(self, samples: np.ndarray) -> list[tuple[int, int]]:
        """Non-streaming convenience built on process_chunk: run a
        complete buffer through and return [(start_sample, end_sample), ...]
        for each detected speech region. Used to prove real Silero VAD
        detection against a complete recording without needing a live
        stream (see tests)."""
        self.reset()
        segments: list[tuple[int, int]] = []
        current_start: int | None = None
        n_chunks = len(samples) // CHUNK_SAMPLES

        for i in range(n_chunks):
            chunk = samples[i * CHUNK_SAMPLES : (i + 1) * CHUNK_SAMPLES]
            result = self.process_chunk(chunk)
            if result and "start" in result:
                current_start = result["start"]
            elif result and "end" in result and current_start is not None:
                segments.append((current_start, result["end"]))
                current_start = None

        if current_start is not None:
            segments.append((current_start, n_chunks * CHUNK_SAMPLES))

        return segments
