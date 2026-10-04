"""Semantic router service (shadow use): ModernBERT-base x3, fine 18-route taxonomy, ONNX FP32 on CPU, argmax.

POST /route {"text": "..."} -> {route, confidence, member_routes, top3, latency_ms}.
It decides nothing about execution: no tool, consent or auth logic lives here. Nothing is logged or stored.
"""

import os
import time
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import onnxruntime as ort
from fastapi import FastAPI
from pydantic import BaseModel, Field
from transformers import AutoTokenizer

ROUTES = [
    "none", "unsupported", "calendar.read", "email.read", "email.draft", "tasks.read", "tasks.capture", "tasks.complete",
    "memory.read", "memory.capture", "memory.forget", "rag.query", "web.search", "coding.status", "coding.usage",
    "robot.standby", "robot.resume", "clock.read",
]
MODELS = os.environ.get("MODELS_DIR", "/app/models")
THREADS = int(os.environ.get("ORT_THREADS", "3"))

tokenizer = AutoTokenizer.from_pretrained(f"{MODELS}/tokenizer")
sessions = []
for seed in range(3):
    options = ort.SessionOptions()
    options.intra_op_num_threads = THREADS
    options.inter_op_num_threads = 1
    sessions.append(ort.InferenceSession(f"{MODELS}/onnx_fp32_s{seed}.onnx", options, providers=["CPUExecutionProvider"]))
pool = ThreadPoolExecutor(max_workers=len(sessions))


def route(text: str) -> dict:
    started = time.perf_counter()
    encoded = tokenizer([text], return_tensors="np", truncation=True, max_length=64)
    feed = {"input_ids": encoded["input_ids"].astype(np.int64), "attention_mask": encoded["attention_mask"].astype(np.int64)}
    probs = []
    for logits in pool.map(lambda s: s.run(None, feed)[0][0], sessions):
        p = np.exp(logits - logits.max())
        probs.append(p / p.sum())
    mean = np.mean(probs, 0)
    top = np.argsort(-mean)[:3]
    return {
        "route": ROUTES[int(mean.argmax())],
        "confidence": round(float(mean.max()), 4),
        "member_routes": [ROUTES[int(np.argmax(p))] for p in probs],
        "top3": [(ROUTES[int(i)], round(float(mean[i]), 3)) for i in top],
        "latency_ms": round(1000 * (time.perf_counter() - started), 1),
    }


route("warm-up")
app = FastAPI(title="semantic-router (shadow)")


class RouteRequest(BaseModel):
    text: str = Field(min_length=1, max_length=2000)


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "models": len(sessions), "routes": len(ROUTES)}


@app.post("/route")
def do_route(request: RouteRequest) -> dict:
    return route(request.text)
