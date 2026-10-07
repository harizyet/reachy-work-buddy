"""Alignment (Phase 27.4): attribute each transcript segment to the speaker who was talking.

Transcription gives words with times and no speaker; diarization gives speaker time spans and no words. This matches
them. Each transcript segment gets the speaker with the most overlapping time (summed over all of that speaker's spans
in the segment). A segment that overlaps nobody takes the nearest span within MAX_GAP_S, else no speaker.

The result is index-aligned with `transcript_segments` (same length and order), so accepted corrections, which are keyed
by segment index, stay valid. The raw transcript and diarization are never changed."""

from __future__ import annotations

from typing import Any

MAX_GAP_S = 1.5


def align(transcript: list[dict[str, Any]], diarization: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    spans = [
        (float(s.get("start", 0)), float(s.get("end", 0)), str(s["speaker"]))
        for s in diarization or []
        if s.get("speaker") is not None
    ]
    aligned = []
    for segment in transcript:
        start = float(segment.get("start", 0))
        end = max(float(segment.get("end", start)), start)
        aligned.append({
            "start": start, "end": end, "text": str(segment.get("text", "")).strip(),
            "speaker": _speaker(spans, start, end),
        })
    return aligned


def _speaker(spans: list[tuple[float, float, str]], start: float, end: float) -> str | None:
    totals: dict[str, float] = {}
    for span_start, span_end, label in spans:
        overlap = min(end, span_end) - max(start, span_start)
        if overlap > 0:
            totals[label] = totals.get(label, 0.0) + overlap
        elif end == start and span_start <= start < span_end:  # an instant: whoever is speaking at that moment
            totals[label] = totals.get(label, 0.0) + 1e-6
    if totals:
        return max(totals, key=lambda label: totals[label])
    nearest = min(
        ((max(span_start - end, start - span_end, 0.0), label) for span_start, span_end, label in spans),
        default=None,
    )
    return nearest[1] if nearest and nearest[0] <= MAX_GAP_S else None
