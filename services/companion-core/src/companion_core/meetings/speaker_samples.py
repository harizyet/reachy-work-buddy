"""Phase 54: which stretches of the recording to play so the owner can tell who a diarization label is.

Deterministic and derived only from what the speech services already produced: the diarization spans, the transcript
text and the silent-recording check. No audio is read, no embedding is computed and nothing is stored: a sample is a
time range of the existing recording, played through the existing authenticated recording route. The same meeting
always gives the same samples."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

MIN_SECONDS = 2.0  # a shorter stretch is too little to recognise a voice from
IDEAL_SECONDS = 8.0
MAX_SECONDS = 10.0
PRIMARY = 3
ALTERNATES = 3
MERGE_GAP = 0.6  # same-speaker spans closer than this are one turn
MAX_OVERLAP = 0.05  # a window with more than this share of another speaker talking is not clean
SPREAD_SECONDS = 30.0  # prefer samples this far apart so one noisy stretch cannot be all of them
MIN_TEXT_DENSITY = 1.0  # transcript characters per second below which the stretch is probably not clear speech


@dataclass(frozen=True)
class Sample:
    start: float
    end: float
    quality: str  # "good" or "low"
    notes: tuple[str, ...] = ()
    text: str = ""

    def view(self) -> dict[str, Any]:
        return {"start": round(self.start, 2), "end": round(self.end, 2), "quality": self.quality, "notes": list(self.notes), "text": self.text}


@dataclass
class SpeakerSamples:
    label: str
    seconds: float
    samples: list[Sample] = field(default_factory=list)
    alternates: list[Sample] = field(default_factory=list)
    reason: str | None = None  # why there is nothing (or little) to play

    def view(self) -> dict[str, Any]:
        return {"label": self.label, "seconds": round(self.seconds, 1), "samples": [s.view() for s in self.samples],
                "alternates": [s.view() for s in self.alternates], "reason": self.reason}


def _overlap(a0: float, a1: float, b0: float, b1: float) -> float:
    return max(0.0, min(a1, b1) - max(a0, b0))


def _covered(start: float, end: float, spans: list[tuple[float, float]]) -> float:
    """Seconds of [start, end] inside the union of `spans` (assumed sorted by start)."""
    total, cursor = 0.0, start
    for s, e in spans:
        if e <= cursor:
            continue
        if s >= end:
            break
        lo, hi = max(s, cursor), min(e, end)
        if hi > lo:
            total += hi - lo
            cursor = hi
    return total


def _union(spans: list[tuple[float, float]]) -> list[tuple[float, float]]:
    out: list[tuple[float, float]] = []
    for s, e in sorted(spans):
        if out and s <= out[-1][1]:
            out[-1] = (out[-1][0], max(out[-1][1], e))
        else:
            out.append((s, e))
    return out


def _text_in(transcript: list[dict[str, Any]], start: float, end: float) -> tuple[float, str]:
    """Characters of transcript text per second of [start, end], and the text, counting each segment by its share inside."""
    chars, parts, best = 0.0, [], (0.0, "")
    for seg in transcript:
        s, e = float(seg.get("start", 0)), float(seg.get("end", 0))
        inside = _overlap(s, e, start, end)
        if inside <= 0 or e <= s:
            continue
        text = " ".join(str(seg.get("text", "")).split())
        chars += len(text) * inside / (e - s)
        if inside / (e - s) >= 0.5 and text:
            parts.append(text)
        if text and inside > best[0]:
            best = (inside, text)
    return chars / max(end - start, 0.001), (" ".join(parts) or best[1])[:160]


def _gap_spans(audio_gaps: dict[str, Any] | None) -> list[tuple[float, float]]:
    return _union([(float(g["start"]), float(g["end"])) for g in (audio_gaps or {}).get("spans", []) if "start" in g and "end" in g])


def select(
    diarization: list[dict[str, Any]] | None,
    transcript: list[dict[str, Any]] | None,
    audio_gaps: dict[str, Any] | None = None,
    duration: float | None = None,
) -> list[SpeakerSamples]:
    """Samples for every diarization label, in order of first appearance."""
    spans = [(float(s["start"]), float(s["end"]), str(s["speaker"])) for s in diarization or [] if s.get("speaker") and float(s.get("end", 0)) > float(s.get("start", 0))]
    order: dict[str, None] = {}
    for _, _, who in sorted(spans):
        order.setdefault(who, None)
    gaps = _gap_spans(audio_gaps)
    text = sorted(transcript or [], key=lambda t: float(t.get("start", 0)))
    result = []
    for label in order:
        mine = _union([(s, e) for s, e, who in spans if who == label])
        others = _union([(s, e) for s, e, who in spans if who != label])
        total = sum(e - s for s, e in mine)
        result.append(_for_speaker(label, mine, others, gaps, text, total, duration))
    return result


def _turns(mine: list[tuple[float, float]], others: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """Runs of this speaker's speech, merged across short pauses when nobody else spoke in between."""
    turns: list[tuple[float, float]] = []
    for s, e in mine:
        if turns and s - turns[-1][1] <= MERGE_GAP and _covered(turns[-1][1], s, others) == 0:
            turns[-1] = (turns[-1][0], e)
        else:
            turns.append((s, e))
    return turns


