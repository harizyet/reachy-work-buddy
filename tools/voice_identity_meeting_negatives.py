"""Stage 2 of tools/voice_identity_meeting_negatives.sh: runs INSIDE a throw-away container from the core image (read-only mount of the meeting audio).

Decodes one meeting recording, cuts clean single-speaker windows from the diarization turns (no overlap with any other speaker, 2.5 s or longer, at most 6 s each, evenly
spread, at most MAX_PER_LABEL per label), embeds each window through the speaker service and scores it against the owner's template. Writes SCORES ONLY, per
anonymous diarization label: no audio, no embeddings, no text, no names. Nothing is stored on the hub.
"""
import io
import json
import os
import sys
import wave
from pathlib import Path

import av
import httpx
import numpy as np

MEETING = os.environ["MEETING_ID"]
MAX_PER_LABEL = int(os.environ.get("MAX_PER_LABEL", "40"))
tmpl = np.asarray(json.loads(Path("/work/template.json").read_text())["template"])
segments = json.loads(Path("/work/segments.json").read_text())

path = os.path.join("/data/meeting-audio", MEETING)
file = min(os.listdir(path))
samples, resampler = [], av.AudioResampler(format="s16", layout="mono", rate=16000)
with av.open(os.path.join(path, file)) as container:
    for frame in container.decode(audio=0):
        for f in resampler.resample(frame):
            samples.append(f.to_ndarray().reshape(-1))
audio = np.concatenate(samples).astype("<i2")
print("decoded", round(len(audio) / 16000), "s", file=sys.stderr)


def overlaps(a, b, c, d):
    return a < d and c < b


by_label = {}
for s in segments:
    by_label.setdefault(s["speaker"], []).append((s["start"], s["end"]))
windows = {}
for label, turns in by_label.items():
    others = [t for other, ts in by_label.items() if other != label for t in ts]
    clean = []
    for start, end in turns:
        if end - start < 2.5 or any(overlaps(start, end, o0, o1) for o0, o1 in others):
            continue
        clean.append((start + 0.2, min(start + 0.2 + 6.0, end - 0.2)))
    step = max(1, len(clean) // MAX_PER_LABEL)
    windows[label] = clean[::step][:MAX_PER_LABEL]

http = httpx.Client(timeout=60)
out = {}
for label, spans in sorted(windows.items()):
    scores = []
    for start, end in spans:
        clip = audio[int(start * 16000):int(end * 16000)]
        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(16000)
            w.writeframes(clip.tobytes())
        r = http.post("http://speaker:8012/embed", files={"file": ("a.wav", buffer.getvalue(), "audio/wav")})
        if r.status_code != 200 or r.json()["speech_s"] < 1.5:
            continue
        v = np.asarray(r.json()["embedding"])
        scores.append(float(v @ tmpl / (np.linalg.norm(v) * np.linalg.norm(tmpl))))
    out[label] = {"turns_total": len(by_label[label]), "clean_windows": len(spans), "scored": len(scores), "scores": scores}
    print(label, len(scores), "scored", file=sys.stderr)
Path("/work/scores.json").write_text(json.dumps(out))
