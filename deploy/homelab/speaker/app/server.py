"""HTTP service: speaker embeddings (Phase 32A.V, ADR 0041, ADR 0025's sidecar pattern).

Stateless on purpose. It turns one short mono 16 kHz PCM16 WAV into a speaker
embedding plus audio-quality facts, and keeps neither: no audio is written, no
embedding is cached or logged. Profiles, thresholds, consent, encryption and
every decision live in reachy-hub; this service never learns whose voice it heard.
CPU-first: SpeechBrain ECAPA-TDNN (the model benchmarked in Phase 25a.1), pinned to a
Hugging Face revision so the embedding space is reproducible. Same shared-token
check as the other speech sidecars (SPEECH_SERVICE_TOKEN).
"""
import io
import math
import os
import secrets
import threading
import time
import wave

import numpy as np
from fastapi import Depends, FastAPI, File, Header, HTTPException, UploadFile

SAMPLE_RATE = 16000
MAX_AUDIO_BYTES = 2 * 1024 * 1024
MIN_SAMPLES = SAMPLE_RATE // 2  # shorter than half a second cannot be embedded sensibly
MODEL_REPO = os.environ.get("SPEAKER_MODEL_REPO", "speechbrain/spkrec-ecapa-voxceleb")
MODEL_REVISION = os.environ.get("SPEAKER_MODEL_REVISION", "0f99f2d0ebe89ac095bcc5903c4dd8f72b367286")
MODEL_VERSION = f"{MODEL_REPO}@{MODEL_REVISION[:8]}"
THREADS = int(os.environ.get("SPEAKER_TORCH_THREADS", "2"))
SPEECH_SERVICE_TOKEN = os.environ.get("SPEECH_SERVICE_TOKEN") or None

app = FastAPI(title="speaker-embedding")
S = {"embedder": None, "status": "loading", "load_seconds": None}
lock = threading.Lock()


def require_service_token(x_reachy_speech_token: str | None = Header(default=None)) -> None:
    if SPEECH_SERVICE_TOKEN and not (
        x_reachy_speech_token and secrets.compare_digest(x_reachy_speech_token, SPEECH_SERVICE_TOKEN)
    ):
        raise HTTPException(401, "Invalid or missing service token")


class SpeechBrainEmbedder:
    def __init__(self):
        import torch
        from huggingface_hub import snapshot_download
        from speechbrain.inference.speaker import EncoderClassifier

        torch.set_num_threads(THREADS)
        self._torch = torch
        path = snapshot_download(MODEL_REPO, revision=MODEL_REVISION)
        self._model = EncoderClassifier.from_hparams(source=path, savedir=path, run_opts={"device": "cpu"})

    def embed(self, samples: np.ndarray) -> list[float]:
        with self._torch.inference_mode():
            tensor = self._torch.from_numpy(samples).unsqueeze(0)
            return self._model.encode_batch(tensor).squeeze().cpu().numpy().astype(float).tolist()


def load():
    t0 = time.perf_counter()
    try:
        S["embedder"] = SpeechBrainEmbedder()
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
    body = {"status": S["status"], "model": MODEL_VERSION, "load_seconds": S["load_seconds"], "device": "cpu"}
    if S["status"] != "ready":
        raise HTTPException(503 if not S["status"].startswith("failed") else 500, detail=body)
    return body


def decode_wav(data: bytes) -> np.ndarray:
    """Mono 16 kHz PCM16 only: the single phone capture format (ADR 0041). No resampling
    here, so a client that sends something else finds out instead of getting a quietly worse embedding."""
    try:
        with wave.open(io.BytesIO(data), "rb") as wav:
            if wav.getnchannels() != 1 or wav.getsampwidth() != 2 or wav.getframerate() != SAMPLE_RATE:
                raise HTTPException(422, "audio must be mono 16 kHz 16-bit PCM WAV")
            frames = wav.readframes(wav.getnframes())
    except (wave.Error, EOFError):
        raise HTTPException(422, "audio is not a readable WAV file") from None
    # A truncated upload can end mid-sample; drop the stray byte rather than fail on it.
    return np.frombuffer(frames[: len(frames) // 2 * 2], dtype="<i2").astype(np.float32) / 32768.0


def quality(samples: np.ndarray) -> dict:
    """Plain signal facts the hub turns into a usable/unusable decision. An energy gate, not a
    speech detector: it cannot tell a voice from a loud fan, which is why the hub also needs the
    embedding score and, later, measured conditions."""
    frame = int(SAMPLE_RATE * 0.03)
    count = len(samples) // frame
    if count == 0:
        return {"duration_s": 0.0, "speech_s": 0.0, "rms_dbfs": -120.0, "clipping_fraction": 0.0}
    frames = samples[: count * frame].reshape(count, frame)
    rms = np.sqrt((frames ** 2).mean(axis=1) + 1e-12)
    db = 20 * np.log10(rms)
    gate = max(-50.0, float(db.max()) - 30.0)
    speech_frames = int((db > gate).sum()) if float(db.max()) > -50.0 else 0
    overall = float(np.sqrt((samples ** 2).mean() + 1e-12))
    return {
        "duration_s": round(len(samples) / SAMPLE_RATE, 3),
        "speech_s": round(speech_frames * 0.03, 3),
        "rms_dbfs": round(20 * math.log10(overall), 1),
        "clipping_fraction": round(float((np.abs(samples) >= 0.999).mean()), 5),
    }


@app.post("/embed", dependencies=[Depends(require_service_token)])
def embed(file: UploadFile = File(...)):  # noqa: B008
    if S["status"] != "ready":
        raise HTTPException(503, detail=S["status"])
    data = file.file.read(MAX_AUDIO_BYTES + 1)
    if not data:
        raise HTTPException(400, "empty audio file")
    if len(data) > MAX_AUDIO_BYTES:
        raise HTTPException(413, "audio too large")
    samples = decode_wav(data)
    facts = quality(samples)
    if len(samples) < MIN_SAMPLES:
        raise HTTPException(422, "audio shorter than half a second")
    if not lock.acquire(blocking=False):
        raise HTTPException(503, detail="embedding busy", headers={"Retry-After": "2"})
    try:
        t = time.perf_counter()
        vector = S["embedder"].embed(samples)
        took = time.perf_counter() - t
    finally:
        lock.release()
    return {"model_version": MODEL_VERSION, "embedding": vector, "process_s": round(took, 3), **facts}
