"""Stretches of a recording where the phone captured no audio.

Android hands a recording app digital silence (exact zeros) while another app holds the microphone or the system
restricts a background app, and the recording clock keeps running. Speech-to-text then bridges the gap, so a transcript
line can claim seconds that hold no sound. A real microphone never produces exact zeros, so a run of them is a reliable
sign of lost audio, unlike a quiet room."""

from __future__ import annotations

from typing import Any, BinaryIO

import numpy as np

RATE = 8000  # speech-to-text is not involved, so a low rate keeps the check cheap
WINDOW_S = 0.5
SILENT_RMS = 2.0  # int16 units; decoded digital silence is 0, a live microphone's noise floor is far above this
MIN_SPAN_S = 5.0  # shorter pauses are ordinary
LINE_OVERLAP = 0.5  # a transcript line is flagged when at least this fraction of it lies in a gap


def levels(stream: BinaryIO) -> list[float]:
    """RMS level of each half-second window of the recording."""
    import av

    window = int(RATE * WINDOW_S)
    resampler = av.AudioResampler(format="s16", layout="mono", rate=RATE)
    out: list[float] = []
    pending = np.zeros(0, dtype=np.float64)

    def drain(frames) -> None:
        nonlocal pending
        for frame in frames:
            pending = np.concatenate([pending, frame.to_ndarray().reshape(-1).astype(np.float64)])
        whole = len(pending) // window * window
        if whole:
            blocks = pending[:whole].reshape(-1, window)
            out.extend(float(v) for v in np.sqrt((blocks**2).mean(axis=1)))
            pending = pending[whole:]

    with av.open(stream) as container:
        for frame in container.decode(audio=0):
            drain(resampler.resample(frame))
        drain(resampler.resample(None))
    if len(pending):
        out.append(float(np.sqrt((pending**2).mean())))
    return out


def spans_from_levels(window_levels: list[float]) -> list[dict[str, float]]:
    spans: list[dict[str, float]] = []
    start: int | None = None
    for index, level in enumerate([*window_levels, float("inf")]):
        if level <= SILENT_RMS and start is None:
            start = index
        elif level > SILENT_RMS and start is not None:
            begin, end = start * WINDOW_S, index * WINDOW_S
            if end - begin >= MIN_SPAN_S:
                spans.append({"start": round(begin, 1), "end": round(end, 1)})
            start = None
    return spans


def segments_in_gaps(segments: list[dict[str, Any]], spans: list[dict[str, float]]) -> list[int]:
    """Indexes of transcript segments that mostly lie inside a silent stretch."""
    flagged = []
    for index, segment in enumerate(segments):
        begin, end = float(segment.get("start", 0)), float(segment.get("end", 0))
        length = max(end - begin, 0.001)
        overlap = sum(max(0.0, min(end, s["end"]) - max(begin, s["start"])) for s in spans)
        if overlap / length >= LINE_OVERLAP:
            flagged.append(index)
    return flagged


def analyse(stream: BinaryIO, segments: list[dict[str, Any]]) -> dict[str, Any]:
    spans = spans_from_levels(levels(stream))
    return {"spans": spans, "segments": segments_in_gaps(segments, spans), "seconds": round(sum(s["end"] - s["start"] for s in spans), 1)}
