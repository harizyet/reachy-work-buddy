# ruff: noqa: BLE001
"""Phase 32A.V automated synthetic-audio validation (functional checks and synthetic-only measurements).

Runs a frozen corpus made by tools/voice_identity_synthetic_corpus.py (Reachy's own Piper and espeak-ng) through the REAL pipeline: the hub's real faster-whisper recogniser,
the real speaker service (SpeechBrain ECAPA), and the hub's real /voice-identity routes in-process, backed by an ISOLATED PostgreSQL (migrated to head with core's own
migrations), a throw-away key file and a throw-away owner id. It never touches the homelab database, keys or any real owner's profile.

WHAT THIS IS: functional pass/fail checks (does the pipeline behave, fail safely, stay available) and measurements on machine-generated voices.
WHAT THIS IS NOT: biometric accuracy. Generated voices are not independent human speakers, there is no microphone, room or handling, and replay here is a digital file
re-submission, not a physical replay attack. Nothing in the output is a real-world FAR/FRR, and thresholds used for the "verified" branch are TEST-ONLY.

    SYNTH_PG_URL=postgresql://postgres:t@127.0.0.1:55477/postgres SIDECAR_URL=http://127.0.0.1:18012 \\
        python tools/voice_identity_synthetic_validation.py CORPUS_DIR [--regen CORPUS_DIR2] --out report.json
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import io
import json
import math
import os
import platform
import re
import statistics
import sys
import time
import wave
from collections import defaultdict
from pathlib import Path

import numpy as np
from scipy import signal

TEST_OWNER = "synthetic-test-owner"
TEST_ACCEPT, TEST_UNCERTAIN = 0.60, 0.40   # TEST-ONLY, fixed before the run; not a proposal for production
CLIENT = {"X-Reachy-Client-Kind": "android", "X-Reachy-Client-Id": "synthetic-harness", "X-Reachy-Device-Id": "synthetic"}
CSRF = {"X-Reachy-CSRF": "1"}


# ---- audio helpers ----------------------------------------------------------------------------------------

def read_wav(path_or_bytes) -> tuple[np.ndarray, int]:
    src = io.BytesIO(path_or_bytes) if isinstance(path_or_bytes, bytes) else str(path_or_bytes)
    with wave.open(src) as w:
        x = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2").astype(np.float64) / 32768.0
        return x, w.getframerate()


def to_wav(x: np.ndarray, rate: int = 16000) -> bytes:
    out = io.BytesIO()
    with wave.open(out, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(rate)
        w.writeframes((np.clip(x, -1, 1) * 32767).astype("<i2").tobytes())
    return out.getvalue()


def resample(x: np.ndarray, src: int, dst: int) -> np.ndarray:
    if src == dst:
        return x
    g = math.gcd(src, dst)
    return signal.resample_poly(x, dst // g, src // g)


def phone_format(path: Path) -> tuple[bytes, float]:
    """The format the phone sends: mono 16 kHz PCM16. Returns the WAV and the conversion time."""
    t = time.perf_counter()
    x, rate = read_wav(path)
    out = to_wav(resample(x, rate, 16000))
    return out, time.perf_counter() - t


def add_noise(x: np.ndarray, snr_db: float, rng: np.random.Generator) -> np.ndarray:
    p = float(np.mean(x ** 2)) + 1e-12
    noise = rng.standard_normal(len(x)) * math.sqrt(p / (10 ** (snr_db / 10)))
    return np.clip(x + noise, -1, 1)


def reverb(x: np.ndarray, rt60: float, rate: int, rng: np.random.Generator) -> np.ndarray:
    n = int(rate * rt60)
    t = np.arange(n) / rate
    rir = rng.standard_normal(n) * np.exp(-6.91 * t / rt60)   # exponential decay to -60 dB at RT60
    rir[0] = 1.0
    rir /= np.sqrt(np.sum(rir ** 2))
    y = signal.fftconvolve(x, rir)[: len(x)]
    return y / (np.max(np.abs(y)) + 1e-9) * np.max(np.abs(x))


def codec(x: np.ndarray, rate: int, name: str, bitrate: int | None) -> np.ndarray:
    """Encode then decode through PyAV (the same libraries the hub image carries), back to 16 kHz mono."""
    import av

    buf = io.BytesIO()
    fmt = {"mp3": "mp3", "aac": "adts", "opus": "ogg"}[name]
    codec_name = {"mp3": "libmp3lame", "aac": "aac", "opus": "libopus"}[name]
    enc_rate = 48000 if name == "opus" else rate
    pcm = resample(x, rate, enc_rate)
    with av.open(buf, "w", format=fmt) as container:
        stream = container.add_stream(codec_name, rate=enc_rate)
        stream.layout = "mono"
        if bitrate:
            stream.bit_rate = bitrate
        frame_size = 960 if name == "opus" else 1152
        for i in range(0, len(pcm) - frame_size + 1, frame_size):
            frame = av.AudioFrame.from_ndarray((pcm[i:i + frame_size] * 32767).astype("<i2")[None, :], format="s16", layout="mono")
            frame.sample_rate = enc_rate
            for packet in stream.encode(frame):
                container.mux(packet)
        for packet in stream.encode(None):
            container.mux(packet)
    buf.seek(0)
    out = []
    with av.open(buf) as container:
        resampler = av.AudioResampler(format="s16", layout="mono", rate=16000)
        for frame in container.decode(audio=0):
            for f in resampler.resample(frame):
                out.append(f.to_ndarray().reshape(-1))
    return np.concatenate(out).astype(np.float64) / 32768.0 if out else np.zeros(1)


def telephone(x: np.ndarray, rate: int) -> np.ndarray:
    y = resample(x, rate, 8000)
    sos = signal.butter(4, [300, 3400], btype="band", fs=8000, output="sos")
    return resample(signal.sosfilt(sos, y), 8000, rate)


# ---- metrics ----------------------------------------------------------------------------------------------

def wer(ref: str, hyp: str) -> tuple[int, int]:
    norm = lambda s: re.sub(r"[^a-z0-9' ]", "", s.lower().replace("-", " ")).split()
    r, h = norm(ref), norm(hyp)
    d = list(range(len(h) + 1))
    for i, rw in enumerate(r, 1):
        prev, d[0] = d[0], i
        for j, hw in enumerate(h, 1):
            prev, d[j] = d[j], min(d[j] + 1, d[j - 1] + 1, prev + (rw != hw))
    return d[len(h)], len(r)


def dist(values: list[float]) -> dict:
    if not values:
        return {"n": 0}
    v = sorted(values)
    q = lambda p: v[min(len(v) - 1, int(p * len(v)))]
    return {"n": len(v), "min": round(v[0], 4), "p05": round(q(0.05), 4), "p25": round(q(0.25), 4), "p50": round(statistics.median(v), 4),
            "p75": round(q(0.75), 4), "p95": round(q(0.95), 4), "max": round(v[-1], 4), "mean": round(statistics.fmean(v), 4)}


def lat(values: list[float]) -> dict:
    if not values:
        return {"n": 0}
    v = sorted(values)
    return {"n": len(v), "p50": round(statistics.median(v), 3), "p95": round(v[min(len(v) - 1, int(0.95 * len(v)))], 3), "max": round(v[-1], 3), "mean": round(statistics.fmean(v), 3)}


def auc(positives: list[float], negatives: list[float]) -> float | None:
    if not positives or not negatives:
        return None
    wins = sum((p > n) + 0.5 * (p == n) for p in positives for n in negatives)
    return round(wins / (len(positives) * len(negatives)), 4)


def dprime(a: list[float], b: list[float]) -> float | None:
    if len(a) < 2 or len(b) < 2:
        return None
    pooled = math.sqrt((statistics.variance(a) + statistics.variance(b)) / 2)
    return round((statistics.fmean(a) - statistics.fmean(b)) / pooled, 3) if pooled else None


def sweep(genuine: list[float], impostor: list[float]) -> list[dict]:
    rows = []
    for i in range(49):
        t = -0.2 + i * 0.025
        rows.append({"threshold": round(t, 3), "far": round(sum(s >= t for s in impostor) / len(impostor), 4) if impostor else None,
                     "frr": round(sum(s < t for s in genuine) / len(genuine), 4) if genuine else None})
    return rows


def cos(a, b) -> float:
    a, b = np.asarray(a), np.asarray(b)
    return float(a @ b / (np.linalg.norm(a) * np.linalg.norm(b)))


# ---- the run ------------------------------------------------------------------------------------------------

class Timed:
    """Wraps a component and records how long each call took, so endpoint latency can be split by stage."""

    def __init__(self, inner, method):
        self.inner, self.method, self.times = inner, method, []

    def __getattr__(self, name):
        return getattr(self.inner, name)


class TimedSTT:
    def __init__(self, inner):
        self.inner, self.times = inner, []

    def transcribe(self, wav_bytes, vocabulary=()):
        t = time.perf_counter()
        out = self.inner.transcribe(wav_bytes, vocabulary=vocabulary)
        self.times.append(time.perf_counter() - t)
        return out


class TimedEmbedder:
    def __init__(self, inner):
        self.inner, self.times = inner, []
        self.fail = False

    async def embed(self, wav):
        t = time.perf_counter()
        try:
            return await self.inner.embed(wav)
        finally:
            self.times.append(time.perf_counter() - t)

    async def healthy(self):
        return await self.inner.healthy()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("corpus"); ap.add_argument("--regen"); ap.add_argument("--out", required=True)
    ap.add_argument("--quick", action="store_true", help="fewer clips (development only)")
    args = ap.parse_args(argv)
    return run(args)


def run(args) -> int:
    import httpx
    import psycopg
    from companion_core.migrations.__main__ import upgrade
    from companion_core.secrets import Keyring as CoreKeyring
    from fastapi.testclient import TestClient
    from reachy_hub.app import create_app
    from reachy_hub.audit_log import InMemoryAuditLog
    from reachy_hub.enrollment_store import InMemoryEnrollmentStore
    from reachy_hub.keyring import Keyring
    from reachy_hub.notification_queue import InMemoryNotificationQueue
    from reachy_hub.robot_registry import InMemoryRobotRegistry
    from reachy_hub.session_store import InMemorySessionStore
    from reachy_hub.stt import FasterWhisperSTT
    from reachy_hub.user_store import InMemoryUserStore
    from reachy_hub.voice_identity import SidecarEmbeddingClient, VoiceIdentityConfig
    from reachy_hub.voice_profiles import (
        InMemoryVoiceProfileStore,
        PostgresVoiceProfileStore,
    )

    root = os.environ["SYNTH_PG_URL"]
    sidecar_url = os.environ.get("SIDECAR_URL", "http://127.0.0.1:18012")
    assert "55477" in root or os.environ.get("SYNTH_PG_ALLOW_OTHER") == "1", "refusing to run against an unexpected database"
    corpus = Path(args.corpus)
    manifest = json.loads((corpus / "manifest.json").read_text())
    rng = np.random.default_rng(32)
    report: dict = {"disclaimer": __doc__.split("WHAT THIS IS:")[1].split("\n\n")[0].strip(), "stages": {}, "failures": []}

    def fail(stage, what):
        """A FUNCTIONAL failure: the pipeline misbehaved (error, wrong state, unsafe outcome)."""
        report["failures"].append({"stage": stage, "case": what})

    def observe(stage, what):
        """A MEASUREMENT observation on synthetic audio (a mis-heard word, a confusable generated voice): not a pipeline fault and not biometric evidence."""
        report.setdefault("observations", []).append({"stage": stage, "case": what})

    # S0 environment -------------------------------------------------------------------------------------------
    import faster_whisper
    side = httpx.get(sidecar_url + "/health", timeout=10).json()
    report["environment"] = {"host_cpus": os.cpu_count(), "python": platform.python_version(), "faster_whisper": faster_whisper.__version__, "stt_model": "small.en (the hub's STT_MODEL)",
                             "speaker_model": side.get("model"), "speaker_device": side.get("device"), "corpus_manifest_sha256": hashlib.sha256((corpus / "manifest.json").read_bytes()).hexdigest(),
                             "voices": manifest["voices"], "clips": len(manifest["clips"]), "test_thresholds_TEST_ONLY": {"accept": TEST_ACCEPT, "uncertain": TEST_UNCERTAIN}}

    # S1 corpus integrity and reproducibility -----------------------------------------------------------------------
    bad = [c["file"] for c in manifest["clips"] if hashlib.sha256((corpus / c["file"]).read_bytes()).hexdigest() != c["sha256"]]
    s1 = {"clips_checked": len(manifest["clips"]), "hash_mismatches": bad}
    if bad:
        fail("S1", f"{len(bad)} clip(s) differ from the manifest")
    if args.regen:
        other = {c["file"]: c["sha256"] for c in json.loads((Path(args.regen) / "manifest.json").read_text())["clips"]}
        byv = defaultdict(lambda: [0, 0])
        for c in manifest["clips"]:
            byv[c["voice"]][1] += 1
            byv[c["voice"]][0] += other[c["file"]] == c["sha256"]
        s1["regeneration_byte_identical_by_voice"] = {v: f"{a}/{b}" for v, (a, b) in byv.items()}
    report["stages"]["S1_corpus"] = s1

    # prepare phone-format clips ----------------------------------------------------------------------------------
    clips = [c for i, c in enumerate(manifest["clips"]) if not args.quick or c["group"] == "enroll" or i % 5 == 0]
    phone, conv_times = {}, []
    for c in clips:
        phone[c["file"]], took = phone_format(corpus / c["file"])
        conv_times.append(took)

    # S3 STT accuracy (direct, the hub's recogniser) --------------------------------------------------------------
    stt = TimedSTT(FasterWhisperSTT("small.en"))
    stt.transcribe(phone[clips[0]["file"]])   # warm-up, not counted
    stt.times.clear()
    errs, words, by_voice, by_group, stt_rows, = 0, 0, defaultdict(lambda: [0, 0]), defaultdict(lambda: [0, 0]), []
    for c in clips:
        t = time.perf_counter()
        hyp = stt.transcribe(phone[c["file"]])
        took = time.perf_counter() - t
        e, n = wer(c["text"], hyp)
        errs += e; words += n
        by_voice[c["voice"]][0] += e; by_voice[c["voice"]][1] += n
        by_group[c["group"]][0] += e; by_group[c["group"]][1] += n
        stt_rows.append((c["seconds"], took))
        if e / max(n, 1) > 0.25:
            observe("S3", f"{c['file']}: WER {e}/{n}: heard {hyp!r}")
    report["stages"]["S3_stt"] = {"overall_wer": round(errs / words, 4), "words": words,
                                  "wer_by_voice": {v: round(a / max(b, 1), 4) for v, (a, b) in by_voice.items()},
                                  "wer_by_length_group": {g: round(a / max(b, 1), 4) for g, (a, b) in by_group.items()},
                                  "latency_s": lat([r[1] for r in stt_rows]), "real_time_factor_p50": round(statistics.median(r[1] / r[0] for r in stt_rows), 3)}

    # S4 speaker-embedding consistency and distinguishability (the speaker service directly) -------------------------
    client = httpx.Client(timeout=60)
    emb, svc_times, wall_times = {}, [], []

    def embed(wav: bytes):
        t = time.perf_counter()
        r = client.post(sidecar_url + "/embed", files={"file": ("a.wav", wav, "audio/wav")})
        wall_times.append(time.perf_counter() - t)
        r.raise_for_status()
        body = r.json()
        svc_times.append(body["process_s"])
        return body["embedding"]

    for c in clips:
        emb[c["file"]] = embed(phone[c["file"]])
    voices = sorted({c["voice"] for c in clips})
    by = defaultdict(list)
    for c in clips:
        by[c["voice"]].append(c)
    within, between, same_text = [], [], []
    for v in voices:
        for i, a in enumerate(by[v]):
            for b in by[v][i + 1:]:
                if a["group"] != "enroll" or b["group"] != "enroll" or True:
                    within.append(cos(emb[a["file"]], emb[b["file"]]))
    phrase_ids = sorted({c["phrase"] for c in clips})
    for p in phrase_ids:
        same = [c for c in clips if c["phrase"] == p]
        for i, a in enumerate(same):
            for b in same[i + 1:]:
                if a["voice"] != b["voice"]:
                    same_text.append(cos(emb[a["file"]], emb[b["file"]]))
    for i, va in enumerate(voices):
        for vb in voices[i + 1:]:
            for a in by[va]:
                for b in by[vb]:
                    if a["phrase"] != b["phrase"]:
                        between.append(cos(emb[a["file"]], emb[b["file"]]))
    # nearest-centroid identification of the voice from held-out phrases (centroid from the 8 enrolment phrases)
    cent = {v: np.mean([np.asarray(emb[c["file"]]) / np.linalg.norm(emb[c["file"]]) for c in by[v] if c["group"] == "enroll"], axis=0) for v in voices if any(c["group"] == "enroll" for c in by[v])}
    ident_ok = ident_n = 0
    confusions = defaultdict(int)
    for v in cent:
        for c in by[v]:
            if c["group"] == "enroll":
                continue
            best = max(cent, key=lambda u: cos(emb[c["file"]], cent[u]))
            ident_n += 1; ident_ok += best == v
            if best != v:
                confusions[f"{v} -> {best}"] += 1
                observe("S4", f"{c['file']} nearest to {best}")
    regen = {}
    if args.regen:
        for v in voices:
            for c in by[v]:
                if c["group"] == "enroll":
                    other_path = Path(args.regen) / c["file"]
                    if hashlib.sha256(other_path.read_bytes()).hexdigest() != c["sha256"]:
                        regen.setdefault(v, []).append(cos(emb[c["file"]], embed(phone_format(other_path)[0])))
    report["stages"]["S4_embeddings"] = {
        "same_voice_different_phrase_cosine": dist(within), "different_voice_cosine": dist(between), "same_text_different_voice_cosine": dist(same_text),
        "auc_same_vs_different_voice": auc(within, between), "d_prime_same_vs_different": dprime(within, between),
        "nearest_centroid_voice_identification": {"correct": ident_ok, "of": ident_n, "confusions": dict(confusions)},
        "regenerated_clip_same_text_cosine_by_voice": {v: dist(x) for v, x in regen.items()},
        "latency_s": {"service_embedding": lat(svc_times), "http_round_trip": lat(wall_times)},
        "note": "Voices are machine-generated; espeak variants share one synthesiser, so this measures how distinguishable the generated voices are to the model, not how well it separates people.",
    }

    # isolated database, key, hub ------------------------------------------------------------------------------------
    dbname = "synthetic_" + hashlib.sha1(os.urandom(8)).hexdigest()[:10]
    with psycopg.connect(root, autocommit=True) as conn:
        conn.execute(psycopg.sql.SQL("CREATE DATABASE {}").format(psycopg.sql.Identifier(dbname)))
    dsn = psycopg.conninfo.make_conninfo(root, dbname=dbname)
    upgrade(dsn, CoreKeyring("one", {"one": b"\x01" * 32}))
    with psycopg.connect(dsn) as conn:
        head = conn.execute("SELECT version_num FROM alembic_version").fetchone()[0]
        voice_rows = conn.execute("SELECT count(*) FROM voice_profiles").fetchone()[0]
    keyring = Keyring("synthetic", {"synthetic": os.urandom(32)})
    report["stages"]["S0_isolation"] = {"database": dbname, "schema_head": head, "voice_profiles_rows_at_start": voice_rows, "key": "random, in memory only, discarded at exit", "owner_id": TEST_OWNER,
                                        "note": "a separate PostgreSQL container; the homelab database, key files and any real owner profile are not reachable from this process"}
    os.environ["OWNER_USER_ID"] = TEST_OWNER

    store = None   # opened inside the app's own event loop below (a pool cannot be shared across loops)
    embedder = TimedEmbedder(SidecarEmbeddingClient(sidecar_url))
    users = InMemoryUserStore()
    asyncio.run(users.bootstrap("owner", "synthetic-password"))
    core = None
    try:
        from companion_core.app import create_app as create_core
        from companion_core.calendar.store import InMemoryCalendarStore
        from companion_core.consent.store import InMemoryConfirmationStore
        from companion_core.email.store import InMemoryEmailStore
        from companion_core.llm.store import (
            InMemoryLLMSettingsStore,
            InMemoryLLMUsageStore,
        )
        from companion_core.meetings.store import InMemoryMeetingStore
        from companion_core.memory.store import InMemoryMemoryStore
        from companion_core.persona.store import InMemoryPersonaStore
        from companion_core.planner.store import InMemoryPlannerStore
        from companion_core.rag.store import InMemoryDocumentStore
        from companion_core.tasks.store import InMemoryTaskStore
        from companion_core.websearch.store import InMemorySearchSettingsStore
        from reachy_hub.companion_core_client import CompanionCoreClient
        core = create_core(calendar_store=InMemoryCalendarStore(), task_store=InMemoryTaskStore(), planner_store=InMemoryPlannerStore(), meeting_store=InMemoryMeetingStore(),
                           run_meeting_worker_task=False, memory_store=InMemoryMemoryStore(), rag_store=InMemoryDocumentStore(), email_store=InMemoryEmailStore(),
                           confirmation_store=InMemoryConfirmationStore(), llm_settings_store=InMemoryLLMSettingsStore(), llm_usage_store=InMemoryLLMUsageStore(),
                           persona_store=InMemoryPersonaStore(), search_settings_store=InMemorySearchSettingsStore(), run_email_dispatch_task=False)
        core_client = CompanionCoreClient("http://companion-core", transport=httpx.ASGITransport(app=core))
    except Exception as exc:   # pragma: no cover - the conversation stage reports it
        core_client = None
        fail("setup", f"in-memory core unavailable: {exc!r}")

    timed_stt = TimedSTT(FasterWhisperSTT("small.en"))
    app = create_app(user_store=users, registry=InMemoryRobotRegistry(), session_store=InMemorySessionStore(), audit_log=InMemoryAuditLog(), notification_queue=InMemoryNotificationQueue(),
                     enrollment_store=InMemoryEnrollmentStore(), run_heartbeat_task=False, run_telegram_poll_task=False, run_coding_agent_notify_task=False, session_secret_key="synthetic-session-secret",
                     remote_ui_token="synthetic-token", stt=timed_stt, companion_core_client=core_client,
                     voice_identity_config=VoiceIdentityConfig(enabled=True, accept_threshold=None, uncertain_threshold=None, calibration_version="uncalibrated"),
                     voice_embedder=embedder, voice_profile_store=InMemoryVoiceProfileStore(), voice_keyring=keyring)
    service = app.state.voice_identity
    client_ctx = TestClient(app)
    http = client_ctx.__enter__()   # keeps one event loop alive for the app, the database pool and the HTTP client
    store = http.portal.call(PostgresVoiceProfileStore.connect, dsn)
    service.store = store
    assert http.post("/auth/login", json={"username": "owner", "password": "synthetic-password"}, headers=CSRF).status_code == 200

    def reauth():
        assert http.post("/owner-recognition/reauth", json={"password": "synthetic-password"}, headers=CSRF).status_code == 200

    def post(path, wav, utt=None, extra=None):
        h = {**CSRF, **CLIENT, "content-type": "audio/wav", **({"X-Reachy-Utterance-Id": utt} if utt else {}), **(extra or {})}
        t = time.perf_counter()
        r = http.post(path, content=wav, headers=h)
        return r, time.perf_counter() - t

    def score_of(utt):
        ev = service.ledger.current(TEST_OWNER, CLIENT["X-Reachy-Client-Id"], utt)
        return None if ev is None else ev.similarity_score

    verify_lat, utt_counter = [], [0]

    def verify(wav, label=""):
        utt_counter[0] += 1
        utt = f"u{utt_counter[0]}"
        r, took = post("/voice-identity/verify", wav, utt)
        verify_lat.append(took)
        body = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
        return r.status_code, body.get("state"), body.get("reasons", []), score_of(utt), took

    def enroll(voice):
        http.delete("/voice-identity/enrollment", headers=CSRF)
        for c in by[voice]:
            if c["group"] == "enroll":
                r, _ = post("/voice-identity/enrollment/samples", phone[c["file"]])
                assert r.status_code == 200 and r.json()["quality_ok"], (c["file"], r.text)
        reauth()
        r = http.post("/voice-identity/enrollment/commit", json={"consent": True}, headers={**CSRF, **CLIENT})
        assert r.status_code == 200, r.text
        return r.json()

    # S5 uncalibrated behaviour, then positive matching with TEST-ONLY thresholds -----------------------------------
    identities = [v for v in ("piper-lessac", "espeak-en-us", "espeak-us+m3") if v in by]
    s5 = {"identities": {}}
    first = identities[0]
    info = enroll(first)
    probe = next(c for c in by[first] if c["group"] == "medium")
    code, state, reasons, score, _ = verify(phone[probe["file"]])
    s5["default_uncalibrated_behaviour"] = {"http": code, "state": state, "reasons": reasons, "pass": code == 200 and state == "unavailable" and reasons == ["not_calibrated"],
                                            "profile_version": info["version"], "samples": info["sample_count"]}
    if not s5["default_uncalibrated_behaviour"]["pass"]:
        fail("S5", "uncalibrated hub did not report unavailable/not_calibrated")
    # from here the throw-away app instance has TEST-ONLY thresholds so the "verified" branch can be exercised
    from dataclasses import replace
    service.config = replace(service.config, accept_threshold=TEST_ACCEPT, uncertain_threshold=TEST_UNCERTAIN, calibration_version="TEST-ONLY-synthetic")
    all_scores = {}
    for ident in identities:
        if ident != first:
            http.delete("/voice-identity/profile", headers=CSRF) if (reauth() or True) else None
            enroll(ident)
        genuine, impostor, states = [], [], defaultdict(lambda: defaultdict(int))
        for c in clips:
            if c["group"] == "enroll" and c["voice"] == ident:
                continue   # the enrolment clips themselves are not trials
            code, state, reasons, score, _ = verify(phone[c["file"]])
            if code != 200 or state is None or score is None:
                fail("S5", f"{ident}: {c['file']} -> {code} {state} {reasons}")
                continue
            (genuine if c["voice"] == ident else impostor).append(score)
            states["genuine" if c["voice"] == ident else "impostor"][state] += 1
            if c["voice"] != ident:
                impostor_state = state
                if impostor_state == "verified":
                    observe("S5", f"{ident}: generated voice {c['voice']} accepted ({c['file']}, score {score:.3f}) at the TEST-ONLY threshold")
        all_scores[ident] = (genuine, impostor)
        s5["identities"][ident] = {"genuine_trials": len(genuine), "impostor_trials": len(impostor), "states_at_TEST_ONLY_thresholds": {k: dict(v) for k, v in states.items()},
                                   "genuine_score": dist(genuine), "impostor_score": dist(impostor), "auc_genuine_vs_impostor": auc(genuine, impostor),
                                   "d_prime": dprime(genuine, impostor), "threshold_sweep_SYNTHETIC_ONLY": sweep(genuine, impostor)}
    s5["note"] = "Synthetic-only. Impostors are other generated voices (several share a synthesiser), the owner is a generated voice, and the thresholds are TEST-ONLY. Not FAR/FRR for any person."
    report["stages"]["S5_identity_matching"] = s5

    # return to identity A for the remaining stages
    http.delete("/voice-identity/profile", headers=CSRF) if (reauth() or True) else None
    enroll(first)
    ident = first
    genuine_clips = [c for c in by[ident] if c["group"] != "enroll"]
    impostor_clips = [c for v in voices if v != ident for c in by[v] if c["group"] != "enroll"][:: 7]

    # S6 malformed audio ------------------------------------------------------------------------------------------------
    good = phone[genuine_clips[0]["file"]]
    xg, _ = read_wav(good)
    def custom_wav(x, rate=16000, width=2, channels=1):
        out = io.BytesIO()
        with wave.open(out, "wb") as w:
            w.setnchannels(channels); w.setsampwidth(width); w.setframerate(rate)
            if width == 1:
                w.writeframes(((np.clip(x, -1, 1) * 127) + 128).astype("u1").tobytes())
            else:
                w.writeframes((np.clip(x, -1, 1) * 32767).astype("<i2").tobytes())
        return out.getvalue()
    mp3 = None
    try:
        import av
        mp3 = io.BytesIO()
        pcm = (resample(xg, 16000, 16000) * 32767).astype("<i2")
        with av.open(mp3, "w", format="mp3") as cont:
            st = cont.add_stream("libmp3lame", rate=16000); st.layout = "mono"
            for i in range(0, len(pcm) - 1152, 1152):
                fr = av.AudioFrame.from_ndarray(pcm[i:i + 1152][None, :], format="s16", layout="mono"); fr.sample_rate = 16000
                for p in st.encode(fr): cont.mux(p)
            for p in st.encode(None): cont.mux(p)
        mp3 = mp3.getvalue()
    except Exception:
        mp3 = None
    huge_header = bytearray(good[:44]); huge_header[40:44] = (1_000_000_000).to_bytes(4, "little")
    cases = [
        ("empty body", b"", {422}), ("plain text", b"hello this is not audio at all" * 4, {422}), ("RIFF header only", good[:44], {200, 422}),
        ("truncated mid-file", good[: len(good) // 2], {200, 422}), ("header claims 1 GB of data", bytes(huge_header) + good[44:200], {200, 422}),
        ("random bytes after a valid header", good[:44] + os.urandom(64000), {200, 422}), ("8-bit PCM", custom_wav(xg, width=1), {200, 422}),
        ("stereo", custom_wav(np.repeat(xg, 2), channels=2), {200, 422}), ("8 kHz", custom_wav(resample(xg, 16000, 8000), rate=8000), {200, 422}),
        ("44.1 kHz", custom_wav(resample(xg, 16000, 44100), rate=44100), {200, 422}), ("0.2 s of speech", custom_wav(xg[:3200]), {200, 422}),
        ("3 s digital silence", custom_wav(np.zeros(48000)), {200, 422}), ("3 s DC offset", custom_wav(np.full(48000, 0.5)), {200, 422}),
        ("3 s full-scale square wave", custom_wav(np.sign(np.sin(np.arange(48000) * 0.05))), {200, 422}), ("3 s white noise", custom_wav(rng.uniform(-0.5, 0.5, 48000)), {200, 422}),
        ("20 s of valid speech (a long clip, not malformed)", custom_wav(np.tile(xg, 8)[: 16000 * 20]), {200}), ("over 2 MiB", good[:44] + bytes(2 * 1024 * 1024 + 10), {413}),
        ("MP3 bytes, not WAV", mp3 or b"", {422}),
    ]
    s6 = []
    for name, data, ok_codes in cases:
        row = {"case": name}
        for path in ("/voice-identity/verify", "/voice-identity/enrollment/samples", "/voice-identity/turn?converse=false"):
            utt_counter[0] += 1
            r, took = post(path, data, f"m{utt_counter[0]}")
            body = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
            state = body.get("state") or (body.get("voice") or {}).get("state")
            row[path.split("/")[-1].split("?")[0]] = {"http": r.status_code, "state": state, "ms": round(took * 1000)}
            if r.status_code >= 500:
                fail("S6", f"{name} -> {path}: HTTP {r.status_code} (a malformed upload must never be a server error)")
            elif r.status_code not in ok_codes | {422}:
                fail("S6", f"{name} -> {path}: unexpected HTTP {r.status_code}")
            if state == "verified" and not name.startswith("20 s of valid"):
                fail("S6", f"{name} -> {path}: VERIFIED (must never happen for malformed or non-speech audio)")
        s6.append(row)
    http.delete("/voice-identity/enrollment", headers=CSRF)   # drop any draft the enrolment-route cases created
    report["stages"]["S6_malformed_audio"] = {"cases": s6, "pass": not any(f["stage"] == "S6" for f in report["failures"])}

    # S7 conversation fallback -------------------------------------------------------------------------------------------
    s7 = {}
    turn_lat = {"converse_false": [], "converse_true": []}
    speech = phone[genuine_clips[2]["file"]]
    for label, q in (("converse_false", "?converse=false"), ("converse_true", "")):
        r, took = post("/voice-identity/turn" + q, speech, f"t-{label}")
        body = r.json()
        turn_lat[label].append(took)
        s7[f"normal_{label}"] = {"http": r.status_code, "transcript": body.get("transcript"), "voice_state": body.get("voice", {}).get("state"), "reply_present": bool(body.get("message"))}
    real_embedder = service.embedder
    service.embedder = TimedEmbedder(SidecarEmbeddingClient("http://127.0.0.1:1"))   # speaker service "down"
    r, took = post("/voice-identity/turn", speech, "t-down")
    body = r.json()
    turn_lat["converse_true"].append(took)
    s7["speaker_service_down"] = {"http": r.status_code, "transcript": body.get("transcript"), "reply_present": bool(body.get("message")), "voice_state": body.get("voice", {}).get("state"),
                                  "reasons": body.get("voice", {}).get("reasons"), "session_still_valid": http.get("/auth/me").status_code == 200}
    service.embedder = real_embedder
    http.delete("/voice-identity/profile", headers=CSRF) if (reauth() or True) else None
    r, took = post("/voice-identity/turn", speech, "t-noprofile")
    body = r.json()
    s7["no_profile"] = {"http": r.status_code, "reply_present": bool(body.get("message")), "voice_state": body.get("voice", {}).get("state"), "reasons": body.get("voice", {}).get("reasons")}
    r, _ = post("/voice-identity/turn", custom_wav(np.zeros(48000)), "t-silence")
    s7["silent_clip"] = {"http": r.status_code, "note": "no speech: the hub answers 422 and the app keeps listening"}
    enroll(first)
    for k, v in s7.items():
        if k.startswith(("normal", "speaker", "no_profile")) and not (v.get("http") == 200 and v.get("reply_present") is not False or k.endswith("converse_false")):
            fail("S7", f"{k}: {v}")
    if s7["speaker_service_down"]["voice_state"] != "unavailable" or not s7["speaker_service_down"]["reply_present"]:
        fail("S7", "conversation did not survive a speaker-service outage")
    report["stages"]["S7_conversation_fallback"] = s7

    # S8 degradations ---------------------------------------------------------------------------------------------------
    conditions = []
    for snr in (20, 10, 5, 0):
        conditions.append((f"white noise SNR {snr} dB", lambda x, r_=snr: add_noise(x, r_, rng)))
    for rt in (0.3, 0.6, 1.0):
        conditions.append((f"reverberation RT60 {rt} s", lambda x, r_=rt: reverb(x, r_, 16000, rng)))
    conditions += [("MP3 64 kbit/s", lambda x: codec(x, 16000, "mp3", 64000)), ("MP3 24 kbit/s", lambda x: codec(x, 16000, "mp3", 24000)),
                   ("AAC 32 kbit/s", lambda x: codec(x, 16000, "aac", 32000)), ("Opus 12 kbit/s", lambda x: codec(x, 16000, "opus", 12000)),
                   ("telephone band (8 kHz, 300-3400 Hz)", lambda x: telephone(x, 16000)),
                   ("resample 16k->8k->16k", lambda x: resample(resample(x, 16000, 8000), 8000, 16000)),
                   ("resample 16k->44.1k->16k", lambda x: resample(resample(x, 16000, 44100), 44100, 16000)),
                   ("resample 16k->22.05k->16k", lambda x: resample(resample(x, 16000, 22050), 22050, 16000)),
                   ("low volume (-30 dB)", lambda x: x * 10 ** (-30 / 20)), ("clipping (x8 gain)", lambda x: np.clip(x * 8, -1, 1))]
    g_sample = genuine_clips[:: (2 if args.quick else 1)][:13]
    i_sample = impostor_clips[:12]
    baseline_g = [verify(phone[c["file"]])[3] for c in g_sample]
    baseline_i = [verify(phone[c["file"]])[3] for c in i_sample]
    s8 = {"baseline": {"genuine_score": dist([s for s in baseline_g if s is not None]), "impostor_score": dist([s for s in baseline_i if s is not None])}, "conditions": []}
    base_wer = [wer(c["text"], timed_stt.inner.transcribe(phone[c["file"]])) for c in g_sample[:6]]
    s8["baseline"]["wer_on_6_genuine_clips"] = round(sum(e for e, _ in base_wer) / sum(n for _, n in base_wer), 4)
    for name, fn in conditions:
        gs, is_, gstates, istates, w_e, w_n = [], [], defaultdict(int), defaultdict(int), 0, 0
        try:
            for k, c in enumerate(g_sample):
                x, _ = read_wav(phone[c["file"]])
                y = fn(x)
                wav = to_wav(y)
                code, state, reasons, score, _ = verify(wav)
                gstates[state or f"http{code}"] += 1
                if score is not None:
                    gs.append(score)
                if k < 6:
                    e, n = wer(c["text"], timed_stt.inner.transcribe(wav)); w_e += e; w_n += n
            for c in i_sample:
                x, _ = read_wav(phone[c["file"]])
                code, state, reasons, score, _ = verify(to_wav(fn(x)))
                istates[state or f"http{code}"] += 1
                if score is not None:
                    is_.append(score)
                if state == "verified":
                    observe("S8", f"{name}: generated voice {c['voice']} accepted (score {score:.3f}) at the TEST-ONLY threshold")
        except Exception as exc:
            fail("S8", f"{name}: {exc!r}")
            s8["conditions"].append({"condition": name, "error": repr(exc)})
            continue
        s8["conditions"].append({"condition": name, "genuine_score": dist(gs), "genuine_states": dict(gstates), "genuine_score_change_median": round(statistics.median(gs) - statistics.median([b for b in baseline_g if b is not None]), 4) if gs else None,
                                 "impostor_states": dict(istates), "impostor_score_max": round(max(is_), 4) if is_ else None, "wer_on_6_genuine_clips": round(w_e / max(w_n, 1), 4)})
    s8["note"] = "Applied to synthetic speech; the noise, room and codec models are simple stand-ins (white noise, exponentially decaying random impulse response, PyAV encoders). Indicative of sensitivity, not of a real room or phone."
    report["stages"]["S8_degradations"] = s8

    # S9 digital replay (file re-submission) ----------------------------------------------------------------------------------------
    s9 = {"label": "DIGITAL REPLAY: previously generated WAV files are re-submitted to the endpoint. This is not a physical replay attack (no loudspeaker, room or microphone) and says nothing about replay resistance."}
    first_pass = [(c, verify(phone[c["file"]])) for c in g_sample]
    second_pass = [verify(phone[c["file"]]) for c in g_sample]
    s9["identical_bytes_resubmitted"] = {"clips": len(g_sample), "same_state": sum(a[1][1] == b[1] for a, b in zip(first_pass, second_pass)),
                                         "max_abs_score_difference": round(max(abs((a[1][3] or 0) - (b[3] or 0)) for a, b in zip(first_pass, second_pass)), 6),
                                         "states": dict(defaultdict(int, {s: sum(1 for _, b in zip(first_pass, second_pass) if b[1] == s) for s in {b[1] for b in second_pass}}))}
    accepted = sum(b[1] == "verified" for b in second_pass)
    s9["verified_after_digital_replay"] = f"{accepted}/{len(g_sample)}"
    s9["interpretation"] = "As designed, replay_protection is 'none': a file that verified once verifies again. No anti-spoof model exists."
    # ledger: the same utterance id twice, and an old id after a newer turn
    utt = "replay-same-id"
    post("/voice-identity/verify", phone[g_sample[0]["file"]], utt)
    post("/voice-identity/verify", phone[g_sample[1]["file"]], "replay-newer")
    s9["old_utterance_evidence_after_newer_turn"] = "absent" if score_of(utt) is None else "PRESENT"
    s9["current_utterance_evidence"] = "present" if score_of("replay-newer") is not None else "ABSENT"
    if s9["old_utterance_evidence_after_newer_turn"] != "absent":
        fail("S9", "evidence for an older utterance was still retrievable after a newer turn")
    # a re-encoded copy (lossy file replay) and a loop-back resample
    re_enc = [verify(to_wav(codec(read_wav(phone[c["file"]])[0], 16000, "mp3", 64000))) for c in g_sample[:6]]
    s9["re_encoded_mp3_copy_states"] = dict(defaultdict(int, {s: sum(1 for r_ in re_enc if r_[1] == s) for s in {r_[1] for r_ in re_enc}}))
    report["stages"]["S9_digital_replay"] = s9

    # S10 latency ------------------------------------------------------------------------------------------------------------------------
    report["stages"]["S10_latency_s"] = {
        "tts_synthesis_per_clip": lat([c["synth_s"] for c in manifest["clips"]]),
        "tts_by_engine": {e: lat([c["synth_s"] for c in manifest["clips"] if c["engine"] == e]) for e in ("piper", "espeak")},
        "resample_to_16k": lat(conv_times), "stt_direct": report["stages"]["S3_stt"]["latency_s"], "speaker_embedding_service": report["stages"]["S4_embeddings"]["latency_s"]["service_embedding"],
        "hub_verify_endpoint_end_to_end": lat(verify_lat), "hub_turn_converse_false": lat(turn_lat["converse_false"]), "hub_turn_with_conversation": lat(turn_lat["converse_true"]),
        "clip_length_seconds": dist([c["seconds"] for c in clips]),
        "note": "Dev box (20 CPUs, shared with other work), all stages on CPU, in-process hub (no network between phone and hub, no Tailscale), in-memory core. Homelab and phone numbers will differ.",
    }
    report["stages"]["S10_latency_s"]["hub_verify_endpoint_end_to_end"]["includes"] = "request parse, embedding service HTTP call, decrypt, score, ledger"

    # wrap up ---------------------------------------------------------------------------------------------------------------------------
    http.portal.call(store.close)
    client_ctx.__exit__(None, None, None)
    with psycopg.connect(root, autocommit=True) as conn:
        conn.execute(psycopg.sql.SQL("DROP DATABASE {} WITH (FORCE)").format(psycopg.sql.Identifier(dbname)))
    report["isolation_cleanup"] = "throw-away database dropped; key discarded"
    Path(args.out).write_text(json.dumps(report, indent=1, default=str))
    print(f"report written: {args.out}; failure cases: {len(report['failures'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