def _windows(turns: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """Candidate windows: a whole turn up to MAX_SECONDS, or sliding windows over a longer one."""
    out = []
    for s, e in turns:
        if e - s < MIN_SECONDS:
            continue
        if e - s <= MAX_SECONDS:
            out.append((s, e))
            continue
        step, start = IDEAL_SECONDS / 2, s
        while start + IDEAL_SECONDS <= e + 1e-9:
            out.append((start, start + IDEAL_SECONDS))
            start += step
    return out


def _for_speaker(label: str, mine: list[tuple[float, float]], others: list[tuple[float, float]], gaps: list[tuple[float, float]],
                 transcript: list[dict[str, Any]], total: float, duration: float | None) -> SpeakerSamples:
    out = SpeakerSamples(label=label, seconds=total)
    scored: list[tuple[float, Sample]] = []
    for s, e in _windows(_turns(mine, others)):
        if duration is not None:
            e = min(e, duration)
            if e - s < MIN_SECONDS:
                continue
        length = e - s
        crossing = _covered(s, e, others) / length
        silent = _covered(s, e, gaps) / length
        density, snippet = _text_in(transcript, s, e)
        notes = []
        if length < 5:
            notes.append("short")
        if crossing > MAX_OVERLAP:
            notes.append("another speaker talks over part of this")
        if silent > 0:
            notes.append("part of this has no recorded audio")
        if density < MIN_TEXT_DENSITY:
            notes.append("little speech was recognised here")
        score = 4 * min(length, MAX_SECONDS) / MAX_SECONDS - 12 * crossing - 10 * silent + min(density, 15.0) / 15.0 * 2
        if density < MIN_TEXT_DENSITY:
            score -= 3
        scored.append((score, Sample(start=s, end=e, quality="low" if notes and (crossing > MAX_OVERLAP or silent > 0 or density < MIN_TEXT_DENSITY or length < 3) else "good", notes=tuple(notes), text=snippet)))
    if not scored:
        out.reason = "Too little uninterrupted speech from this speaker to play a sample." if total else "No speech was detected for this speaker."
        return out
    # Best first; the start time breaks ties so the choice never depends on input order.
    scored.sort(key=lambda t: (-t[0], t[1].start))
    picked: list[Sample] = []
    # Clean and spread out first, then clean but close together, and only then unclear ones: a poor stretch never displaces a good one.
    for clean_only, spread in ((True, True), (True, False), (False, False)):
        if not clean_only and picked:
            break  # unclear stretches are offered only when there is nothing clear to play
        for _, sample in scored:
            if len(picked) == PRIMARY + ALTERNATES:
                break
            if sample in picked or (clean_only and sample.quality != "good"):
                continue
            if any(_overlap(sample.start, sample.end, p.start, p.end) > 0 for p in picked):
                continue
            if spread and any(abs(sample.start - p.start) < SPREAD_SECONDS for p in picked):
                continue
            picked.append(sample)
    # The first three, played in the order they occur, are the main samples; the rest are offered when one is unclear.
    out.samples = sorted(picked[:PRIMARY], key=lambda x: x.start)
    out.alternates = sorted(picked[PRIMARY:], key=lambda x: x.start)
    if all(s.quality == "low" for s in out.samples):
        out.reason = "Only unclear stretches were found for this speaker; check the transcript before naming them."
    return out
