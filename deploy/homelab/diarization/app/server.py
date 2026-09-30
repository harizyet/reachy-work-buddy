"""HTTP service: Nemotron-3-Diarization with the network step on OpenVINO (Intel GPU by default)."""
import io
import os
import secrets
import tempfile
import threading
import time

import numpy as np
import soundfile as sf
from fastapi import Depends, FastAPI, File, Header, HTTPException, UploadFile
from scipy.signal import resample_poly

ONNX_PATH = os.environ.get("ONNX_PATH", "/data/sortformer_step.onnx")
MODEL_ID = os.environ.get("MODEL_ID", "nvidia/Nemotron-3-Diarization")
OV_DEVICE = os.environ.get("OV_DEVICE", "GPU")
OV_PRECISION = os.environ.get("OV_PRECISION") or None  # e.g. f32; default lets the plugin pick (fp16 on GPU)
# ADR 0025's "authenticated service-to-service calls": unset (the default
# on a homelab with only Docker-internal reachability) means no check, same
# as before this was added. Set SPEECH_SERVICE_TOKEN to require it — the
# companion-core clients (meetings/speech_clients.py) send the same value.
SPEECH_SERVICE_TOKEN = os.environ.get("SPEECH_SERVICE_TOKEN") or None

app = FastAPI(title="nemotron-3-diarization")


def require_service_token(x_reachy_speech_token: str | None = Header(default=None)) -> None:
    if SPEECH_SERVICE_TOKEN and not (
        x_reachy_speech_token and secrets.compare_digest(x_reachy_speech_token, SPEECH_SERVICE_TOKEN)
    ):
        raise HTTPException(401, "Invalid or missing service token")
S = {"diarizer": None, "status": "loading", "load_seconds": None, "device": None}
lock = threading.Lock()


def load():
    t0 = time.perf_counter()
    try:
        from export_onnx import export
        from nemo.collections.asr.models import SortformerEncLabelModel
        from ov_diarizer import OVDiarizer
        model = SortformerEncLabelModel.from_pretrained(MODEL_ID).eval().cpu()
        if not os.path.exists(ONNX_PATH):
            S["status"] = "exporting onnx (first start only)"
            export(model, ONNX_PATH)
        S["status"] = "compiling for " + OV_DEVICE
        S["diarizer"] = OVDiarizer(model, ONNX_PATH, OV_DEVICE, OV_PRECISION)
        import openvino as ov
        S["device"] = ov.Core().get_property(OV_DEVICE, "FULL_DEVICE_NAME")
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
    body = {k: S[k] for k in ("status", "device", "load_seconds")}
    if S["status"] != "ready":
        raise HTTPException(503 if not S["status"].startswith("failed") else 500, detail=body)
    return body


@app.post("/diarize", dependencies=[Depends(require_service_token)])
def diarize(file: UploadFile = File(...)):  # noqa: B008
    """Upload wav/flac/ogg audio (any rate/channels). Returns speaker segments in seconds."""
    if S["status"] != "ready":
        raise HTTPException(503, detail=S["status"])
    try:
        audio, sr = sf.read(io.BytesIO(file.file.read()), dtype="float32", always_2d=True)
    except Exception as e:  # soundfile raises several exception types for a bad/unreadable file
        raise HTTPException(400, detail=f"could not decode audio (wav/flac/ogg only): {e}") from e
    audio = audio.mean(axis=1)
    if sr != 16000:
        audio = resample_poly(audio, 16000, sr).astype(np.float32)
    dur = len(audio) / 16000
    with tempfile.NamedTemporaryFile(suffix=".wav") as tmp, lock:
        sf.write(tmp.name, audio, 16000)
        t = time.perf_counter()
        raw = S["diarizer"].diarize([tmp.name], batch_size=1)[0]
        took = time.perf_counter() - t
    segs = sorted(({"start": float(a), "end": float(b), "speaker": s}
                   for a, b, s in (r.split() for r in raw)), key=lambda x: (x["start"], x["speaker"]))
    return {"duration_s": round(dur, 2), "process_s": round(took, 3), "rtf": round(took / dur, 4) if dur else None,
            "num_speakers": len({s["speaker"] for s in segs}), "segments": segs}
