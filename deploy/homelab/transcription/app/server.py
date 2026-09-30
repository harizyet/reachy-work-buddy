"""HTTP service: long-form meeting transcription with faster-whisper
(Phase 27.2, ADR 0025 — docs/adr/0025-speech-inference-service.md).

Same faster-whisper library and int8-CPU-by-default shape as reachy-hub's
conversational `stt.py` (`FasterWhisperSTT`) — this is a separate process
on purpose, not a shared import: reachy-hub owns interactive voice
transport, this owns long-form meeting inference, and Companion Core must
never import either implementation directly (ADR 0001, reaffirmed by ADR
0025). Unlike reachy-hub's short-turn transcribe (a single concatenated
string, no timing), meetings need real per-segment start/end times, so
this exposes faster-whisper's own segment boundaries instead of joining
them into one string.

Response shape deliberately matches the sibling diarization sidecar's
`/diarize` (`deploy/homelab/diarization/app/server.py`): `{duration_s,
process_s, rtf, segments}` plus this service's own `language`.
"""
import os
import tempfile
import threading
import time

from fastapi import FastAPI, File, HTTPException, UploadFile

MODEL_SIZE = os.environ.get("MEETING_STT_MODEL", "small.en")
COMPUTE_TYPE = os.environ.get("MEETING_STT_COMPUTE_TYPE", "int8")
DEVICE = os.environ.get("MEETING_STT_DEVICE", "cpu")

app = FastAPI(title="meeting-transcription")
S = {"model": None, "status": "loading", "load_seconds": None, "device": DEVICE}
lock = threading.Lock()


def load():
    t0 = time.perf_counter()
    try:
        from faster_whisper import WhisperModel

        S["model"] = WhisperModel(MODEL_SIZE, device=DEVICE, compute_type=COMPUTE_TYPE)
        S["status"] = "ready"
    except Exception as e:  # keep the process up so /health reports why
        S["status"] = f"failed: {e!r}"
        raise
    finally:
        S["load_seconds"] = round(time.perf_counter() - t0, 1)


@app.on_event("startup")
def _startup():
    threading.Thread(target=load, daemon=True).start()


@app.get("/health")
def health():
    body = {"status": S["status"], "device": S["device"], "load_seconds": S["load_seconds"], "model": MODEL_SIZE}
    if S["status"] != "ready":
        raise HTTPException(503 if not S["status"].startswith("failed") else 500, detail=body)
    return body


@app.post("/transcribe")
def transcribe(file: UploadFile = File(...)):  # noqa: B008
    """Upload wav/flac/mp3/m4a/etc audio (faster-whisper decodes via
    bundled PyAV, no system ffmpeg required). Returns timestamped
    segments in seconds."""
    if S["status"] != "ready":
        raise HTTPException(503, detail=S["status"])
    data = file.file.read()
    if not data:
        raise HTTPException(400, detail="empty audio file")
    suffix = os.path.splitext(file.filename or "")[1] or ".wav"
    with tempfile.NamedTemporaryFile(suffix=suffix) as tmp, lock:
        tmp.write(data)
        tmp.flush()
        t = time.perf_counter()
        try:
            segments, info = S["model"].transcribe(tmp.name, vad_filter=True)
            segs = [{"start": float(s.start), "end": float(s.end), "text": s.text.strip()} for s in segments]
        except Exception as e:
            raise HTTPException(400, detail=f"could not decode/transcribe audio: {e}") from e
        took = time.perf_counter() - t
    dur = info.duration if info else None
    return {
        "duration_s": round(dur, 2) if dur else None,
        "process_s": round(took, 3),
        "rtf": round(took / dur, 4) if dur else None,
        "language": info.language if info else None,
        "segments": segs,
    }
